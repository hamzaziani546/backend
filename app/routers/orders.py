import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import OrderCreateRequest, OrderCreateResponse, OrderOut
from app.services import orders as order_service
from app.services import sheets as sheet_service
from app.services.tracking import meta as meta_capi
from app.services.tracking import tiktok as tiktok_capi
from app.services.tracking import snapchat as snap_capi
from app.services.geoip import check_ip
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orders", tags=["orders"])


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _normalize_phone(phone: str) -> str:
    """Strip to digits, remove leading +966 or 966, keep local format."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("966"):
        digits = "0" + digits[3:]
    return digits


def _is_phone_whitelisted(phone: str) -> bool:
    normalized = _normalize_phone(phone)
    return any(
        normalized == _normalize_phone(wp)
        for wp in settings.whitelisted_phones
    )


@router.post("", response_model=OrderCreateResponse, status_code=201)
async def create_order(
    payload: OrderCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    # GeoIP fraud check — skip for whitelisted phone numbers
    if not _is_phone_whitelisted(payload.customer.phone):
        geo_result = check_ip(client_ip)
        if not geo_result.allowed:
            logger.warning(
                "Order blocked | ip=%s country=%s vpn=%s proxy=%s reason=%s phone=%s",
                client_ip,
                geo_result.country_code,
                geo_result.is_vpn,
                geo_result.is_proxy,
                geo_result.reason,
                payload.customer.phone,
            )
            raise HTTPException(
                status_code=403,
                detail="عذراً، الخدمة متاحة فقط داخل المملكة العربية السعودية",
            )

    try:
        order = order_service.create_order(
            db=db,
            request=payload,
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    items_for_tracking = [
        {
            "product_id": item.product_id,
            "unit_count": item.unit_count,
            "price_sar": float(item.price_sar),
        }
        for item in order.items
    ]

    event_source_url = (
        f"{settings.PUBLIC_SITE_URL}/thank-you/{order.order_number}"
    )

    # Sheet payload
    sheet_payload = {
        "order_id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "customer_name": order.customer_name,
        "phone_e164": order.phone_e164,
        "total_sar": float(order.total_sar),
        "currency": order.currency,
        "payment_method": order.payment_method,
        "items": [
            {
                "product_id": i.product_id,
                "product_name_ar": i.product_name_ar,
                "offer_id": i.offer_id,
                "quantity": i.quantity,
                "unit_count": i.unit_count,
                "price_sar": float(i.price_sar),
                "source": i.source,
            }
            for i in order.items
        ],
        "upsell_accepted": any(i.source == "checkout_upsell" for i in order.items),
        "utm_source": order.utm_source,
        "utm_medium": order.utm_medium,
        "utm_campaign": order.utm_campaign,
        "utm_content": order.utm_content,
        "utm_term": order.utm_term,
        "landing_page": order.landing_page,
        "event_id": order.event_id,
        "fbp": order.fbp,
        "fbc": order.fbc,
        "ttp": order.ttp,
        "ttclid": order.ttclid,
        "sc_click_id": order.sc_click_id,
        "client_ip": order.client_ip,
        "user_agent": order.user_agent,
        "notes": "",
    }

    sheet_resp = await sheet_service.send_order_to_sheet(sheet_payload)
    order.sheet_response = json.dumps(sheet_resp, ensure_ascii=False, default=str)
    if not sheet_resp.get("success"):
        order.status = "sheet_failed"
    else:
        order.status = "sent_to_sheet"
    db.commit()

    # CAPI events - fire and forget; failures logged
    tracking_results: dict = {}

    meta_resp = await meta_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_sar=float(order.total_sar),
        items=items_for_tracking,
        event_source_url=event_source_url,
        fbp=order.fbp,
        fbc=order.fbc,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["meta"] = meta_resp
    order_service.log_tracking_event(db, order, "meta", "Purchase", sheet_payload, meta_resp)

    tt_resp = await tiktok_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_sar=float(order.total_sar),
        items=items_for_tracking,
        event_source_url=event_source_url,
        ttp=order.ttp,
        ttclid=order.ttclid,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["tiktok"] = tt_resp
    order_service.log_tracking_event(db, order, "tiktok", "CompletePayment", sheet_payload, tt_resp)

    snap_resp = await snap_capi.send_purchase_event(
        order_number=order.order_number,
        phone_digits=order.phone_digits,
        total_sar=float(order.total_sar),
        items=items_for_tracking,
        event_source_url=event_source_url,
        client_ip=order.client_ip,
        user_agent=order.user_agent,
    )
    tracking_results["snapchat"] = snap_resp
    order_service.log_tracking_event(db, order, "snapchat", "PURCHASE", sheet_payload, snap_resp)

    order.tracking_response = json.dumps(tracking_results, ensure_ascii=False, default=str)
    db.commit()

    return OrderCreateResponse(
        order_id=str(order.id),
        order_number=order.order_number,
        event_id=order.event_id,
        total_sar=order.total_sar,
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
        total_sar=order.total_sar,
        currency=order.currency,
        payment_method=order.payment_method,
        items=[
            {
                "product_id": i.product_id,
                "product_name_ar": i.product_name_ar,
                "offer_id": i.offer_id,
                "quantity": i.quantity,
                "unit_count": i.unit_count,
                "price_sar": i.price_sar,
                "source": i.source,
            }
            for i in order.items
        ],
        created_at=order.created_at.isoformat(),
    )
