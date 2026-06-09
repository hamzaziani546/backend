from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "production"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    PUBLIC_SITE_URL: str = "https://lamisbeauty.site"
    PUBLIC_API_URL: str = "https://api.lamisbeauty.site"

    DATABASE_URL: str = (
        "postgresql+psycopg://lamisbeauty:lamisbeauty@lamisbeauty_database:5432/lamisbeauty"
    )

    GOOGLE_SHEETS_WEBHOOK_URL: Optional[str] = None
    GOOGLE_SHEETS_WEBHOOK_SECRET: Optional[str] = None

    META_PIXEL_ID: Optional[str] = None
    META_ACCESS_TOKEN: Optional[str] = None
    META_TEST_EVENT_CODE: Optional[str] = None

    TIKTOK_PIXEL_ID: Optional[str] = None
    TIKTOK_ACCESS_TOKEN: Optional[str] = None
    TIKTOK_TEST_EVENT_CODE: Optional[str] = None

    SNAP_PIXEL_ID: Optional[str] = None
    SNAP_ACCESS_TOKEN: Optional[str] = None

    MAXMIND_ACCOUNT_ID: Optional[str] = None
    MAXMIND_LICENSE_KEY: Optional[str] = None
    MAXMIND_DB_PATH: Optional[str] = None
    PROXYCHECK_API_KEY: Optional[str] = None
    PROXYCHECK_RISK_THRESHOLD: int = 66
    PROXYCHECK_BLOCK_ON_ERROR: bool = False

    CORS_ORIGINS: str = "https://lamisbeauty.site"

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-me-please"
    ADMIN_JWT_SECRET: str = "change-me-too-very-long-random-string"
    ADMIN_TOKEN_EXPIRE_HOURS: int = 24

    WHATSAPP_WABA_ID: Optional[str] = None
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = None
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_ORDER_TEMPLATE: str = "new_order"
    WHATSAPP_ORDER_TEMPLATE_LANG: str = "en"
    WHATSAPP_AUTO_CONFIRM: bool = True
    WHATSAPP_WEBHOOK_VERIFY_TOKEN: Optional[str] = None
    WHATSAPP_APP_SECRET: Optional[str] = None

    CHATWOOT_BASE_URL: Optional[str] = "https://chat.lamisbeauty.site"
    CHATWOOT_API_TOKEN: Optional[str] = None
    CHATWOOT_ACCOUNT_ID: str = "1"
    CHATWOOT_INBOX_ID: str = "1"

    SENDIT_PUBLIC_KEY: Optional[str] = None
    SENDIT_PRIVATE_KEY: Optional[str] = None
    SENDIT_API_BASE: str = "https://app.sendit.ma/api/v1"
    SENDIT_AUTO_DISPATCH: bool = True
    SENDIT_PICKUP_DISTRICT: str = "Casablanca"
    SENDIT_PICKUP_DISTRICT_ID: Optional[int] = None
    # Sendit warehouse stock (TO_PREPARE) vs ramassage (PENDING)
    SENDIT_PRODUCTS_FROM_STOCK: bool = True
    # JSON map product_id or SKU → Sendit stock reference, e.g. {"collagen-glow-gummies":"collagen1"}
    SENDIT_REFERENCE_MAP: Optional[str] = None
    SENDIT_PACKAGING_ID: int = 12
    SENDIT_ALLOW_OPEN: int = 1
    SENDIT_ALLOW_TRY: int = 1

    UPLOAD_DIR: str = "uploads"
    UPLOAD_MAX_MB: int = 5

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

settings = Settings()
