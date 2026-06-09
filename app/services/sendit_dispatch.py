import asyncio
import logging
import re
from typing import Any

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


def _build_products_string(order: Order) -> str:
    parts: list[str] = []
    for item in order.items:
        count = item.unit_count or item.quantity
        parts.append(f"{item.product_name_ar} x{count}")
    return ", ".join(parts)[:500]


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


def build_delivery_payload(
    order: Order,
    district_id: int,
    pickup_district_id: int,
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
        "products_from_stock": 0,
        "products": _build_products_string(order),
        "packaging_id": settings.SENDIT_PACKAGING_ID,
        "option_exchange": 0,
        "delivery_exchange_id": "",
    }


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

        payload = build_delivery_payload(order, district_id, pickup_id)
        result = await client.create_delivery(payload)
        sendit_code = None
        if result.get("data") and isinstance(result["data"], dict):
            sendit_code = result["data"].get("code")

        response = {
            "success": bool(result.get("success")),
            "status_code": result.get("status_code"),
            "sendit_code": sendit_code,
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
                "Sendit delivery created order=%s code=%s",
                order.order_number,
                sendit_code,
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
