import time
import logging
from typing import Optional
import httpx
from app.config import settings
from app.services.hashing import hash_phone, hash_external_id

logger = logging.getLogger(__name__)


async def send_purchase_event(
    order_number: str,
    phone_digits: str,
    total_sar: float,
    items: list[dict],
    event_source_url: str,
    ttp: Optional[str],
    ttclid: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> dict:
    if not settings.TIKTOK_PIXEL_ID or not settings.TIKTOK_ACCESS_TOKEN:
        return {"skipped": True, "reason": "TikTok credentials not configured"}

    url = "https://business-api.tiktok.com/open_api/v1.3/event/track/"

    contents = [
        {
            "content_id": item["product_id"],
            "quantity": item["unit_count"],
            "price": float(item["price_sar"]),
        }
        for item in items
    ]

    user_data: dict = {
        "phone": hash_phone(phone_digits),
        "external_id": hash_external_id(order_number),
    }
    if ttp:
        user_data["ttp"] = ttp
    if ttclid:
        user_data["ttclid"] = ttclid
    if client_ip:
        user_data["ip"] = client_ip
    if user_agent:
        user_data["user_agent"] = user_agent

    payload: dict = {
        "event_source": "web",
        "event_source_id": settings.TIKTOK_PIXEL_ID,
        "data": [
            {
                "event": "CompletePayment",
                "event_time": int(time.time()),
                "event_id": order_number,
                "user": user_data,
                "page": {"url": event_source_url},
                "properties": {
                    "contents": contents,
                    "content_type": "product",
                    "value": total_sar,
                    "currency": "SAR",
                },
            }
        ],
    }

    if settings.TIKTOK_TEST_EVENT_CODE:
        payload["test_event_code"] = settings.TIKTOK_TEST_EVENT_CODE

    headers = {
        "Access-Token": settings.TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            return {"status_code": resp.status_code, "body": resp.text, "success": resp.is_success}
    except Exception as exc:
        logger.error("TikTok Events API error: %s", exc)
        return {"error": str(exc), "success": False}
