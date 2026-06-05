-- ============================================================
-- Migration 001: Admin dashboard + click tracking
-- Run once against the production Postgres database.
--   psql "$DATABASE_URL" -f backend/migrations/001_admin_dashboard.sql
-- Idempotent: safe to re-run.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) Click tracking ------------------------------------------------
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

CREATE INDEX IF NOT EXISTS idx_clicks_created_at  ON clicks (created_at);
CREATE INDEX IF NOT EXISTS idx_clicks_visitor_id  ON clicks (visitor_id);
CREATE INDEX IF NOT EXISTS idx_clicks_is_valid    ON clicks (is_valid);
CREATE INDEX IF NOT EXISTS idx_clicks_utm_source  ON clicks (utm_source);
CREATE INDEX IF NOT EXISTS idx_clicks_utm_campaign ON clicks (utm_campaign);

-- 2) Admin fields on orders ---------------------------------------
ALTER TABLE orders ADD COLUMN IF NOT EXISTS admin_notes  TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS country_code VARCHAR(4);

CREATE INDEX IF NOT EXISTS idx_orders_created_at   ON orders (created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status       ON orders (status);
CREATE INDEX IF NOT EXISTS idx_orders_utm_source   ON orders (utm_source);
CREATE INDEX IF NOT EXISTS idx_orders_utm_campaign ON orders (utm_campaign);
