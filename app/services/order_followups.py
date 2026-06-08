import json
import logging
from typing import Optional

from app.config import settings
from app.database import SessionLocal
from app.models import Order
from app.services import orders as order_service
from app.services import sheets as sheet_service
from app.services.tracking import meta as meta_capi
from app.services.tracking import snapchat as snap_capi
from app.services.tracking import tiktok as tiktok_capi
from app.services.whatsapp import format_delivery_address, send_order_confirmation

logger = logging.getLogger(__name__)


async def process_order_followups(
    order_id: str,
    *,
    city: str,
    address: str,
    sc_cookie1: Optional[str],
    sheet_payload: dict,
) -> None:
    """Sheet sync, WhatsApp confirmation, and CAPI — runs after checkout response."""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if not order:
            logger.warning("Follow-up skipped — order not found: %s", order_id)
            return

        items_list = list(order.items)
        items_for_tracking = [
            {
                "product_id": item.product_id,
                "unit_count": item.unit_count,
                "price_mad": float(item.price_mad),
            }
            for item in items_list
        ]
        event_source_url = (
            f"{settings.PUBLIC_SITE_URL}/thank-you/{order.order_number}"
        )

        sheet_resp = await sheet_service.send_order_to_sheet(sheet_payload)
        order.sheet_response = json.dumps(sheet_resp, ensure_ascii=False, default=str)
        if not sheet_resp.get("success"):
            order.status = "sheet_failed"
        else:
            order.status = "sent_to_sheet"
        db.commit()

        if settings.WHATSAPP_AUTO_CONFIRM and order.status == "sent_to_sheet":
            product_label = " / ".join(i.product_name_ar for i in items_list)
            delivery_address = format_delivery_address(
                city=city,
                address=address,
                admin_notes=order.admin_notes,
            )
            wa_resp = await send_order_confirmation(
                phone_e164=order.phone_e164,
                customer_name=order.customer_name,
                order_number=order.order_number,
                delivery_address=delivery_address,
                product_label=product_label,
                total_mad=float(order.total_mad),
            )
            order_service.log_tracking_event(
                db,
                order,
                "whatsapp",
                "order_confirmation",
                {
                    "order_number": order.order_number,
                    "template": settings.WHATSAPP_ORDER_TEMPLATE,
                },
                wa_resp,
            )
            if wa_resp.get("success"):
                order.status = "confirmation_sent"
            db.commit()

        tracking_results: dict = {}
        capi_context = {
            "order_number": order.order_number,
            "total_mad": float(order.total_mad),
            "item_count": len(items_for_tracking),
            "event_source_url": event_source_url,
        }

        meta_resp = await meta_capi.send_purchase_event(
            order_number=order.order_number,
            phone_digits=order.phone_digits,
            total_mad=float(order.total_mad),
            items=items_for_tracking,
            event_source_url=event_source_url,
            fbp=order.fbp,
            fbc=order.fbc,
            client_ip=order.client_ip,
            user_agent=order.user_agent,
        )
        tracking_results["meta"] = meta_resp
        order_service.log_tracking_event(
            db, order, "meta", "Purchase", capi_context, meta_resp
        )

        tt_resp = await tiktok_capi.send_purchase_event(
            order_number=order.order_number,
            phone_digits=order.phone_digits,
            total_mad=float(order.total_mad),
            items=items_for_tracking,
            event_source_url=event_source_url,
            ttp=order.ttp,
            ttclid=order.ttclid,
            client_ip=order.client_ip,
            user_agent=order.user_agent,
        )
        tracking_results["tiktok"] = tt_resp
        order_service.log_tracking_event(
            db, order, "tiktok", "CompletePayment", capi_context, tt_resp
        )

        snap_resp = await snap_capi.send_purchase_event(
            order_number=order.order_number,
            phone_digits=order.phone_digits,
            total_mad=float(order.total_mad),
            items=items_for_tracking,
            event_source_url=event_source_url,
            sc_click_id=order.sc_click_id,
            sc_cookie1=sc_cookie1,
            client_ip=order.client_ip,
            user_agent=order.user_agent,
        )
        tracking_results["snapchat"] = snap_resp
        order_service.log_tracking_event(
            db, order, "snapchat", "PURCHASE", capi_context, snap_resp
        )

        order.tracking_response = json.dumps(
            tracking_results, ensure_ascii=False, default=str
        )
        db.commit()
    except Exception:
        logger.exception("Order follow-up failed for %s", order_id)
    finally:
        db.close()
