import logging
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Click
from app.services.geoip import check_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/track", tags=["tracking"])


class ClickIn(BaseModel):
    visitor_id: str
    landing_page: Optional[str] = None
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    ttp: Optional[str] = None
    ttclid: Optional[str] = None
    sc_click_id: Optional[str] = None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


@router.post("/click", status_code=202)
def record_click(
    payload: ClickIn,
    request: Request,
    db: Session = Depends(get_db),
):
    """Record a landing-page visit with geo/VPN signals for admin analytics."""
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")

    geo = check_ip(client_ip)

    click = Click(
        visitor_id=payload.visitor_id[:64],
        landing_page=payload.landing_page,
        referrer=payload.referrer,
        country_code=geo.country_code,
        is_vpn=bool(geo.is_vpn),
        is_proxy=bool(geo.is_proxy),
        is_valid=bool(geo.allowed),
        block_reason=None if geo.allowed else geo.reason[:255],
        client_ip=client_ip,
        user_agent=user_agent,
        utm_source=payload.utm_source,
        utm_medium=payload.utm_medium,
        utm_campaign=payload.utm_campaign,
        utm_content=payload.utm_content,
        utm_term=payload.utm_term,
        fbp=payload.fbp,
        fbc=payload.fbc,
        ttp=payload.ttp,
        ttclid=payload.ttclid,
        sc_click_id=payload.sc_click_id,
    )
    db.add(click)
    db.commit()

    return {"recorded": True, "valid": click.is_valid}
