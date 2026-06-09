import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import OrderCreateRequest, OrderCreateResponse, OrderOut
from app.services import orders as order_service
from app.services.orders import PRODUCT_CATALOG
from app.services.geoip import check_ip
from app.services.order_followups import process_order_followups
from app.services.order_lookup import order_lookup_filter

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
    background_tasks: BackgroundTasks,
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

    sc_cookie1 = payload.attribution.sc_cookie1 if payload.attribution else None
    background_tasks.add_task(
        process_order_followups,
        str(order.id),
        city=payload.customer.city,
        address=payload.customer.address,
        sc_cookie1=sc_cookie1,
        sheet_payload=sheet_payload,
    )

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
    order = db.query(Order).filter(order_lookup_filter(order_id)).first()
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
