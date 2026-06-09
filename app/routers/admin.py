import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderItem, Click, TrackingEvent, LandingPage
from app.services.uploads import save_admin_image
from app.services.landing_pages import (
    dump_gallery_images,
    dump_lp_products,
    normalize_slug,
    parse_gallery_images,
    parse_lp_products,
    serialize_landing_page,
)
from app.services.admin_auth import (
    issue_token,
    require_admin,
    verify_credentials,
)
from app.services.order_lookup import order_lookup_filter
from app.services.delivery_notes import parse_city_address
from app.services.sendit_dispatch import dispatch_sendit_for_order_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# Status taxonomy used by COD ops
ORDER_STATUSES = [
    "new",
    "sent_to_sheet",
    "confirmation_sent",
    "edit_requested",
    "contacted",
    "confirmed",
    "sent_to_carrier",
    "shipped",
    "delivered",
    "cancelled",
    "no_answer",
    "returned",
    "sheet_failed",
]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: int
    username: str


class StatusUpdate(BaseModel):
    status: str
    admin_notes: Optional[str] = None


class LpProductIn(BaseModel):
    id: Optional[str] = None
    name_ar: str
    price_mad: float
    compare_at_price_mad: Optional[float] = None
    image: str
    sku: str


class LandingPageIn(BaseModel):
    slug: str
    title_ar: str
    hero_image: str
    rating: float = 4.9
    review_count: int = 120
    products: list[LpProductIn]
    gallery_images: list[str] = []
    is_active: bool = True


class LandingPageUpdate(BaseModel):
    slug: Optional[str] = None
    title_ar: Optional[str] = None
    hero_image: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    products: Optional[list[LpProductIn]] = None
    gallery_images: Optional[list[str]] = None
    is_active: Optional[bool] = None


def _parse_date(value: Optional[str], default: datetime) -> datetime:
    if not value:
        return default
    try:
        # accept "YYYY-MM-DD" or full iso
        if len(value) == 10:
            dt = datetime.strptime(value, "%Y-%m-%d")
        else:
            dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return default


def _date_range(
    start: Optional[str], end: Optional[str]
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    default_end = now
    default_start = now - timedelta(days=30)
    s = _parse_date(start, default_start)
    e = _parse_date(end, default_end)
    # if "end" is a date-only, extend to end of day
    if end and len(end) == 10:
        e = e.replace(hour=23, minute=59, second=59)
    return s, e


CLEAN_COUNTRY_CODE = "MA"


def _clean_click_filters(start: datetime, end: datetime) -> list:
    return [
        Click.created_at >= start,
        Click.created_at <= end,
        Click.country_code == CLEAN_COUNTRY_CODE,
        Click.is_valid.is_(True),
        Click.is_vpn.is_(False),
        Click.is_proxy.is_(False),
    ]


def _clean_order_filters(start: datetime, end: datetime) -> list:
    return [
        Order.created_at >= start,
        Order.created_at <= end,
        Order.country_code == CLEAN_COUNTRY_CODE,
        Order.geo_is_valid.is_(True),
        Order.geo_is_vpn.is_(False),
        Order.geo_is_proxy.is_(False),
    ]


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest):
    if not verify_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token, exp = issue_token(body.username)
    return LoginResponse(token=token, expires_at=exp, username=body.username)


@router.get("/me")
def me(payload: dict = Depends(require_admin)):
    return {"username": payload.get("sub"), "exp": payload.get("exp")}


