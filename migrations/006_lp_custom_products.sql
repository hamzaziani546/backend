-- Migration 006: Custom LP products (offers) independent of store catalog
ALTER TABLE landing_pages ADD COLUMN IF NOT EXISTS offers_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE landing_pages ALTER COLUMN product_id DROP NOT NULL;
