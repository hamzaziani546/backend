import uuid

from app.models import Order


def order_lookup_filter(order_id: str):
    try:
        uid = uuid.UUID(order_id)
        return (Order.id == uid) | (Order.order_number == order_id)
    except ValueError:
        return Order.order_number == order_id
