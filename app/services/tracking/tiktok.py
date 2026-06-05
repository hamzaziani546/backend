import json
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
        logger.info("TikTok Events API skipped — credentials not configured")
        return {"skipped": True, "reason": "TikTok credentials not configured"}

    url = "https://business-api.tiktok.com/open_api/v1.3/event/track/"

    contents = [
        {
            "content_id": item["product_id"],
            "content_type": "product",
            "quantity": item["unit_count"],
            "price": round(float(item["price_sar"]), 2),
        }
        for item in items
    ]

    # All PII hashed server-side with SHA-256.
    # phone_digits format: 9665xxxxxxxx — TikTok requires E.164 digits, no leading zeros.
    user_data: dict = {
        "phone": hash_phone(phone_digits),
        "external_id": hash_external_id(order_number),
    }
    if ttp:
        user_data["ttp"] = ttp        # raw _ttp cookie value — do NOT hash
    if ttclid:
        user_data["ttclid"] = ttclid  # raw click id — do NOT hash
    if client_ip:
        user_data["ip"] = client_ip
    if user_agent:
        user_data["user_agent"] = user_agent

    event_payload = {
        "event": "CompletePayment",
        "event_time": int(time.time()),
        "event_id": order_number,      # matches event_id on browser pixel for dedup
        "user": user_data,
        "page": {
            "url": event_source_url,
        },
        "properties": {
            "contents": contents,
            "content_type": "product",
            "value": round(total_sar, 2),
            "currency": "MAD",
            "order_id": order_number,
        },
    }

    payload: dict = {
        "event_source": "web",
        "event_source_id": settings.TIKTOK_PIXEL_ID,
        "data": [event_payload],
    }

    if settings.TIKTOK_TEST_EVENT_CODE:
        payload["test_event_code"] = settings.TIKTOK_TEST_EVENT_CODE

    headers = {
        "Access-Token": settings.TIKTOK_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    logger.info(
        "TikTok Events API → sending CompletePayment | order=%s pixel=%s payload=%s",
        order_number,
        settings.TIKTOK_PIXEL_ID,
        json.dumps(event_payload, ensure_ascii=False, default=str),
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            result = {
                "status_code": resp.status_code,
                "body": resp.text,
                "success": resp.is_success,
            }
            if resp.is_success:
                logger.info(
                    "TikTok Events API ✓ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:500],
                )
            else:
                logger.error(
                    "TikTok Events API ✗ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:1000],
                )
            return result
    except Exception as exc:
        logger.error("TikTok Events API exception | order=%s error=%s", order_number, exc)
        return {"error": str(exc), "success": False}
