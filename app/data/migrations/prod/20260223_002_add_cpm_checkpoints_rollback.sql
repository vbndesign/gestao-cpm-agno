-- ============================================================
-- ROLLBACK: 20260223_002_add_cpm_checkpoints
-- ============================================================

DROP TABLE IF EXISTS cpm_checkpoints;

DELETE FROM schema_migrations WHERE version = '20260223_002_add_cpm_checkpoints';
