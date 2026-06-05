-- Migration 003: Morocco market defaults for geo metrics
UPDATE orders
SET geo_is_valid = TRUE
WHERE country_code = 'MA'
  AND geo_is_valid = FALSE
  AND geo_block_reason IS NULL;
