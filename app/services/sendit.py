import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_module_token: Optional[str] = None
_stock_products_cache: Optional[list[dict[str, Any]]] = None

# Arabic checkout cities → Sendit district search (French)
CITY_TO_SENDIT: dict[str, str] = {
    "الدار البيضاء": "Casablanca",
    "الرباط": "Rabat",
    "مراكش": "Marrakech",
    "طنجة": "Tanger",
    "فاس": "Fes",
    "أكادير": "Agadir",
    "مكناس": "Meknes",
    "وجدة": "Oujda",
    "القنيطرة": "Kenitra",
    "آسفي": "Safi",
    "تطوان": "Tetouan",
    "الجديدة": "El Jadida",
    "الناظور": "Nador",
    "بني ملال": "Beni Mellal",
    "خريبكة": "Khouribga",
    "تازة": "Taza",
    "العيون": "Laayoune",
    "سطات": "Settat",
}


def map_city_for_sendit(city: str) -> Optional[str]:
    """Map Moroccan Arabic city label to Sendit district search term."""
    raw = (city or "").strip()
    if not raw:
        return None
    if raw in CITY_TO_SENDIT:
        return CITY_TO_SENDIT[raw]
    if raw == "مدينة أخرى":
        return None
    return raw


def _pick_district_id(districts: list[dict[str, Any]], search: str) -> Optional[int]:
    if not districts:
        return None
    needle = search.strip().casefold()
    for row in districts:
        ville = (row.get("ville") or "").strip().casefold()
        name = (row.get("name") or "").strip().casefold()
        if ville == needle or name == needle:
            return int(row["id"])
    for row in districts:
        ville = (row.get("ville") or "").strip().casefold()
        name = (row.get("name") or "").strip().casefold()
        if needle in ville or needle in name:
            return int(row["id"])
    return int(districts[0]["id"])


class SenditClient:
    def __init__(self) -> None:
        self.base = settings.SENDIT_API_BASE.rstrip("/")

    async def ensure_authenticated(self) -> None:
        global _module_token
        if _module_token:
            return
        await self.login()

    async def login(self) -> None:
        global _module_token
        if not settings.SENDIT_PUBLIC_KEY or not settings.SENDIT_PRIVATE_KEY:
            raise RuntimeError("Sendit API keys not configured")

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self.base}/login",
                json={
                    "public_key": settings.SENDIT_PUBLIC_KEY,
                    "secret_key": settings.SENDIT_PRIVATE_KEY,
                },
            )
            data = resp.json()
            if resp.is_success and data.get("success") and data.get("data", {}).get("token"):
                _module_token = data["data"]["token"]
                logger.info("Sendit authentication successful")
                return
            logger.error(
                "Sendit auth failed status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
            raise RuntimeError("Sendit authentication failed")

    def _auth_headers(self) -> dict[str, str]:
        if not _module_token:
            raise RuntimeError("Sendit token missing")
        return {
            "Authorization": f"Bearer {_module_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_district_id(self, city_name: str) -> Optional[int]:
        await self.ensure_authenticated()
        districts: list[dict[str, Any]] = []
        for page in range(1, 4):
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{self.base}/districts",
                    headers=self._auth_headers(),
                    params={"querystring": city_name, "page": page},
                )
            data = resp.json()
            if not resp.is_success or not data.get("success"):
                logger.warning(
                    "Sendit districts lookup failed city=%s page=%s status=%s",
                    city_name,
                    page,
                    resp.status_code,
                )
                break
            page_rows = data.get("data") or []
            if not page_rows:
                break
            districts.extend(page_rows)
            last_page = data.get("last_page") or 1
            if page >= last_page:
                break

        district_id = _pick_district_id(districts, city_name)
        if district_id:
            logger.info("Sendit district city=%s -> id=%s", city_name, district_id)
        else:
            logger.warning("Sendit district not found for city=%s", city_name)
        return district_id

    async def list_stock_products(self) -> list[dict[str, Any]]:
        """Cached list of products in Sendit warehouse stock."""
        global _stock_products_cache
        if _stock_products_cache is not None:
            return _stock_products_cache

        await self.ensure_authenticated()
        products: list[dict[str, Any]] = []
        for page in range(1, 6):
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(
                    f"{self.base}/products",
                    headers=self._auth_headers(),
                    params={"page": page},
                )
            data = resp.json()
            if not resp.is_success or not data.get("success"):
                break
            page_rows = data.get("data") or []
            if not page_rows:
                break
            products.extend(page_rows)
            last_page = data.get("last_page") or 1
            if page >= last_page:
                break

        _stock_products_cache = products
        logger.info("Sendit stock products loaded count=%s", len(products))
        return products

    async def create_delivery(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self.ensure_authenticated()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base}/deliveries",
                headers=self._auth_headers(),
                json=payload,
            )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        success = resp.is_success and bool(data.get("success"))
        if data.get("error"):
            success = False

        return {
            "success": success,
            "status_code": resp.status_code,
            "data": data.get("data"),
            "body": data,
        }
