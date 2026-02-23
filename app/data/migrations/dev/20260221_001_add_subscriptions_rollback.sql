-- ============================================================
-- ROLLBACK: 20260221_001_add_subscriptions (DEV)
-- Desfaz: criação da tabela subscriptions e FK em transactions
-- ⚠️ ATENÇÃO: Remove TODOS os dados de assinaturas permanentemente.
-- ============================================================

ALTER TABLE transactions DROP COLUMN IF EXISTS subscription_id;
DROP TABLE IF EXISTS subscriptions CASCADE;

DELETE FROM schema_migrations WHERE version = '20260221_001_add_subscriptions';
