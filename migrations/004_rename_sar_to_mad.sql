-- Migration 004: Rename SAR column/field names to MAD (Morocco market)
-- Run once against production Postgres:
--   psql "$DATABASE_URL" -f backend/migrations/004_rename_sar_to_mad.sql
-- Idempotent: safe to re-run.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'subtotal_sar'
  ) THEN
    ALTER TABLE orders RENAME COLUMN subtotal_sar TO subtotal_mad;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'discount_sar'
  ) THEN
    ALTER TABLE orders RENAME COLUMN discount_sar TO discount_mad;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'orders' AND column_name = 'total_sar'
  ) THEN
    ALTER TABLE orders RENAME COLUMN total_sar TO total_mad;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'order_items' AND column_name = 'price_sar'
  ) THEN
    ALTER TABLE order_items RENAME COLUMN price_sar TO price_mad;
  END IF;
END $$;

ALTER TABLE orders ALTER COLUMN currency SET DEFAULT 'MAD';

UPDATE orders SET currency = 'MAD' WHERE currency = 'SAR';
