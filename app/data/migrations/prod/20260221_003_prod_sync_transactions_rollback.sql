-- ============================================================
-- ROLLBACK: 20260221_003_prod_sync_transactions
-- Desfaz: adição de data_transacao e observacao em transactions
-- ⚠️ ATENÇÃO: Remove os valores de data_transacao de todos os registros.
-- ============================================================

ALTER TABLE transactions DROP CONSTRAINT IF EXISTS chk_data_transacao_nao_futura;
ALTER TABLE transactions DROP COLUMN IF EXISTS data_transacao;
ALTER TABLE transactions DROP COLUMN IF EXISTS observacao;

DELETE FROM schema_migrations WHERE version = '20260221_003_prod_sync_transactions';
