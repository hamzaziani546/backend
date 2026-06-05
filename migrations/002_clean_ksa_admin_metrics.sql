-- ============================================================
-- Migration 002: Clean KSA admin metrics fields
-- Run once against the production Postgres database.
--   psql "$DATABASE_URL" -f backend/migrations/002_clean_ksa_admin_metrics.sql
-- Idempotent: safe to re-run.
-- ============================================================

ALTER TABLE orders ADD COLUMN IF NOT EXISTS geo_is_vpn BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS geo_is_proxy BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS geo_is_valid BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS geo_block_reason VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_orders_geo_is_valid ON orders (geo_is_valid);

-- Existing rows cannot be retroactively VPN-checked. Keep them out of clean
-- traffic metrics unless they were already stamped as Saudi orders.
UPDATE orders
SET geo_is_valid = TRUE
WHERE country_code = 'SA'
  AND geo_is_valid = FALSE
  AND geo_block_reason IS NULL;
