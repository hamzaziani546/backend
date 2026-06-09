import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models import Order
from app.services import orders as order_service
from app.services.sendit_dispatch import dispatch_order_to_sendit
from app.services.whatsapp import send_text_message

logger = logging.getLogger(__name__)

REPLY_CONFIRM = (
    "تم تأكيد طلبكم بنجاح، الطلب الآن في انتظار المعالجة من طرف شركة التوصيل. "
    "سيتم التوصيل في أقرب وقت، عادةً من يوم إلى يومين. "
    "سيتم التواصل معكم قريباً لتحديد موعد التسليم."
)
REPLY_EDIT = (
    "من فضلك، أدخل المعلومات الجديدة التي ترغب في تعديلها وسنقوم بتحديثها فوراً"
)
REPLY_CANCEL = "لقد تم استقبال طلب الإلغاء، نؤكد بأنه سيُعالج حالاً."
REPLY_NO_ORDER = (
    "لم نجد طلباً حديثاً مرتبطاً بهذا الرقم. "
    "إذا كنتم قد طلبتم للتو، يرجى الانتظار قليلاً ثم المحاولة مجدداً."
)
REPLY_ALREADY_CONFIRMED = "طلبكم مؤكد مسبقاً ✅ سيتم التواصل معكم قبل الشحن."
REPLY_ALREADY_CANCELLED = "طلبكم ملغى مسبقاً. لأي استفسار نحن هنا لمساعدتكم."


class ReplyAction(str, Enum):
    CONFIRM = "confirm"
    EDIT = "edit"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


@dataclass
class IncomingMessage:
    from_phone: str
    message_id: str
    action: ReplyAction
    raw_text: str
    button_id: Optional[str] = None


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", (value or "").strip().casefold())
    text = re.sub(r"\s+", " ", text)
    return text


def _phones_match(a: str, b: str) -> bool:
    da, db = _digits_only(a), _digits_only(b)
    if not da or not db:
        return False
    if da == db:
        return True
    if len(da) >= 9 and len(db) >= 9 and da[-9:] == db[-9:]:
        return True
    return False


def parse_reply_action(
    *,
    button_id: Optional[str] = None,
    button_title: Optional[str] = None,
    text: Optional[str] = None,
) -> ReplyAction:
    candidates = [_normalize_text(v) for v in (button_id, button_title, text) if v]
    blob = " ".join(candidates)

    confirm_keys = (
        "confirm",
        "confirm_order",
        "تأكيد",
        "تأكيد الطلب",
        "نعم",
        "ok",
        "yes",
    )
    edit_keys = (
        "edit",
        "edit_info",
        "edit_order",
        "تعديل",
        "تعديل المعلومات",
        "تعديل الطلب",
    )
    cancel_keys = (
        "cancel",
        "cancel_order",
        "إلغاء",
        "الغاء",
        "إلغاء الطلب",
        "الغاء الطلب",
        "لا",
        "no",
    )

    for key in confirm_keys:
        if _normalize_text(key) in blob or blob == _normalize_text(key):
            return ReplyAction.CONFIRM
    for key in edit_keys:
        if _normalize_text(key) in blob or blob == _normalize_text(key):
            return ReplyAction.EDIT
    for key in cancel_keys:
        if _normalize_text(key) in blob or blob == _normalize_text(key):
            return ReplyAction.CANCEL
    return ReplyAction.UNKNOWN


def extract_incoming_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    messages: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                from_phone = _digits_only(msg.get("from", ""))
                message_id = str(msg.get("id", ""))
                if not from_phone or not message_id:
                    continue

                msg_type = msg.get("type")
                button_id = None
                button_title = None
                text = None

                if msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        reply = interactive.get("button_reply", {})
                        button_id = reply.get("id")
                        button_title = reply.get("title")
                    elif interactive.get("type") == "list_reply":
                        reply = interactive.get("list_reply", {})
                        button_id = reply.get("id")
                        button_title = reply.get("title")
                elif msg_type == "button":
                    button = msg.get("button", {})
                    button_id = button.get("payload")
                    button_title = button.get("text")
                elif msg_type == "text":
                    text = (msg.get("text") or {}).get("body")

                action = parse_reply_action(
                    button_id=button_id,
                    button_title=button_title,
                    text=text,
                )
                raw = button_title or text or button_id or ""
                messages.append(
                    IncomingMessage(
                        from_phone=from_phone,
                        message_id=message_id,
                        action=action,
                        raw_text=raw,
                        button_id=button_id,
                    )
                )
    return messages


