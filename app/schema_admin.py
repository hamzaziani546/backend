import logging

from sqlalchemy import inspect, text

from app.database import Base, engine

logger = logging.getLogger(__name__)


ORDER_COLUMNS = {
    "admin_notes": "TEXT",
    "country_code": "VARCHAR(4)",
    "geo_is_vpn": "BOOLEAN NOT NULL DEFAULT FALSE",
    "geo_is_proxy": "BOOLEAN NOT NULL DEFAULT FALSE",
    "geo_is_valid": "BOOLEAN NOT NULL DEFAULT FALSE",
    "geo_block_reason": "VARCHAR(255)",
}

ORDER_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status)",
    "CREATE INDEX IF NOT EXISTS idx_orders_utm_source ON orders (utm_source)",
    "CREATE INDEX IF NOT EXISTS idx_orders_utm_campaign ON orders (utm_campaign)",
    "CREATE INDEX IF NOT EXISTS idx_orders_geo_is_valid ON orders (geo_is_valid)",
]

CLICK_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_clicks_created_at ON clicks (created_at)",
    "CREATE INDEX IF NOT EXISTS idx_clicks_visitor_id ON clicks (visitor_id)",
    "CREATE INDEX IF NOT EXISTS idx_clicks_is_valid ON clicks (is_valid)",
    "CREATE INDEX IF NOT EXISTS idx_clicks_utm_source ON clicks (utm_source)",
    "CREATE INDEX IF NOT EXISTS idx_clicks_utm_campaign ON clicks (utm_campaign)",
]


def ensure_admin_dashboard_schema() -> None:
    """Apply the app/admin schema at startup.

    This keeps deployed environments healthy even when the database was reset or
    the SQL migration was not run manually after shipping the dashboard.
    """
    import app.models  # noqa: F401 - registers all table metadata

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    if not inspector.has_table("orders"):
        logger.warning("orders table is missing; skipped admin schema migration")
        return

    existing_order_columns = {col["name"] for col in inspector.get_columns("orders")}

    with engine.begin() as conn:
        for column_name, ddl_type in ORDER_COLUMNS.items():
            if column_name not in existing_order_columns:
                conn.execute(text(f"ALTER TABLE orders ADD COLUMN {column_name} {ddl_type}"))

        for statement in [*ORDER_INDEXES, *CLICK_INDEXES]:
            conn.execute(text(statement))

