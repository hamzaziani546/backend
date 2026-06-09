import asyncio
import json
import logging
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, TrackingEvent
from app.services import orders as order_service
from app.services.delivery_notes import parse_city_address
from app.services.order_lookup import order_lookup_filter
from app.services.sendit import SenditClient, map_city_for_sendit

logger = logging.getLogger(__name__)


def _format_phone(phone_digits: str, phone_e164: str) -> str:
    digits = re.sub(r"\D", "", phone_digits or phone_e164 or "")
    if digits.startswith("212") and len(digits) >= 12:
        return "0" + digits[3:]
    if digits.startswith("0"):
        return digits
    if len(digits) == 9:
        return "0" + digits
    return digits


def _reference_map() -> dict[str, str]:
    raw = settings.SENDIT_REFERENCE_MAP
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        logger.warning("Invalid SENDIT_REFERENCE_MAP JSON")
        return {}


def _catalog_sku(product_id: str) -> Optional[str]:
    product = order_service.PRODUCT_CATALOG.get(product_id)
    if product:
        return str(product.get("sku") or "").strip() or None
    return None


def resolve_sendit_reference(
    product_id: str,
    product_name_ar: str,
    stock_products: list[dict[str, Any]],
    ref_map: dict[str, str],
) -> Optional[str]:
    """Map order line to Sendit stock product reference."""
    pid = (product_id or "").strip()
    if pid in ref_map:
        return ref_map[pid]

    sku = _catalog_sku(pid)
    if sku and sku in ref_map:
        return ref_map[sku]

    if pid.startswith("lp-"):
        lp_key = pid[3:].upper()
        if lp_key in ref_map:
            return ref_map[lp_key]
        sku = lp_key

    candidates: list[str] = []
    if sku:
        candidates.append(sku)
        candidates.append(sku.lower())

    for candidate in candidates:
        for row in stock_products:
            ref = str(row.get("reference") or "").strip()
            if ref and ref.lower() == candidate.lower():
                return ref

    name = (product_name_ar or "").strip()
    if name:
        for row in stock_products:
            stock_name = str(row.get("name") or "").strip()
            if stock_name and (name in stock_name or stock_name in name):
                return str(row.get("reference") or "").strip() or None

    return None


def _build_stock_products_field(
    order: Order,
    stock_products: list[dict[str, Any]],
    ref_map: dict[str, str],
) -> tuple[str, list[str]]:
    """Build Sendit products string: reference:qty,reference:qty"""
    parts: list[str] = []
    missing: list[str] = []
    for item in order.items:
        qty = item.unit_count or item.quantity or 1
        ref = resolve_sendit_reference(
            item.product_id,
            item.product_name_ar,
            stock_products,
            ref_map,
        )
        if not ref:
            missing.append(f"{item.product_id} ({item.product_name_ar})")
            continue
        parts.append(f"{ref}:{qty}")
    return ",".join(parts), missing


def _build_text_products_field(order: Order) -> str:
    parts: list[str] = []
    for item in order.items:
        count = item.unit_count or item.quantity
        parts.append(f"{item.product_name_ar} x{count}")
    return ", ".join(parts)[:500]


def build_delivery_payload(
    order: Order,
    district_id: int,
    pickup_district_id: int,
    *,
    products_field: str,
    products_from_stock: int,
) -> dict[str, Any]:
    city, address = parse_city_address(order.admin_notes)
    full_address = ", ".join(p for p in (address, city) if p).strip(", ")

    return {
        "pickup_district_id": pickup_district_id,
        "district_id": district_id,
        "name": order.customer_name,
        "amount": float(order.total_mad),
        "address": full_address or city or "—",
        "phone": _format_phone(order.phone_digits, order.phone_e164),
        "comment": f"LAMIS {order.order_number}",
        "reference": order.order_number,
        "allow_open": settings.SENDIT_ALLOW_OPEN,
        "allow_try": settings.SENDIT_ALLOW_TRY,
        "products_from_stock": products_from_stock,
        "products": products_field,
        "packaging_id": settings.SENDIT_PACKAGING_ID,
        "option_exchange": 0,
        "delivery_exchange_id": "",
    }


def already_sent_to_sendit(db: Session, order_id) -> bool:
    return (
        db.query(TrackingEvent)
        .filter(
            TrackingEvent.order_id == order_id,
            TrackingEvent.platform == "sendit",
            TrackingEvent.event_name == "create_delivery",
            TrackingEvent.success.is_(True),
        )
        .first()
        is not None
    )


