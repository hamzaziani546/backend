import json
import logging
from typing import Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


async def send_order_to_sheet(order_payload: dict) -> dict:
    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        return {"skipped": True, "reason": "GOOGLE_SHEETS_WEBHOOK_URL not configured"}

    payload = {**order_payload}
    if settings.GOOGLE_SHEETS_WEBHOOK_SECRET:
        payload["webhook_secret"] = settings.GOOGLE_SHEETS_WEBHOOK_SECRET

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    settings.GOOGLE_SHEETS_WEBHOOK_URL,
                    json=payload,
                )
                if resp.is_success:
                    return {
                        "status_code": resp.status_code,
                        "body": resp.text,
                        "success": True,
                    }
                logger.warning(
                    "Sheet webhook attempt %d failed: %d %s",
                    attempt + 1,
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.error("Sheet webhook attempt %d error: %s", attempt + 1, exc)

    return {"success": False, "error": "All sheet webhook attempts failed"}
