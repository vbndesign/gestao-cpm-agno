-- ========================================================
-- MIGRATION: Adicionar coluna observacao em transactions
-- Data: 2026-01-16
-- Descrição: Separa descrição automática do sistema de observações do usuário
-- ========================================================

-- Adiciona coluna para observações do usuário (opcional)
ALTER TABLE transactions 
ADD COLUMN IF NOT EXISTS observacao TEXT;

COMMENT ON COLUMN transactions.descricao IS 'Descrição automática gerada pelo sistema';
COMMENT ON COLUMN transactions.observacao IS 'Observação opcional fornecida pelo usuário';

-- Verifica se a coluna foi criada
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'transactions' 
AND column_name IN ('descricao', 'observacao')
ORDER BY ordinal_position;
