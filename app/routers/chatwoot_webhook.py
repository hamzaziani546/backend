import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Request

from app.database import SessionLocal
from app.services.whatsapp_replies import IncomingMessage, process_incoming_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/chatwoot", tags=["webhooks"])

_PROCESSED_IDS: set[str] = set()
_MAX_CACHE = 5000


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _extract_phone(payload: dict[str, Any]) -> str:
    sender = payload.get("sender") or {}
    phone = sender.get("phone_number") or sender.get("identifier") or ""
    if phone:
        return _digits_only(phone)

    conversation = payload.get("conversation") or {}
    contact_inbox = conversation.get("contact_inbox") or {}
    source_id = contact_inbox.get("source_id") or ""
    if source_id:
        return _digits_only(source_id)

    meta = conversation.get("meta") or {}
    meta_sender = meta.get("sender") or {}
    return _digits_only(
        meta_sender.get("phone_number") or meta_sender.get("identifier") or ""
    )


def _is_incoming(payload: dict[str, Any]) -> bool:
    message_type = payload.get("message_type")
    if message_type in (0, "incoming", "Incoming"):
        return True
    sender_type = (payload.get("sender") or {}).get("type")
    return sender_type == "contact"


def _message_from_chatwoot(payload: dict[str, Any]) -> Optional[IncomingMessage]:
    if payload.get("event") != "message_created":
        return None
    if not _is_incoming(payload):
        return None

    content = (payload.get("content") or "").strip()
    if not content:
        return None

    phone = _extract_phone(payload)
    message_id = str(payload.get("id") or payload.get("source_id") or "")
    if not phone or not message_id:
        return None

    from app.services.whatsapp_replies import parse_reply_action, ReplyAction

    action = parse_reply_action(text=content, button_title=content)
    if action == ReplyAction.UNKNOWN:
        return None

    return IncomingMessage(
        from_phone=phone,
        message_id=f"cw-{message_id}",
        action=action,
        raw_text=content,
    )


async def _handle_chatwoot_payload(payload: dict[str, Any]) -> None:
    message = _message_from_chatwoot(payload)
    if not message:
        return

    if message.message_id in _PROCESSED_IDS:
        return

    db = SessionLocal()
    try:
        result = await process_incoming_message(db, message)
        if result.get("handled"):
            _PROCESSED_IDS.add(message.message_id)
            if len(_PROCESSED_IDS) > _MAX_CACHE:
                _PROCESSED_IDS.clear()
    except Exception:
        logger.exception("Chatwoot reply handler failed message_id=%s", message.message_id)
    finally:
        db.close()


@router.post("")
async def receive_chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception:
        return {"status": "invalid"}

    if not isinstance(payload, dict):
        return {"status": "ignored"}

    logger.info(
        "Chatwoot webhook event=%s type=%s",
        payload.get("event"),
        payload.get("message_type"),
    )
    background_tasks.add_task(_handle_chatwoot_payload, payload)
    return {"status": "ok"}
