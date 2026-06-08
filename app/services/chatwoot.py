import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {"api_access_token": settings.CHATWOOT_API_TOKEN or ""}


def _base() -> str:
    base = (settings.CHATWOOT_BASE_URL or "").rstrip("/")
    account = settings.CHATWOOT_ACCOUNT_ID or "1"
    return f"{base}/api/v1/accounts/{account}"


def is_configured() -> bool:
    return bool(
        settings.CHATWOOT_API_TOKEN
        and settings.CHATWOOT_BASE_URL
        and settings.CHATWOOT_INBOX_ID
    )


async def list_conversations(page: int = 1, status: str = "all") -> dict:
    if not is_configured():
        return {"items": [], "meta": {}, "configured": False}

    params = {
        "inbox_id": settings.CHATWOOT_INBOX_ID,
        "status": status,
        "page": page,
    }
    url = f"{_base()}/conversations"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers(), params=params)
            data = response.json()
            if not response.is_success:
                logger.error("Chatwoot list failed: %s %s", response.status_code, data)
                return {
                    "items": [],
                    "meta": {},
                    "configured": True,
                    "error": data,
                }
            payload = data.get("data", {}).get("payload", [])
            meta = data.get("data", {}).get("meta", {})
            items = [_serialize_conversation(item) for item in payload]
            return {"items": items, "meta": meta, "configured": True}
    except Exception as exc:
        logger.exception("Chatwoot list error")
        return {"items": [], "meta": {}, "configured": True, "error": str(exc)}


async def get_conversation_messages(conversation_id: int) -> dict:
    if not is_configured():
        return {"items": [], "configured": False}

    url = f"{_base()}/conversations/{conversation_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_headers())
            data = response.json()
            if not response.is_success:
                return {"items": [], "configured": True, "error": data}
            payload = data.get("payload", [])
            items = [
                {
                    "id": msg.get("id"),
                    "content": msg.get("content") or "",
                    "message_type": msg.get("message_type"),
                    "created_at": msg.get("created_at"),
                    "sender_type": (msg.get("sender") or {}).get("type"),
                    "sender_name": (msg.get("sender") or {}).get("name"),
                }
                for msg in payload
            ]
            return {"items": items, "configured": True}
    except Exception as exc:
        logger.exception("Chatwoot messages error id=%s", conversation_id)
        return {"items": [], "configured": True, "error": str(exc)}


def _serialize_conversation(item: dict) -> dict:
    meta = item.get("meta") or {}
    sender = meta.get("sender") or {}
    last_message = meta.get("last_message") or item.get("last_non_activity_message") or {}
    return {
        "id": item.get("id"),
        "inbox_id": item.get("inbox_id"),
        "status": item.get("status"),
        "contact_name": sender.get("name") or sender.get("identifier") or "Unknown",
        "contact_phone": sender.get("phone_number") or sender.get("identifier"),
        "last_message": last_message.get("content") or "",
        "last_message_at": last_message.get("created_at") or item.get("last_activity_at"),
        "unread_count": item.get("unread_count") or 0,
        "messages_count": item.get("messages_count") or 0,
    }
