import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.database import engine, _is_sqlite
from app.routers import health, orders, admin, track
from app.schema_admin import ensure_admin_dashboard_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="Lamis Beauty API",
    description="Backend API for لاميس للجمال ecommerce store",
    version="1.0.0",
    docs_url="/docs" if settings.APP_ENV != "production" else None,
    redoc_url=None,
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["*"])
# Accept exact origins from CORS_ORIGINS plus a regex covering any
# lamisbeauty.site subdomain and localhost. This avoids 400s on
# preflight whenever the site is opened from www., a staging host,
# or a developer machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"^https?://(?:[a-z0-9-]+\.)?lamisbeauty\.site$|^http://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

if _is_sqlite:
    import importlib

    from app.database import Base
    importlib.import_module("app.models")  # ensure models are registered
    Base.metadata.create_all(bind=engine)


@app.on_event("startup")
def _ensure_admin_dashboard_schema() -> None:
    ensure_admin_dashboard_schema()

app.include_router(health.router)
app.include_router(orders.router)
app.include_router(track.router)
app.include_router(admin.router)
