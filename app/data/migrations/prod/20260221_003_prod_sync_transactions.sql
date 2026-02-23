-- ============================================================
-- MIGRATION: Sincronizar tabela transactions no PROD
-- Data: 2026-02-21
-- Descrição: Adiciona colunas presentes no DEV que estão ausentes no PROD:
--              - data_transacao (data real da transação)
--              - observacao (campo livre do usuário)
-- NOTA: subscription_id será adicionada pela migration de subscriptions
-- ============================================================

-- 1. Adicionar coluna data_transacao
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS data_transacao DATE;

-- Popular com data_registro para registros existentes
UPDATE transactions
SET data_transacao = data_registro::DATE
WHERE data_transacao IS NULL;

-- Tornar obrigatória
ALTER TABLE transactions
ALTER COLUMN data_transacao SET NOT NULL;

-- Constraint: data_transacao não pode ser no futuro
ALTER TABLE transactions
ADD CONSTRAINT IF NOT EXISTS chk_data_transacao_nao_futura
CHECK (data_transacao <= CURRENT_DATE);

COMMENT ON COLUMN transactions.data_registro IS 'Data em que a transação foi registrada no sistema';
COMMENT ON COLUMN transactions.data_transacao IS 'Data em que a transação realmente ocorreu (pode ser diferente do registro)';

-- 2. Adicionar coluna observacao
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS observacao TEXT;

COMMENT ON COLUMN transactions.descricao IS 'Descrição automática gerada pelo sistema';
COMMENT ON COLUMN transactions.observacao IS 'Observação opcional fornecida pelo usuário';

-- Verificação final
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'transactions'
  AND column_name IN ('data_transacao', 'observacao')
ORDER BY ordinal_position;