@router.get("/metrics")
def metrics(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    s, e = _date_range(start, end)

    clean_click_filters = _clean_click_filters(s, e)
    clean_order_filters = _clean_order_filters(s, e)

    valid_clicks_q = db.query(Click).filter(*clean_click_filters)
    total_clicks = valid_clicks_q.count()
    unique_visitors = (
        db.query(func.count(func.distinct(Click.visitor_id)))
        .filter(*clean_click_filters)
        .scalar()
        or 0
    )
    blocked_clicks = (
        db.query(Click)
        .filter(
            Click.created_at >= s,
            Click.created_at <= e,
            or_(
                Click.is_valid.is_(False),
                Click.country_code.is_(None),
                Click.country_code != CLEAN_COUNTRY_CODE,
                Click.is_vpn.is_(True),
                Click.is_proxy.is_(True),
            ),
        )
        .count()
    )

    orders_q = db.query(Order).filter(*clean_order_filters)
    total_orders = orders_q.count()
    revenue = (
        db.query(func.coalesce(func.sum(Order.total_mad), 0))
        .filter(*clean_order_filters)
        .scalar()
        or Decimal(0)
    )
    delivered_orders = orders_q.filter(Order.status == "delivered").count()
    cancelled_orders = orders_q.filter(
        Order.status.in_(["cancelled", "returned", "no_answer"])
    ).count()
    confirmed_orders = orders_q.filter(
        Order.status.in_(["confirmed", "sent_to_carrier", "shipped", "delivered"])
    ).count()

    aov = float(revenue) / total_orders if total_orders else 0.0
    conv_rate = (total_orders / total_clicks * 100) if total_clicks else 0.0
    confirm_rate = (confirmed_orders / total_orders * 100) if total_orders else 0.0
    delivery_rate = (delivered_orders / total_orders * 100) if total_orders else 0.0
    revenue_per_visitor = float(revenue) / unique_visitors if unique_visitors else 0.0

    # Status breakdown
    status_rows = (
        db.query(Order.status, func.count(Order.id))
        .filter(*clean_order_filters)
        .group_by(Order.status)
        .all()
    )
    status_breakdown = [{"status": s_, "count": c} for s_, c in status_rows]

    # UTM source breakdown
    utm_rows = (
        db.query(
            func.coalesce(Click.utm_source, "direct").label("src"),
            func.count(Click.id),
        )
        .filter(*clean_click_filters)
        .group_by("src")
        .order_by(func.count(Click.id).desc())
        .limit(10)
        .all()
    )
    utm_clicks_map = {src: cnt for src, cnt in utm_rows}

    utm_orders_rows = (
        db.query(
            func.coalesce(Order.utm_source, "direct").label("src"),
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_mad), 0),
        )
        .filter(*clean_order_filters)
        .group_by("src")
        .all()
    )
    utm_orders_map = {row[0]: (row[1], float(row[2])) for row in utm_orders_rows}

    utm_breakdown = []
    for src in set(list(utm_clicks_map.keys()) + list(utm_orders_map.keys())):
        clicks = utm_clicks_map.get(src, 0)
        orders, rev = utm_orders_map.get(src, (0, 0.0))
        utm_breakdown.append(
            {
                "source": src,
                "clicks": clicks,
                "orders": orders,
                "revenue": rev,
                "cvr": (orders / clicks * 100) if clicks else 0.0,
            }
        )
    utm_breakdown.sort(key=lambda x: x["clicks"], reverse=True)

    product_rows = (
        db.query(
            OrderItem.product_id,
            OrderItem.product_name_ar,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.unit_count),
            func.count(func.distinct(Order.id)),
            func.coalesce(func.sum(OrderItem.price_mad), 0),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .filter(*clean_order_filters)
        .group_by(OrderItem.product_id, OrderItem.product_name_ar)
        .order_by(func.coalesce(func.sum(OrderItem.price_mad), 0).desc())
        .limit(10)
        .all()
    )
    product_breakdown = [
        {
            "product_id": row[0],
            "product_name_ar": row[1],
            "line_quantity": int(row[2] or 0),
            "units_sold": int(row[3] or 0),
            "orders": int(row[4] or 0),
            "revenue": float(row[5] or 0),
        }
        for row in product_rows
    ]

    reason_expr = func.coalesce(Click.block_reason, "unknown").label("reason")
    invalid_reason_rows = (
        db.query(reason_expr, func.count(Click.id))
        .filter(
            Click.created_at >= s,
            Click.created_at <= e,
            or_(
                Click.is_valid.is_(False),
                Click.country_code.is_(None),
                Click.country_code != CLEAN_COUNTRY_CODE,
                Click.is_vpn.is_(True),
                Click.is_proxy.is_(True),
            ),
        )
        .group_by(reason_expr)
        .order_by(func.count(Click.id).desc())
        .limit(8)
        .all()
    )
    invalid_reasons = [
        {"reason": reason, "count": count} for reason, count in invalid_reason_rows
    ]

    # Daily timeseries
    if "sqlite" in db.bind.dialect.name:
        day_expr = func.strftime("%Y-%m-%d", Click.created_at)
        order_day = func.strftime("%Y-%m-%d", Order.created_at)
    else:
        day_expr = func.to_char(Click.created_at, "YYYY-MM-DD")
        order_day = func.to_char(Order.created_at, "YYYY-MM-DD")

    click_by_day = dict(
        db.query(day_expr, func.count(Click.id))
        .filter(*clean_click_filters)
        .group_by(day_expr)
        .all()
    )
    order_by_day_rows = (
        db.query(order_day, func.count(Order.id), func.coalesce(func.sum(Order.total_mad), 0))
        .filter(*clean_order_filters)
        .group_by(order_day)
        .all()
    )
    order_by_day = {row[0]: (row[1], float(row[2])) for row in order_by_day_rows}

    days: list[dict] = []
    cur = s.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = e.replace(hour=0, minute=0, second=0, microsecond=0)
    while cur <= end_day:
        key = cur.strftime("%Y-%m-%d")
        clicks = click_by_day.get(key, 0)
        orders, rev = order_by_day.get(key, (0, 0.0))
        days.append(
            {
                "date": key,
                "clicks": clicks,
                "orders": orders,
                "revenue": rev,
                "conversion_rate": (orders / clicks * 100) if clicks else 0.0,
            }
        )
        cur += timedelta(days=1)

    return {
        "range": {"start": s.isoformat(), "end": e.isoformat()},
        "summary": {
            "total_clicks": total_clicks,
            "unique_visitors": unique_visitors,
            "blocked_clicks": blocked_clicks,
            "total_orders": total_orders,
            "confirmed_orders": confirmed_orders,
            "delivered_orders": delivered_orders,
            "cancelled_orders": cancelled_orders,
            "revenue_mad": float(revenue),
            "aov_mad": aov,
            "revenue_per_visitor_mad": revenue_per_visitor,
            "conversion_rate": conv_rate,
            "confirm_rate": confirm_rate,
            "delivery_rate": delivery_rate,
        },
        "status_breakdown": status_breakdown,
        "utm_breakdown": utm_breakdown,
        "product_breakdown": product_breakdown,
        "invalid_reasons": invalid_reasons,
        "timeseries": days,
    }


