import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    Boolean,
    ForeignKey,
    Text,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number = Column(String(32), unique=True, nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    phone_e164 = Column(String(20), nullable=False)
    phone_digits = Column(String(20), nullable=False)
    status = Column(String(32), nullable=False, default="new")
    subtotal_sar = Column(Numeric(10, 2), nullable=False, default=0)
    discount_sar = Column(Numeric(10, 2), nullable=False, default=0)
    total_sar = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), nullable=False, default="SAR")
    payment_method = Column(String(32), nullable=False, default="cod")
    event_id = Column(String(64), nullable=False)
    landing_page = Column(Text, nullable=True)
    utm_source = Column(String(128), nullable=True)
    utm_medium = Column(String(128), nullable=True)
    utm_campaign = Column(String(128), nullable=True)
    utm_content = Column(String(128), nullable=True)
    utm_term = Column(String(128), nullable=True)
    fbp = Column(String(256), nullable=True)
    fbc = Column(String(256), nullable=True)
    ttp = Column(String(256), nullable=True)
    ttclid = Column(String(2048), nullable=True)
    sc_click_id = Column(String(512), nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    sheet_response = Column(Text, nullable=True)
    tracking_response = Column(Text, nullable=True)
    admin_notes = Column(Text, nullable=True)
    country_code = Column(String(4), nullable=True)
    geo_is_vpn = Column(Boolean, nullable=False, default=False)
    geo_is_proxy = Column(Boolean, nullable=False, default=False)
    geo_is_valid = Column(Boolean, nullable=False, default=False, index=True)
    geo_block_reason = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    tracking_events = relationship(
        "TrackingEvent", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(String(128), nullable=False)
    product_name_ar = Column(String(512), nullable=False)
    offer_id = Column(String(32), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    unit_count = Column(Integer, nullable=False, default=1)
    source = Column(String(64), nullable=False, default="pdp")
    price_sar = Column(Numeric(10, 2), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    order = relationship("Order", back_populates="items")


class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True, index=True)
    platform = Column(String(32), nullable=False)
    event_name = Column(String(64), nullable=False)
    event_id = Column(String(64), nullable=False)
    payload_json = Column(Text, nullable=True)
    response_json = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    order = relationship("Order", back_populates="tracking_events")


class Click(Base):
    __tablename__ = "clicks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visitor_id = Column(String(64), nullable=False, index=True)
    landing_page = Column(Text, nullable=True)
    referrer = Column(Text, nullable=True)
    country_code = Column(String(4), nullable=True)
    is_vpn = Column(Boolean, nullable=False, default=False)
    is_proxy = Column(Boolean, nullable=False, default=False)
    is_valid = Column(Boolean, nullable=False, default=True, index=True)
    block_reason = Column(String(255), nullable=True)
    client_ip = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    utm_source = Column(String(128), nullable=True, index=True)
    utm_medium = Column(String(128), nullable=True)
    utm_campaign = Column(String(128), nullable=True, index=True)
    utm_content = Column(String(128), nullable=True)
    utm_term = Column(String(128), nullable=True)
    fbp = Column(String(256), nullable=True)
    fbc = Column(String(256), nullable=True)
    ttp = Column(String(256), nullable=True)
    ttclid = Column(String(2048), nullable=True)
    sc_click_id = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
