-- ============================================================
-- Full schema bootstrap for a fresh/emptied Postgres database.
-- Safe to re-run.
--
--   psql "$DATABASE_URL" -f backend/migrations/000_full_schema.sql
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS orders (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number      VARCHAR(32)  NOT NULL UNIQUE,
    customer_name     VARCHAR(255) NOT NULL,
    phone_e164        VARCHAR(20)  NOT NULL,
    phone_digits      VARCHAR(20)  NOT NULL,
    status            VARCHAR(32)  NOT NULL DEFAULT 'new',
    subtotal_mad      NUMERIC(10, 2) NOT NULL DEFAULT 0,
    discount_mad      NUMERIC(10, 2) NOT NULL DEFAULT 0,
    total_mad         NUMERIC(10, 2) NOT NULL,
    currency          VARCHAR(3)   NOT NULL DEFAULT 'MAD',
    payment_method    VARCHAR(32)  NOT NULL DEFAULT 'cod',
    event_id          VARCHAR(64)  NOT NULL,
    landing_page      TEXT,
    utm_source        VARCHAR(128),
    utm_medium        VARCHAR(128),
    utm_campaign      VARCHAR(128),
    utm_content       VARCHAR(128),
    utm_term          VARCHAR(128),
    fbp               VARCHAR(256),
    fbc               VARCHAR(256),
    ttp               VARCHAR(256),
    ttclid            VARCHAR(256),
    sc_click_id       VARCHAR(256),
    client_ip         VARCHAR(64),
    user_agent        TEXT,
    sheet_response    TEXT,
    tracking_response TEXT,
    admin_notes       TEXT,
    country_code      VARCHAR(4),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id),
    product_id      VARCHAR(128) NOT NULL,
    product_name_ar VARCHAR(512) NOT NULL,
    offer_id        VARCHAR(32) NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_count      INTEGER NOT NULL DEFAULT 1,
    source          VARCHAR(64) NOT NULL DEFAULT 'pdp',
    price_mad       NUMERIC(10, 2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tracking_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id      UUID REFERENCES orders(id),
    platform      VARCHAR(32) NOT NULL,
    event_name    VARCHAR(64) NOT NULL,
    event_id      VARCHAR(64) NOT NULL,
    payload_json  TEXT,
    response_json TEXT,
    status_code   INTEGER,
    success       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS clicks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visitor_id      VARCHAR(64)  NOT NULL,
    landing_page    TEXT,
    referrer        TEXT,
    country_code    VARCHAR(4),
    is_vpn          BOOLEAN      NOT NULL DEFAULT FALSE,
    is_proxy        BOOLEAN      NOT NULL DEFAULT FALSE,
    is_valid        BOOLEAN      NOT NULL DEFAULT TRUE,
    block_reason    VARCHAR(255),
    client_ip       VARCHAR(64),
    user_agent      TEXT,
    utm_source      VARCHAR(128),
    utm_medium      VARCHAR(128),
    utm_campaign    VARCHAR(128),
    utm_content     VARCHAR(128),
    utm_term        VARCHAR(128),
    fbp             VARCHAR(256),
    fbc             VARCHAR(256),
    ttp             VARCHAR(256),
    ttclid          VARCHAR(256),
    sc_click_id     VARCHAR(256),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_orders_order_number ON orders (order_number);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders (created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_utm_source ON orders (utm_source);
CREATE INDEX IF NOT EXISTS idx_orders_utm_campaign ON orders (utm_campaign);

CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_tracking_events_order_id ON tracking_events (order_id);

CREATE INDEX IF NOT EXISTS idx_clicks_created_at ON clicks (created_at);
CREATE INDEX IF NOT EXISTS idx_clicks_visitor_id ON clicks (visitor_id);
CREATE INDEX IF NOT EXISTS idx_clicks_is_valid ON clicks (is_valid);
CREATE INDEX IF NOT EXISTS idx_clicks_utm_source ON clicks (utm_source);
CREATE INDEX IF NOT EXISTS idx_clicks_utm_campaign ON clicks (utm_campaign);

