import time
import logging
from typing import Optional
import httpx
from app.config import settings
from app.services.hashing import hash_phone

logger = logging.getLogger(__name__)


async def send_purchase_event(
    order_number: str,
    phone_digits: str,
    total_sar: float,
    items: list[dict],
    event_source_url: str,
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> dict:
    if not settings.SNAP_PIXEL_ID or not settings.SNAP_ACCESS_TOKEN:
        return {"skipped": True, "reason": "Snapchat credentials not configured"}

    url = (
        f"https://tr.snapchat.com/v3/{settings.SNAP_PIXEL_ID}/events"
        f"?access_token={settings.SNAP_ACCESS_TOKEN}"
    )

    item_ids = [item["product_id"] for item in items]
    number_items = sum(item["unit_count"] for item in items)

    user_data: dict = {
        "ph": [hash_phone(phone_digits)],
    }
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent

    payload: dict = {
        "data": [
            {
                "event_name": "PURCHASE",
                "event_time": int(time.time()),
                "event_id": order_number,
                "action_source": "web",
                "event_source_url": event_source_url,
                "user_data": user_data,
                "custom_data": {
                    "value": str(total_sar),
                    "currency": "SAR",
                    "item_ids": item_ids,
                    "number_items": number_items,
                },
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return {"status_code": resp.status_code, "body": resp.text, "success": resp.is_success}
    except Exception as exc:
        logger.error("Snapchat CAPI error: %s", exc)
        return {"error": str(exc), "success": False}
