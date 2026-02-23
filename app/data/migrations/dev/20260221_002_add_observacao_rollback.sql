-- ============================================================
-- ROLLBACK: 20260221_002_add_observacao (DEV)
-- Desfaz: adição da coluna observacao em transactions
-- ============================================================

ALTER TABLE transactions DROP COLUMN IF EXISTS observacao;

DELETE FROM schema_migrations WHERE version = '20260221_002_add_observacao';
