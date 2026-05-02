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
    GEOIP_ENFORCE: bool = True
    GEOIP_WHITELISTED_PHONES: str = "0527837429"

    CORS_ORIGINS: str = "https://lamisbeauty.site"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def whitelisted_phones(self) -> set[str]:
        return {p.strip() for p in self.GEOIP_WHITELISTED_PHONES.split(",") if p.strip()}


settings = Settings()
