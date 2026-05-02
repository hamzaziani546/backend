"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.String(32), nullable=False, unique=True),
        sa.Column("customer_name", sa.String(255), nullable=False),
        sa.Column("phone_e164", sa.String(20), nullable=False),
        sa.Column("phone_digits", sa.String(20), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="new"),
        sa.Column("subtotal_sar", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("discount_sar", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total_sar", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="SAR"),
        sa.Column("payment_method", sa.String(32), nullable=False, server_default="cod"),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("landing_page", sa.Text, nullable=True),
        sa.Column("utm_source", sa.String(128), nullable=True),
        sa.Column("utm_medium", sa.String(128), nullable=True),
        sa.Column("utm_campaign", sa.String(128), nullable=True),
        sa.Column("utm_content", sa.String(128), nullable=True),
        sa.Column("utm_term", sa.String(128), nullable=True),
        sa.Column("fbp", sa.String(256), nullable=True),
        sa.Column("fbc", sa.String(256), nullable=True),
        sa.Column("ttp", sa.String(256), nullable=True),
        sa.Column("ttclid", sa.String(256), nullable=True),
        sa.Column("sc_click_id", sa.String(256), nullable=True),
        sa.Column("client_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("sheet_response", sa.Text, nullable=True),
        sa.Column("tracking_response", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"])

    op.create_table(
        "order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("product_name_ar", sa.String(512), nullable=False),
        sa.Column("offer_id", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("unit_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source", sa.String(64), nullable=False, server_default="pdp"),
        sa.Column("price_sar", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "tracking_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=True,
        ),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.Column("response_json", sa.Text, nullable=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_tracking_events_order_id", "tracking_events", ["order_id"])


def downgrade() -> None:
    op.drop_table("tracking_events")
    op.drop_table("order_items")
    op.drop_table("orders")
