import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response

from app.config import settings
from app.database import SessionLocal
from app.services.whatsapp_replies import extract_incoming_messages, process_incoming_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks/whatsapp", tags=["webhooks"])


def _verify_signature(body: bytes, signature_header: str | None = None) -> bool:
    secret = (settings.WHATSAPP_APP_SECRET or "").strip()
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


async def _handle_webhook_payload(payload: dict) -> None:
    messages = extract_incoming_messages(payload)
    if not messages:
        return

    db = SessionLocal()
    try:
        for message in messages:
            try:
                await process_incoming_message(db, message)
            except Exception:
                logger.exception(
                    "WhatsApp reply handler failed message_id=%s",
                    message.message_id,
                )
    finally:
        db.close()


@router.get("")
def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
):
    token = (settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    if hub_mode == "subscribe" and token and hub_verify_token == token:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not _verify_signature(body, signature):
        logger.warning("WhatsApp webhook rejected — invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    msg_count = sum(
        len(change.get("value", {}).get("messages", []))
        for entry in payload.get("entry", [])
        for change in entry.get("changes", [])
    )
    logger.info("WhatsApp webhook received messages=%s", msg_count)
    background_tasks.add_task(_handle_webhook_payload, payload)
    return {"status": "ok"}
