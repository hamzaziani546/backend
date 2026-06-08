-- Migration 005: Product landing pages (admin-managed, not in store nav)
--   psql "$DATABASE_URL" -f backend/migrations/005_landing_pages.sql
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS landing_pages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    product_id          VARCHAR(128) NOT NULL,
    title_ar            VARCHAR(512) NOT NULL,
    hero_image          TEXT         NOT NULL,
    rating              NUMERIC(2, 1) NOT NULL DEFAULT 4.9,
    review_count        INTEGER      NOT NULL DEFAULT 120,
    gallery_images_json TEXT         NOT NULL DEFAULT '[]',
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_landing_pages_slug ON landing_pages (slug);
CREATE INDEX IF NOT EXISTS idx_landing_pages_product_id ON landing_pages (product_id);
CREATE INDEX IF NOT EXISTS idx_landing_pages_is_active ON landing_pages (is_active);
