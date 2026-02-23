-- Migration: Adicionar coluna data_transacao
-- Objetivo: Separar a data em que a transação realmente ocorreu (data_transacao)
--           da data em que foi registrada no sistema (data_registro)

-- 1. Adicionar nova coluna
ALTER TABLE transactions 
ADD COLUMN data_transacao DATE;

-- 2. Popular com data_registro para registros existentes
UPDATE transactions 
SET data_transacao = data_registro 
WHERE data_transacao IS NULL;

-- 3. Tornar obrigatória e adicionar constraint
ALTER TABLE transactions 
ALTER COLUMN data_transacao SET NOT NULL;

-- Constraint: data_transacao não pode ser no futuro
ALTER TABLE transactions
ADD CONSTRAINT chk_data_transacao_nao_futura 
CHECK (data_transacao <= CURRENT_DATE);

-- 4. Adicionar comentários
COMMENT ON COLUMN transactions.data_registro IS 
'Data em que a transação foi registrada no sistema';

COMMENT ON COLUMN transactions.data_transacao IS 
'Data em que a transação realmente ocorreu (pode ser diferente do registro)';
