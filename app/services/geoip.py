import logging
from typing import Optional

import geoip2.webservice
import geoip2.database
import geoip2.errors

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_COUNTRY_CODES = {"SA"}


def _get_client() -> Optional[geoip2.webservice.Client]:
    if not settings.MAXMIND_ACCOUNT_ID or not settings.MAXMIND_LICENSE_KEY:
        return None
    return geoip2.webservice.Client(
        int(settings.MAXMIND_ACCOUNT_ID),
        settings.MAXMIND_LICENSE_KEY,
        host="geolite.info",
    )


def _get_reader() -> Optional[geoip2.database.Reader]:
    if not settings.MAXMIND_DB_PATH:
        return None
    try:
        return geoip2.database.Reader(settings.MAXMIND_DB_PATH)
    except Exception as exc:
        logger.error("Failed to open GeoIP database: %s", exc)
        return None


class GeoCheckResult:
    def __init__(
        self,
        allowed: bool,
        country_code: Optional[str] = None,
        is_vpn: bool = False,
        is_proxy: bool = False,
        reason: str = "",
    ):
        self.allowed = allowed
        self.country_code = country_code
        self.is_vpn = is_vpn
        self.is_proxy = is_proxy
        self.reason = reason


def check_ip(ip: str) -> GeoCheckResult:
    """Check if IP is from KSA and not using VPN/proxy."""
    if not settings.GEOIP_ENFORCE:
        return GeoCheckResult(allowed=True, reason="enforcement disabled")

    if ip in ("127.0.0.1", "::1", "unknown"):
        return GeoCheckResult(allowed=True, reason="localhost")

    # Try local database first, fall back to web service
    reader = _get_reader()
    if reader:
        try:
            response = reader.insights(ip) if hasattr(reader, "insights") else None
            if response is None:
                response = reader.city(ip)
            country_code = response.country.iso_code
            is_vpn = False
            is_proxy = False
            if hasattr(response, "traits"):
                is_vpn = getattr(response.traits, "is_anonymous_vpn", False) or False
                is_proxy = getattr(response.traits, "is_anonymous_proxy", False) or False
            reader.close()
        except geoip2.errors.AddressNotFoundError:
            reader.close()
            return GeoCheckResult(allowed=False, reason="IP not found in database")
        except Exception as exc:
            logger.error("GeoIP DB lookup error: %s", exc)
            reader.close()
            return GeoCheckResult(allowed=True, reason="db lookup error, allowing")
    else:
        client = _get_client()
        if not client:
            logger.warning("No MaxMind credentials configured; skipping geo check")
            return GeoCheckResult(allowed=True, reason="no credentials")

        try:
            response = client.insights(ip)
            country_code = response.country.iso_code
            is_vpn = getattr(response.traits, "is_anonymous_vpn", False) or False
            is_proxy = getattr(response.traits, "is_anonymous_proxy", False) or False
        except geoip2.errors.AddressNotFoundError:
            return GeoCheckResult(allowed=False, reason="IP not found")
        except Exception as exc:
            logger.error("MaxMind web service error: %s", exc)
            return GeoCheckResult(allowed=True, reason="service error, allowing")

    if is_vpn or is_proxy:
        return GeoCheckResult(
            allowed=False,
            country_code=country_code,
            is_vpn=is_vpn,
            is_proxy=is_proxy,
            reason="VPN or proxy detected",
        )

    if country_code not in ALLOWED_COUNTRY_CODES:
        return GeoCheckResult(
            allowed=False,
            country_code=country_code,
            reason=f"country {country_code} not allowed",
        )

    return GeoCheckResult(
        allowed=True,
        country_code=country_code,
        reason="KSA, clean IP",
    )
