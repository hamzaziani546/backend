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
    fbp: Optional[str],
    fbc: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> dict:
    if not settings.META_PIXEL_ID or not settings.META_ACCESS_TOKEN:
        return {"skipped": True, "reason": "META credentials not configured"}

    url = (
        f"https://graph.facebook.com/v25.0/{settings.META_PIXEL_ID}/events"
        f"?access_token={settings.META_ACCESS_TOKEN}"
    )

    content_ids = [item["product_id"] for item in items]
    contents = [
        {
            "id": item["product_id"],
            "quantity": item["unit_count"],
            "delivery_category": "home_delivery",
        }
        for item in items
    ]

    user_data: dict = {
        "ph": [hash_phone(phone_digits)],
        "external_id": [hash_external_id(order_number)],
    }
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent

    payload: dict = {
        "data": [
            {
                "event_name": "Purchase",
                "event_time": int(time.time()),
                "event_id": order_number,
                "event_source_url": event_source_url,
                "action_source": "website",
                "user_data": user_data,
                "custom_data": {
                    "value": total_sar,
                    "currency": "SAR",
                    "content_ids": content_ids,
                    "content_type": "product",
                    "contents": contents,
                },
            }
        ]
    }

    if settings.META_TEST_EVENT_CODE:
        payload["test_event_code"] = settings.META_TEST_EVENT_CODE

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return {"status_code": resp.status_code, "body": resp.text, "success": resp.is_success}
    except Exception as exc:
        logger.error("Meta CAPI error: %s", exc)
        return {"error": str(exc), "success": False}
