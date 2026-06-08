"""
Order service: validate, calculate, create, and dispatch.
Backend recalculates prices from trusted config - never trusts frontend totals.
"""
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Order, OrderItem, TrackingEvent
from app.schemas import OrderCreateRequest, OrderCreateResponse
from app.services.phone import normalize_ma_phone
from app.config import settings

logger = logging.getLogger(__name__)

# Trusted product/offer price config - source of truth for backend calculations
PRODUCT_CATALOG: dict[str, dict] = {
    "lutein-eye-glow-gummies": {
        "name_ar": "علكات شوت العين",
        "sku": "LMS-LEG-001",
        "offers": {
            "one": {"quantity": 1, "price_mad": Decimal("199")},
            "two": {"quantity": 2, "price_mad": Decimal("349")},
            "three": {"quantity": 3, "price_mad": Decimal("449")},
            "upsell": {"quantity": 1, "price_mad": Decimal("99")},
        },
    },
    "collagen-glow-gummies": {
        "name_ar": "علكات كولاجين الإشراقة",
        "sku": "LMS-CGG-002",
        "offers": {
            "one": {"quantity": 1, "price_mad": Decimal("199")},
            "two": {"quantity": 2, "price_mad": Decimal("349")},
            "three": {"quantity": 3, "price_mad": Decimal("449")},
            "upsell": {"quantity": 1, "price_mad": Decimal("99")},
        },
    },
    "chlorophyll-gummies": {
        "name_ar": "علكات الكلوروفيل",
        "sku": "LMS-CLG-003",
        "offers": {
            "one": {"quantity": 1, "price_mad": Decimal("199")},
            "two": {"quantity": 2, "price_mad": Decimal("349")},
            "three": {"quantity": 3, "price_mad": Decimal("449")},
            "upsell": {"quantity": 1, "price_mad": Decimal("99")},
        },
    },
}


def generate_order_number(db: Session) -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"LAMIS-{today}-"
    result = (
        db.query(Order)
        .filter(Order.order_number.like(f"{prefix}%"))
        .count()
    )
    seq = result + 1
    return f"{prefix}{seq:04d}"


def recalculate_order(items_in: list) -> tuple[list[dict], Decimal]:
    """
    Returns (validated_items, total_mad).
    Raises ValueError for unknown products or offers.
    """
    validated = []
    total = Decimal("0")

    for item in items_in:
        product = PRODUCT_CATALOG.get(item.product_id)
        if not product:
            raise ValueError(f"منتج غير معروف: {item.product_id}")

        offer = product["offers"].get(item.offer_id)
        if not offer:
            raise ValueError(
                f"عرض غير معروف: {item.offer_id} لمنتج {item.product_id}"
            )

        line_price = offer["price_mad"] * item.quantity
        total += line_price

        validated.append(
            {
                "product_id": item.product_id,
                "product_name_ar": product["name_ar"],
                "sku": product["sku"],
                "offer_id": item.offer_id,
                "quantity": item.quantity,
                "unit_count": offer["quantity"] * item.quantity,
                "price_mad": line_price,
                "source": item.source,
            }
        )

    return validated, total


def create_order(
    db: Session,
    request: OrderCreateRequest,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Order:
    phone_e164, phone_digits = normalize_ma_phone(request.customer.phone)
    validated_items, total_mad = recalculate_order(request.items)
    order_number = generate_order_number(db)

    attr = request.attribution or type("Attr", (), {
        "landing_page": None, "utm_source": None, "utm_medium": None,
        "utm_campaign": None, "utm_content": None, "utm_term": None,
        "fbp": None, "fbc": None, "ttp": None, "ttclid": None, "sc_click_id": None,
    })()

    delivery_note = ""
    city = getattr(request.customer, "city", "") or ""
    address = getattr(request.customer, "address", "") or ""
    if city or address:
        delivery_note = f"المدينة: {city}\nالعنوان: {address}".strip()

    order = Order(
        order_number=order_number,
        customer_name=request.customer.name.strip(),
        phone_e164=phone_e164,
        phone_digits=phone_digits,
        admin_notes=delivery_note or None,
        status="new",
        subtotal_mad=total_mad,
        discount_mad=Decimal("0"),
        total_mad=total_mad,
        currency="MAD",
        payment_method="cod",
        event_id=order_number,
        landing_page=getattr(attr, "landing_page", None),
        utm_source=getattr(attr, "utm_source", None),
        utm_medium=getattr(attr, "utm_medium", None),
        utm_campaign=getattr(attr, "utm_campaign", None),
        utm_content=getattr(attr, "utm_content", None),
        utm_term=getattr(attr, "utm_term", None),
        fbp=getattr(attr, "fbp", None),
        fbc=getattr(attr, "fbc", None),
        ttp=getattr(attr, "ttp", None),
        ttclid=getattr(attr, "ttclid", None),
        sc_click_id=getattr(attr, "sc_click_id", None),
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(order)
    db.flush()

    for item_data in validated_items:
        db_fields = {k: v for k, v in item_data.items() if k != "sku"}
        db_item = OrderItem(order_id=order.id, **db_fields)
        db.add(db_item)

    db.commit()
    db.refresh(order)
    logger.info("Order created: %s id=%s", order.order_number, order.id)
    return order


def log_tracking_event(
    db: Session,
    order: Order,
    platform: str,
    event_name: str,
    context: dict,
    response: dict,
) -> None:
    """
    Persist a CAPI event log record.
    `context` is non-PII metadata about the request (order_number, total, etc.).
    `response` is the raw dict returned by the CAPI service function.
    """
    import json as _json
    te = TrackingEvent(
        order_id=order.id,
        platform=platform,
        event_name=event_name,
        event_id=order.order_number,
        payload_json=_json.dumps(context, ensure_ascii=False, default=str),
        response_json=_json.dumps(response, ensure_ascii=False, default=str),
        status_code=response.get("status_code"),
        success=bool(response.get("success", False)),
    )
    db.add(te)
    db.commit()
    logger.info(
        "CAPI log saved | platform=%s event=%s order=%s success=%s status=%s",
        platform,
        event_name,
        order.order_number,
        te.success,
        te.status_code,
    )