def find_pending_order(db: Session, phone: str) -> Optional[Order]:
    awaiting = ("confirmation_sent", "sent_to_sheet", "new", "contacted", "edit_requested")
    orders = (
        db.query(Order)
        .filter(Order.status.in_(awaiting))
        .order_by(Order.created_at.desc())
        .limit(50)
        .all()
    )
    for order in orders:
        if _phones_match(order.phone_e164, phone) or _phones_match(order.phone_digits, phone):
            return order
    return None


def _status_for_action(action: ReplyAction) -> Optional[str]:
    if action == ReplyAction.CONFIRM:
        return "confirmed"
    if action == ReplyAction.EDIT:
        return "edit_requested"
    if action == ReplyAction.CANCEL:
        return "cancelled"
    return None


def _reply_text_for_action(action: ReplyAction, order: Optional[Order]) -> Optional[str]:
    if action == ReplyAction.UNKNOWN:
        return None
    if not order:
        return REPLY_NO_ORDER
    if action == ReplyAction.CONFIRM and order.status == "confirmed":
        return REPLY_ALREADY_CONFIRMED
    if action == ReplyAction.CANCEL and order.status == "cancelled":
        return REPLY_ALREADY_CANCELLED
    if action == ReplyAction.CONFIRM:
        return REPLY_CONFIRM
    if action == ReplyAction.EDIT:
        return REPLY_EDIT
    if action == ReplyAction.CANCEL:
        return REPLY_CANCEL
    return None


async def process_incoming_message(db: Session, message: IncomingMessage) -> dict:
    order = find_pending_order(db, message.from_phone)
    reply_text = _reply_text_for_action(message.action, order)

    if message.action == ReplyAction.UNKNOWN:
        logger.info("WhatsApp reply ignored (unknown) from=%s text=%s", message.from_phone, message.raw_text)
        return {"handled": False, "reason": "unknown_action"}

    if not reply_text:
        return {"handled": False, "reason": "no_reply"}

    wa_resp = await send_text_message(phone_digits=message.from_phone, text=reply_text)

    new_status = _status_for_action(message.action)
    status_changed_to_confirmed = False
    if order and new_status and order.status != new_status:
        if not (
            message.action == ReplyAction.CONFIRM and order.status == "confirmed"
        ) and not (
            message.action == ReplyAction.CANCEL and order.status == "cancelled"
        ):
            order.status = new_status
            if new_status == "confirmed":
                status_changed_to_confirmed = True
            if message.action == ReplyAction.EDIT:
                note = f"[WhatsApp] طلب تعديل: {message.raw_text}"
                order.admin_notes = (
                    f"{order.admin_notes}\n{note}".strip()
                    if order.admin_notes
                    else note
                )
            db.commit()

    if order and status_changed_to_confirmed:
        await dispatch_order_to_sendit(db, order)

    if order:
        order_service.log_tracking_event(
            db,
            order,
            "whatsapp",
            f"reply_{message.action.value}",
            {
                "message_id": message.message_id,
                "button_id": message.button_id,
                "raw_text": message.raw_text,
                "new_status": order.status,
            },
            wa_resp,
        )

    logger.info(
        "WhatsApp auto-reply action=%s from=%s order=%s success=%s",
        message.action.value,
        message.from_phone,
        order.order_number if order else None,
        wa_resp.get("success"),
    )
    return {
        "handled": True,
        "action": message.action.value,
        "order_number": order.order_number if order else None,
        "whatsapp": wa_resp,
    }
