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
    sc_click_id: Optional[str],
    sc_cookie1: Optional[str],
    client_ip: Optional[str],
    user_agent: Optional[str],
) -> dict:
    if not settings.SNAP_PIXEL_ID or not settings.SNAP_ACCESS_TOKEN:
        logger.info("Snap CAPI skipped — credentials not configured")
        return {"skipped": True, "reason": "Snapchat credentials not configured"}

    url = (
        f"https://tr.snapchat.com/v3/{settings.SNAP_PIXEL_ID}/events"
        f"?access_token={settings.SNAP_ACCESS_TOKEN}"
    )

    item_ids = [item["product_id"] for item in items]
    number_items = sum(item["unit_count"] for item in items)

    # All PII hashed server-side.
    # phone_digits format: 9665xxxxxxxx — normalize per Snap docs:
    # include country code, no leading zeros/spaces/non-numeric chars.
    user_data: dict = {
        "ph": [hash_phone(phone_digits)],
        "external_id": [hash_external_id(order_number)],
    }
    if client_ip:
        user_data["client_ip_address"] = client_ip
    if user_agent:
        user_data["client_user_agent"] = user_agent
    if sc_click_id:
        user_data["sc_click_id"] = sc_click_id
    if sc_cookie1:
        # _scid cookie value — improves Snap match quality as sc_cookie1
        user_data["sc_cookie1"] = sc_cookie1

    event_payload = {
        "event_name": "PURCHASE",
        "event_time": int(time.time() * 1000),  # Snap prefers milliseconds
        "event_id": order_number,               # matches client_dedup_id on pixel
        "action_source": "web",
        "event_source_url": event_source_url,
        "user_data": user_data,
        "custom_data": {
            "value": round(total_sar, 2),       # float, not str
            "currency": "MAD",
            "item_ids": item_ids,
            "number_items": number_items,
            "order_id": order_number,           # enables 30-day PURCHASE dedup window
        },
    }

    payload: dict = {"data": [event_payload]}

    logger.info(
        "Snap CAPI → sending PURCHASE | order=%s pixel=%s payload=%s",
        order_number,
        settings.SNAP_PIXEL_ID,
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
                    "Snap CAPI ✓ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:500],
                )
            else:
                logger.error(
                    "Snap CAPI ✗ | order=%s status=%s body=%s",
                    order_number,
                    resp.status_code,
                    resp.text[:1000],
                )
            return result
    except Exception as exc:
        logger.error("Snap CAPI exception | order=%s error=%s", order_number, exc)
        return {"error": str(exc), "success": False}
