import logging
import time
from typing import Optional

import httpx
import geoip2.webservice
import geoip2.database
import geoip2.errors

from app.config import settings

logger = logging.getLogger(__name__)

_PROXYCHECK_CACHE: dict[str, tuple[float, dict]] = {}
_PROXYCHECK_CACHE_TTL = 3600


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


def _check_proxycheck(ip: str) -> Optional[dict]:
    """Query proxycheck.io for VPN/proxy/Tor info. Returns dict or None on error."""
    if not settings.PROXYCHECK_API_KEY:
        return None

    cached = _PROXYCHECK_CACHE.get(ip)
    if cached and (time.time() - cached[0]) < _PROXYCHECK_CACHE_TTL:
        return cached[1]

    try:
        url = f"https://proxycheck.io/v2/{ip}"
        params = {
            "key": settings.PROXYCHECK_API_KEY,
            "vpn": "1",
            "risk": "1",
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "ok":
            logger.warning("proxycheck.io returned non-ok status: %s", data.get("status"))
            return None

        ip_data = data.get(ip, {})
        result = {
            "is_proxy": ip_data.get("proxy") == "yes",
            "type": ip_data.get("type", ""),
            "risk": int(ip_data.get("risk", 0) or 0),
            "country_code": ip_data.get("isocode"),
        }
        _PROXYCHECK_CACHE[ip] = (time.time(), result)
        return result
    except Exception as exc:
        logger.error("proxycheck.io error: %s", exc)
        return None


def check_ip(ip: str) -> GeoCheckResult:
    """Look up IP geo/VPN signals for analytics. Never blocks orders."""
    country_code: Optional[str] = None
    is_vpn = False
    is_proxy = False
    reason = "lookup ok"

    if ip in ("127.0.0.1", "::1", "unknown"):
        return GeoCheckResult(
            allowed=True,
            reason="localhost or unknown IP",
        )

    reader = _get_reader()
    if reader:
        try:
            response = reader.insights(ip) if hasattr(reader, "insights") else None
            if response is None:
                response = reader.city(ip)
            country_code = response.country.iso_code
            if hasattr(response, "traits"):
                is_vpn = getattr(response.traits, "is_anonymous_vpn", False) or False
                is_proxy = getattr(response.traits, "is_anonymous_proxy", False) or False
            reader.close()
        except geoip2.errors.AddressNotFoundError:
            reader.close()
            reason = "IP not found in database"
        except Exception as exc:
            logger.error("GeoIP DB lookup error: %s", exc)
            reader.close()
            reason = "db lookup error"
    else:
        client = _get_client()
        if client:
            try:
                try:
                    response = client.insights(ip)
                except Exception:
                    response = client.city(ip)
                country_code = response.country.iso_code
                is_vpn = getattr(response.traits, "is_anonymous_vpn", False) or False
                is_proxy = getattr(response.traits, "is_anonymous_proxy", False) or False
            except geoip2.errors.AddressNotFoundError:
                reason = "IP not found"
            except Exception as exc:
                logger.error("MaxMind web service error: %s", exc)
                reason = "service error"
        else:
            reason = "geo lookup unavailable"

    if is_vpn or is_proxy:
        reason = "VPN or proxy detected (MaxMind)"

    if settings.PROXYCHECK_API_KEY:
        pc = _check_proxycheck(ip)
        if pc:
            if not country_code and pc.get("country_code"):
                country_code = pc["country_code"]
            if pc["is_proxy"]:
                is_proxy = True
            if pc["type"].upper() == "VPN":
                is_vpn = True
            if pc["is_proxy"] or pc["risk"] >= settings.PROXYCHECK_RISK_THRESHOLD:
                reason = f"proxycheck.io: type={pc['type']} risk={pc['risk']}"

    return GeoCheckResult(
        allowed=True,
        country_code=country_code,
        is_vpn=is_vpn,
        is_proxy=is_proxy,
        reason=reason,
    )
