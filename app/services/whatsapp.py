import logging
import re
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

META_GRAPH = "https://graph.facebook.com/v21.0"


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _template_value(value: str, *, on_new_line: bool = False, max_len: int = 60) -> str:
    """Meta template labels omit spaces before {{n}} — break values onto a new line."""
    text = (value or "").strip()
    if on_new_line and text:
        text = f"\n{text}"
    return text[:max_len]


def format_delivery_address(
    city: str = "",
    address: str = "",
    admin_notes: Optional[str] = None,
) -> str:
    city = (city or "").strip()
    address = (address or "").strip()
    if city and address:
        return f"{city}، {address}"
    if city:
        return city
    if address:
        return address
    if admin_notes:
        city_match = re.search(r"المدينة:\s*(.+)", admin_notes)
        addr_match = re.search(r"العنوان:\s*(.+)", admin_notes)
        parts = []
        if city_match:
            parts.append(city_match.group(1).strip())
        if addr_match:
            parts.append(addr_match.group(1).strip())
        if parts:
            return "، ".join(parts)
    return "المغرب"


async def send_order_confirmation(
    *,
    phone_e164: str,
    customer_name: str,
    order_number: str,
    delivery_address: str,
    product_label: str,
    total_mad: float,
) -> dict:
    if not settings.WHATSAPP_PHONE_NUMBER_ID or not settings.WHATSAPP_ACCESS_TOKEN:
        logger.info("WhatsApp confirmation skipped — credentials not configured")
        return {"skipped": True, "reason": "WhatsApp credentials not configured"}

    to_phone = _digits_only(phone_e164)
    if not to_phone:
        return {"success": False, "error": "Invalid phone number"}

    total_label = (
        f"{int(total_mad) if float(total_mad).is_integer() else total_mad} درهم"
    )

    url = f"{META_GRAPH}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": settings.WHATSAPP_ORDER_TEMPLATE,
            "language": {"code": settings.WHATSAPP_ORDER_TEMPLATE_LANG},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": customer_name[:60]},
                        {
                            "type": "text",
                            "text": _template_value(order_number, on_new_line=True, max_len=60),
                        },
                        {
                            "type": "text",
                            "text": _template_value(
                                delivery_address, on_new_line=True, max_len=200
                            ),
                        },
                        {
                            "type": "text",
                            "text": _template_value(
                                product_label, on_new_line=True, max_len=120
                            ),
                        },
                        {
                            "type": "text",
                            "text": _template_value(total_label, on_new_line=True, max_len=40),
                        },
                    ],
                }
            ],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            data = response.json()
            if response.is_success:
                message_id = (data.get("messages") or [{}])[0].get("id")
                logger.info(
                    "WhatsApp confirmation sent order=%s to=%s id=%s",
                    order_number,
                    to_phone,
                    message_id,
                )
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "message_id": message_id,
                    "response": data,
                }
            logger.error(
                "WhatsApp confirmation failed order=%s status=%s body=%s",
                order_number,
                response.status_code,
                data,
            )
            return {
                "success": False,
                "status_code": response.status_code,
                "error": data.get("error", data),
                "response": data,
            }
    except Exception as exc:
        logger.exception("WhatsApp confirmation error order=%s", order_number)
        return {"success": False, "error": str(exc)}
