-- ============================================================
-- ROLLBACK: 20260223_001_add_cpm_checkpoints
-- ============================================================

DROP TABLE IF EXISTS cpm_checkpoints;

DELETE FROM schema_migrations WHERE version = '20260223_001_add_cpm_checkpoints';
