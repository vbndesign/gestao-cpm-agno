-- ============================================================
-- ROLLBACK: 20260222_002_add_unique_active_subscription
-- Desfaz: índice único parcial idx_subs_unique_active
-- ============================================================

DROP INDEX IF EXISTS idx_subs_unique_active;

DELETE FROM schema_migrations WHERE version = '20260222_002_add_unique_active_subscription';
