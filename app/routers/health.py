from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def root():
    return {"status": "ok", "service": "Lamis Beauty API"}


@router.get("/health")
def health_check():
    return {
        "status": "ok",
        "geo_order_blocking": False,
        "build": "2026-06-05-no-geo-block",
    }
