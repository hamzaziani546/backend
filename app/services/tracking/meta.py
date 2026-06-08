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
    total_mad: float,
    items: list[dict],
    event_source_url: str,
    fbp: Optional[str],
    fbc: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> dict:
    if not settings.META_PIXEL_ID or not settings.META_ACCESS_TOKEN:
        logger.info("Meta CAPI skipped — credentials not configured")
        return {"skipped": True, "reason": "META credentials not configured"}

    url = (
        f"https://graph.facebook.com/v21.0/{settings.META_PIXEL_ID}/events"
        f"?access_token={settings.META_ACCESS_TOKEN}"
    )

    contents = [
        {
            "id": item["product_id"],
            "quantity": item["unit_count"],
            "item_price": float(item["price_mad"]),
            "delivery_category": "home_delivery",
        }
        for item in items
    ]
    content_ids = [item["product_id"] for item in items]
    num_items = sum(item["unit_count"] for item in items)

    # All PII hashed server-side. phone_digits is already in E.164 digits form (9665xxxxxxxx).
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

    event_payload = {
        "event_name": "Purchase",
        "event_time": int(time.time()),
        "event_id": order_number,
        "event_source_url": event_source_url,
        "action_source": "website",
        "user_data": user_data,
        "custom_data": {
            "value": round(total_mad, 2),
            "currency": "MAD",
            "content_ids": content_ids,
            "content_type": "product",
            "contents": contents,
            "num_items": num_items,
            "order_id": order_number,
        },
    }

    payload: dict = {"data": [event_payload]}

    if settings.META_TEST_EVENT_CODE:
        payload["test_event_code"] = settings.META_TEST_EVENT_CODE

    logger.info(
        "Meta CAPI → sending Purchase | order=%s pixel=%s payload=%s",
        order_number,
        settings.META_PIXEL_ID,
        json.dumps(event_payload, ensure_ascii=False, default=str),
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            result = {
                "status_code": resp.status_code,
                "body": resp.text,
                "success": resp.is_success,
            }
            if resp.is_success:
                logger.info(
                    "Meta CAPI ✓ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:500],
                )
            else:
                logger.error(
                    "Meta CAPI ✗ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:1000],
                )
            return result
    except Exception as exc:
        logger.error("Meta CAPI exception | order=%s error=%s", order_number, exc)
        return {"error": str(exc), "success": False}
