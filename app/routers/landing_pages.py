from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LandingPage
from app.services.landing_pages import serialize_landing_page

router = APIRouter(prefix="/landing-pages", tags=["landing-pages"])


@router.get("/{slug}")
def get_landing_page(slug: str, db: Session = Depends(get_db)):
    lp = (
        db.query(LandingPage)
        .filter(LandingPage.slug == slug.strip().lower(), LandingPage.is_active.is_(True))
        .first()
    )
    if not lp:
        raise HTTPException(status_code=404, detail="صفحة الهبوط غير موجودة")
    return serialize_landing_page(lp)