def _serialize_order_summary(o: Order) -> dict:
    return {
        "id": str(o.id),
        "order_number": o.order_number,
        "customer_name": o.customer_name,
        "phone_digits": o.phone_digits,
        "phone_e164": o.phone_e164,
        "status": o.status,
        "total_mad": float(o.total_mad),
        "currency": o.currency,
        "items_count": sum(i.quantity for i in o.items),
        "utm_source": o.utm_source,
        "utm_campaign": o.utm_campaign,
        "country_code": getattr(o, "country_code", None),
        "geo_is_valid": getattr(o, "geo_is_valid", None),
        "geo_is_vpn": getattr(o, "geo_is_vpn", None),
        "geo_is_proxy": getattr(o, "geo_is_proxy", None),
        "geo_block_reason": getattr(o, "geo_block_reason", None),
        "created_at": o.created_at.isoformat(),
    }


@router.get("/orders")
def list_orders(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    traffic: str = Query("clean", pattern="^(clean|all)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    s, e = _date_range(start, end)

    q = db.query(Order).filter(Order.created_at >= s, Order.created_at <= e)
    if traffic == "clean":
        q = q.filter(
            Order.country_code == CLEAN_COUNTRY_CODE,
            Order.geo_is_valid.is_(True),
            Order.geo_is_vpn.is_(False),
            Order.geo_is_proxy.is_(False),
        )
    if status and status != "all":
        q = q.filter(Order.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            or_(
                Order.order_number.ilike(like),
                Order.customer_name.ilike(like),
                Order.phone_digits.ilike(like),
                Order.phone_e164.ilike(like),
            )
        )

    total = q.count()
    items = (
        q.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "traffic": traffic,
        "items": [_serialize_order_summary(o) for o in items],
    }


@router.get("/orders/{order_id}")
def order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    order = db.query(Order).filter(order_lookup_filter(order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items = [
        {
            "product_id": i.product_id,
            "product_name_ar": i.product_name_ar,
            "offer_id": i.offer_id,
            "quantity": i.quantity,
            "unit_count": i.unit_count,
            "price_mad": float(i.price_mad),
            "source": i.source,
        }
        for i in order.items
    ]

    tracking = [
        {
            "id": str(t.id),
            "platform": t.platform,
            "event_name": t.event_name,
            "event_id": t.event_id,
            "status_code": t.status_code,
            "success": t.success,
            "created_at": t.created_at.isoformat(),
        }
        for t in order.tracking_events
    ]

    city, address = parse_city_address(getattr(order, "admin_notes", None))

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "customer": {
            "name": order.customer_name,
            "phone_e164": order.phone_e164,
            "phone_digits": order.phone_digits,
            "city": city,
            "address": address,
        },
        "items": items,
        "totals": {
            "subtotal_mad": float(order.subtotal_mad),
            "discount_mad": float(order.discount_mad),
            "total_mad": float(order.total_mad),
            "currency": order.currency,
        },
        "payment_method": order.payment_method,
        "attribution": {
            "landing_page": order.landing_page,
            "utm_source": order.utm_source,
            "utm_medium": order.utm_medium,
            "utm_campaign": order.utm_campaign,
            "utm_content": order.utm_content,
            "utm_term": order.utm_term,
            "fbp": order.fbp,
            "fbc": order.fbc,
            "ttp": order.ttp,
            "ttclid": order.ttclid,
            "sc_click_id": order.sc_click_id,
        },
        "client_ip": order.client_ip,
        "user_agent": order.user_agent,
        "geo": {
            "country_code": getattr(order, "country_code", None),
            "is_valid": getattr(order, "geo_is_valid", None),
            "is_vpn": getattr(order, "geo_is_vpn", None),
            "is_proxy": getattr(order, "geo_is_proxy", None),
            "block_reason": getattr(order, "geo_block_reason", None),
        },
        "event_id": order.event_id,
        "admin_notes": getattr(order, "admin_notes", None),
        "tracking_events": tracking,
        "sheet_response": _safe_json(order.sheet_response),
        "tracking_response": _safe_json(order.tracking_response),
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }


def _safe_json(s: Optional[str]):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    body: StatusUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Allowed: {', '.join(ORDER_STATUSES)}",
        )
    order = db.query(Order).filter(order_lookup_filter(order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    old_status = order.status
    order.status = body.status
    if body.admin_notes is not None:
        order.admin_notes = body.admin_notes
    db.commit()
    if body.status == "confirmed" and old_status != "confirmed":
        background_tasks.add_task(dispatch_sendit_for_order_id, order_id)
    return {"ok": True, "status": order.status}


@router.get("/statuses")
def statuses(_admin: dict = Depends(require_admin)):
    return {"statuses": ORDER_STATUSES}


@router.get("/capi-logs")
def capi_logs(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    platform: Optional[str] = Query(None, description="meta | tiktok | snapchat"),
    success: Optional[bool] = Query(None),
    order_id: Optional[str] = Query(None, description="order_number or UUID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    """
    Return CAPI (Conversions API) event logs with full request/response bodies.
    Use this to debug pixel-to-CAPI deduplication and match quality.
    """
    s, e = _date_range(start, end)

    q = db.query(TrackingEvent).filter(
        TrackingEvent.created_at >= s,
        TrackingEvent.created_at <= e,
    )
    if platform:
        q = q.filter(TrackingEvent.platform == platform)
    if success is not None:
        q = q.filter(TrackingEvent.success.is_(success))
    if order_id:
        try:
            uid = uuid.UUID(order_id)
            matched = (
                db.query(Order.id)
                .filter((Order.id == uid) | (Order.order_number == order_id))
                .scalar()
            )
        except ValueError:
            matched = (
                db.query(Order.id)
                .filter(Order.order_number == order_id)
                .scalar()
            )
        if matched:
            q = q.filter(TrackingEvent.order_id == matched)
        else:
            return {"total": 0, "page": page, "page_size": page_size, "items": []}

    total = q.count()
    rows = (
        q.order_by(TrackingEvent.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": str(r.id),
            "order_id": str(r.order_id) if r.order_id else None,
            "platform": r.platform,
            "event_name": r.event_name,
            "event_id": r.event_id,
            "status_code": r.status_code,
            "success": r.success,
            "payload": _safe_json(r.payload_json),
            "response": _safe_json(r.response_json),
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

    success_count = db.query(TrackingEvent).filter(
        TrackingEvent.created_at >= s,
        TrackingEvent.created_at <= e,
        TrackingEvent.success.is_(True),
        *([TrackingEvent.platform == platform] if platform else []),
    ).count()

    fail_count = db.query(TrackingEvent).filter(
        TrackingEvent.created_at >= s,
        TrackingEvent.created_at <= e,
        TrackingEvent.success.is_(False),
        *([TrackingEvent.platform == platform] if platform else []),
    ).count()

    return {
        "total": total,
        "success_count": success_count,
        "fail_count": fail_count,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.post("/uploads")
async def upload_image(
    file: UploadFile = File(...),
    _admin: dict = Depends(require_admin),
):
    url = await save_admin_image(file)
    return {"url": url}


@router.get("/landing-pages")
def list_landing_pages(
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    rows = db.query(LandingPage).order_by(LandingPage.created_at.desc()).all()
    return {
        "items": [serialize_landing_page(lp, include_admin=True) for lp in rows],
    }


@router.get("/landing-pages/{lp_id}")
def get_landing_page_admin(
    lp_id: str,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    lp = db.query(LandingPage).filter(LandingPage.id == lp_id).first()
    if not lp:
        raise HTTPException(status_code=404, detail="Landing page not found")
    return serialize_landing_page(lp, include_admin=True)


@router.post("/landing-pages", status_code=201)
def create_landing_page(
    body: LandingPageIn,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    try:
        slug = normalize_slug(body.slug)
        gallery = parse_gallery_images(body.gallery_images)
        products = parse_lp_products([p.model_dump() for p in body.products])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if db.query(LandingPage).filter(LandingPage.slug == slug).first():
        raise HTTPException(status_code=409, detail="هذا الرابط مستخدم مسبقاً")

    lp = LandingPage(
        slug=slug,
        product_id=None,
        title_ar=body.title_ar.strip(),
        hero_image=body.hero_image.strip(),
        rating=body.rating,
        review_count=body.review_count,
        offers_json=dump_lp_products(products),
        gallery_images_json=dump_gallery_images(gallery),
        is_active=body.is_active,
    )
    db.add(lp)
    db.commit()
    db.refresh(lp)
    return serialize_landing_page(lp, include_admin=True)


@router.patch("/landing-pages/{lp_id}")
def update_landing_page(
    lp_id: str,
    body: LandingPageUpdate,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    lp = db.query(LandingPage).filter(LandingPage.id == lp_id).first()
    if not lp:
        raise HTTPException(status_code=404, detail="Landing page not found")

    try:
        if body.slug is not None:
            slug = normalize_slug(body.slug)
            clash = (
                db.query(LandingPage)
                .filter(LandingPage.slug == slug, LandingPage.id != lp.id)
                .first()
            )
            if clash:
                raise HTTPException(status_code=409, detail="هذا الرابط مستخدم مسبقاً")
            lp.slug = slug
        if body.products is not None:
            lp.offers_json = dump_lp_products(
                parse_lp_products([p.model_dump() for p in body.products])
            )
        if body.title_ar is not None:
            lp.title_ar = body.title_ar.strip()
        if body.hero_image is not None:
            lp.hero_image = body.hero_image.strip()
        if body.rating is not None:
            lp.rating = body.rating
        if body.review_count is not None:
            lp.review_count = body.review_count
        if body.gallery_images is not None:
            lp.gallery_images_json = dump_gallery_images(
                parse_gallery_images(body.gallery_images)
            )
        if body.is_active is not None:
            lp.is_active = body.is_active
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    db.commit()
    db.refresh(lp)
    return serialize_landing_page(lp, include_admin=True)


@router.delete("/landing-pages/{lp_id}", status_code=204)
def delete_landing_page(
    lp_id: str,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
):
    lp = db.query(LandingPage).filter(LandingPage.id == lp_id).first()
    if not lp:
        raise HTTPException(status_code=404, detail="Landing page not found")
    db.delete(lp)
    db.commit()
    return None


@router.get("/whatsapp/conversations")
async def whatsapp_conversations(
    page: int = Query(1, ge=1),
    status: str = Query("all"),
    _admin: dict = Depends(require_admin),
):
    from app.services import chatwoot

    return await chatwoot.list_conversations(page=page, status=status)


@router.get("/whatsapp/conversations/{conversation_id}/messages")
async def whatsapp_conversation_messages(
    conversation_id: int,
    _admin: dict = Depends(require_admin),
):
    from app.services import chatwoot

    return await chatwoot.get_conversation_messages(conversation_id)
