import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import OrderCreateRequest, OrderCreateResponse, OrderOut
from app.services import orders as order_service
from app.services.orders import PRODUCT_CATALOG
from app.services import sheets as sheet_service
from app.services.tracking import meta as meta_capi
from app.services.tracking import tiktok as tiktok_capi
from app.services.tracking import snapchat as snap_capi
from app.services.geoip import check_ip
from app.services.whatsapp import format_delivery_address, send_order_confirmation
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    host = request.client.host if request.client else "unknown"
    if host in ("127.0.0.1", "::1"):
        logger.warning(
            "Client IP is %s — reverse proxy may not be forwarding X-Forwarded-For",
            host,
        )
    return host


@router.post("", response_model=OrderCreateResponse, status_code=201)
async def create_order(
    payload: OrderCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    country_code: Optional[str] = None
    geo_is_vpn = False
    geo_is_proxy = False
    geo_is_valid = False
    geo_block_reason: Optional[str] = None

    # GeoIP lookup for analytics only — orders are never blocked here
    geo_result = check_ip(client_ip)
    country_code = geo_result.country_code
    geo_is_vpn = bool(geo_result.is_vpn)
    geo_is_proxy = bool(geo_result.is_proxy)
    geo_is_valid = True
    geo_block_reason = geo_result.reason or None

    try:
        order = order_service.create_order(
            db=db,
            request=payload,
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if hasattr(order, "country_code"):
        order.country_code = country_code or "MA"
    if hasattr(order, "geo_is_valid"):
        order.geo_is_vpn = geo_is_vpn
        order.geo_is_proxy = geo_is_proxy
        order.geo_is_valid = geo_is_valid
        order.geo_block_reason = geo_block_reason[:255] if geo_block_reason else None
        db.commit()

    items_for_tracking = [
        {
            "product_id": item.product_id,
            "unit_count": item.unit_count,
            "price_mad": float(item.price_mad),
        }
        for item in order.items
    ]

    event_source_url = (
        f"{settings.PUBLIC_SITE_URL}/thank-you/{order.order_number}"
    )

    items_list = list(order.items)

    product_names = "/".join(i.product_name_ar for i in items_list)
    skus = "/".join(PRODUCT_CATALOG.get(i.product_id, {}).get("sku", "") for i in items_list)
    quantities = "/".join(str(i.unit_count) for i in items_list)

    sheet_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # Sheet payload — matches: date, order ID, Country, name, phone, product, SKU, quantity, total price, currency, status
    sheet_payload = {
        "date": sheet_date,
        "order_id": order.order_number,
        "country": "Morocco",
        "name": order.customer_name,
        "phone": order.phone_digits,
        "city": getattr(payload.customer, "city", "") or "",
        "address": getattr(payload.customer, "address", "") or "",
        "product": product_names,
        "sku": skus,
        "quantity": quantities,
        "total_price": float(order.total_mad),
        "currency": "MAD",
        "status": "",
    }

    sheet_resp = await sheet_service.send_order_to_sheet(sheet_payload)
    order.sheet_response = json.dumps(sheet_resp, ensure_ascii=False, default=str)
    if not sheet_resp.get("success"):
        order.status = "sheet_failed"
    else:
        order.status = "sent_to_sheet"
    db.commit()

    if settings.WHATSAPP_AUTO_CONFIRM and order.status == "sent_to_sheet":
        product_label = " / ".join(i.product_name_ar for i in items_list)
        delivery_address = format_delivery_address(
            city=payload.customer.city,
            address=payload.customer.address,
            admin_notes=order.admin_notes,
        )
        wa_resp = await send_order_confirmation(
            phone_e164=order.phone_e164,
            customer_name=order.customer_name,
            order_number=order.order_number,
            delivery_address=delivery_address,
            product_label=product_label,
            total_mad=float(order.total_mad),
        )
        order_service.log_tracking_event(
            db,
            order,
            "whatsapp",
            "order_confirmation",
            {
                "order_number": order.order_number,
                "template": settings.WHATSAPP_ORDER_TEMPLATE,
            },
            wa_resp,
        )
        if wa_resp.get("success"):
            order.status = "confirmation_sent"
        db.commit()

    # CAPI events - fire and forget; failures logged
    tracking_results: dict = {}

    capi_context = {
        "order_number": order.order_number,
        "total_mad": float(order.total_mad),
        "item_count": len(items_for_tracking),
        "event_source_url": event_source_url,
    }

    meta_resp = await meta_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_mad=float(order.total_mad),
        items=items_for_tracking,
        event_source_url=event_source_url,
        fbp=order.fbp,
        fbc=order.fbc,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["meta"] = meta_resp
    order_service.log_tracking_event(db, order, "meta", "Purchase", capi_context, meta_resp)

    tt_resp = await tiktok_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_mad=float(order.total_mad),
        items=items_for_tracking,
        event_source_url=event_source_url,
        ttp=order.ttp,
        ttclid=order.ttclid,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["tiktok"] = tt_resp
    order_service.log_tracking_event(db, order, "tiktok", "CompletePayment", capi_context, tt_resp)

    sc_cookie1 = payload.attribution.sc_cookie1 if payload.attribution else None

    snap_resp = await snap_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_mad=float(order.total_mad),
        items=items_for_tracking,
        event_source_url=event_source_url,
        sc_click_id=order.sc_click_id,
        sc_cookie1=sc_cookie1,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["snapchat"] = snap_resp
    order_service.log_tracking_event(db, order, "snapchat", "PURCHASE", capi_context, snap_resp)

    order.tracking_response = json.dumps(tracking_results, ensure_ascii=False, default=str)
    db.commit()

    return OrderCreateResponse(
        order_id=str(order.id),
        order_number=order.order_number,
        event_id=order.event_id,
        total_mad=order.total_mad,
        currency=order.currency,
    )


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: str, db: Session = Depends(get_db)):
    from app.models import Order
    order = db.query(Order).filter(
        (Order.id == order_id) | (Order.order_number == order_id)
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    return OrderOut(
        order_id=str(order.id),
        order_number=order.order_number,
        status=order.status,
        customer_name=order.customer_name,
        total_mad=order.total_mad,
        currency=order.currency,
        payment_method=order.payment_method,
        items=[
            {
                "product_id": i.product_id,
                "product_name_ar": i.product_name_ar,
                "offer_id": i.offer_id,
                "quantity": i.quantity,
                "unit_count": i.unit_count,
                "price_mad": i.price_mad,
                "source": i.source,
            }
            for i in order.items
        ],
        created_at=order.created_at.isoformat(),
    )