async def dispatch_order_to_sendit(db: Session, order: Order) -> dict[str, Any]:
    if not settings.SENDIT_AUTO_DISPATCH:
        return {"skipped": True, "reason": "SENDIT_AUTO_DISPATCH disabled"}
    if not settings.SENDIT_PUBLIC_KEY or not settings.SENDIT_PRIVATE_KEY:
        return {"skipped": True, "reason": "Sendit keys not configured"}
    if already_sent_to_sendit(db, order.id):
        return {"skipped": True, "reason": "already_sent"}
    if order.status in ("sent_to_carrier", "shipped", "delivered", "cancelled"):
        return {"skipped": True, "reason": f"status={order.status}"}

    city, _ = parse_city_address(order.admin_notes)
    if not city:
        err = {"success": False, "error": "missing_city"}
        order_service.log_tracking_event(
            db, order, "sendit", "create_delivery",
            {"order_number": order.order_number},
            err,
        )
        return err

    search_city = map_city_for_sendit(city)
    if not search_city:
        err = {"success": False, "error": f"unsupported_city:{city}"}
        order_service.log_tracking_event(
            db, order, "sendit", "create_delivery",
            {"order_number": order.order_number, "city": city},
            err,
        )
        return err

    client = SenditClient()
    try:
        pickup_id = settings.SENDIT_PICKUP_DISTRICT_ID
        if not pickup_id:
            pickup_id = await client.get_district_id(settings.SENDIT_PICKUP_DISTRICT)
        if not pickup_id:
            err = {"success": False, "error": "pickup_district_not_found"}
            order_service.log_tracking_event(
                db, order, "sendit", "create_delivery",
                {"order_number": order.order_number},
                err,
            )
            return err

        district_id = await client.get_district_id(search_city)
        if not district_id:
            err = {"success": False, "error": "district_not_found", "search_city": search_city}
            order_service.log_tracking_event(
                db, order, "sendit", "create_delivery",
                {"order_number": order.order_number, "search_city": search_city},
                err,
            )
            return err

        use_stock = settings.SENDIT_PRODUCTS_FROM_STOCK
        products_from_stock = 1 if use_stock else 0
        ref_map = _reference_map()

        if use_stock:
            stock_products = await client.list_stock_products()
            products_field, missing = _build_stock_products_field(
                order, stock_products, ref_map,
            )
            if missing:
                err = {
                    "success": False,
                    "error": "sendit_reference_not_found",
                    "missing": missing,
                }
                order_service.log_tracking_event(
                    db,
                    order,
                    "sendit",
                    "create_delivery",
                    {
                        "order_number": order.order_number,
                        "missing_products": missing,
                    },
                    err,
                )
                return err
            if not products_field:
                err = {"success": False, "error": "empty_products"}
                order_service.log_tracking_event(
                    db, order, "sendit", "create_delivery",
                    {"order_number": order.order_number},
                    err,
                )
                return err
        else:
            products_field = _build_text_products_field(order)

        payload = build_delivery_payload(
            order,
            district_id,
            pickup_id,
            products_field=products_field,
            products_from_stock=products_from_stock,
        )
        result = await client.create_delivery(payload)
        sendit_code = None
        if result.get("data") and isinstance(result["data"], dict):
            sendit_code = result["data"].get("code")

        response = {
            "success": bool(result.get("success")),
            "status_code": result.get("status_code"),
            "sendit_code": sendit_code,
            "sendit_status": (
                result.get("data", {}).get("status")
                if isinstance(result.get("data"), dict)
                else None
            ),
            "body": result.get("body"),
        }

        order_service.log_tracking_event(
            db,
            order,
            "sendit",
            "create_delivery",
            {
                "order_number": order.order_number,
                "city": city,
                "search_city": search_city,
                "district_id": district_id,
                "pickup_district_id": pickup_id,
                "products_from_stock": products_from_stock,
                "payload": payload,
            },
            response,
        )

        if response["success"] and sendit_code:
            note = f"[Sendit] code: {sendit_code}"
            order.admin_notes = (
                f"{order.admin_notes}\n{note}".strip() if order.admin_notes else note
            )
            order.status = "sent_to_carrier"
            db.commit()
            logger.info(
                "Sendit delivery created order=%s code=%s status=%s",
                order.order_number,
                sendit_code,
                response.get("sendit_status"),
            )

        return response
    except Exception as exc:
        logger.exception("Sendit dispatch failed order=%s", order.order_number)
        err_resp = {"success": False, "error": str(exc)}
        order_service.log_tracking_event(
            db, order, "sendit", "create_delivery",
            {"order_number": order.order_number},
            err_resp,
        )
        return err_resp


def dispatch_sendit_for_order_id(order_id: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        order = db.query(Order).filter(order_lookup_filter(order_id)).first()
        if not order:
            logger.warning("Sendit dispatch: order not found %s", order_id)
            return
        asyncio.run(dispatch_order_to_sendit(db, order))
    finally:
        db.close()
