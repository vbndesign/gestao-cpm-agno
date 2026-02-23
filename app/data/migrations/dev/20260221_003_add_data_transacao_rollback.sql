-- ============================================================
-- ROLLBACK: 20260221_003_add_data_transacao (DEV)
-- Desfaz: adição da coluna data_transacao em transactions
-- ============================================================

ALTER TABLE transactions DROP CONSTRAINT IF EXISTS chk_data_transacao_nao_futura;
ALTER TABLE transactions DROP COLUMN IF EXISTS data_transacao;

DELETE FROM schema_migrations WHERE version = '20260221_003_add_data_transacao';
