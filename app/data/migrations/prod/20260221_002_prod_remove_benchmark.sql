-- ============================================================
-- MIGRATION: Remover features de benchmark do PROD
-- Data: 2026-02-21
-- Descrição: Remove tabela benchmark_history e coluna programs.benchmark_atual
--            pois não existem no DEV (fonte da verdade). PROD deve espelhar DEV.
-- ⚠️ ATENÇÃO: Esta operação é IRREVERSÍVEL. Faça backup antes de executar.
-- ============================================================

-- 1. Remover tabela benchmark_history
--    (CASCADE remove indexes e constraints dependentes automaticamente)
DROP TABLE IF EXISTS benchmark_history CASCADE;

-- 2. Remover coluna benchmark_atual de programs
ALTER TABLE programs
DROP COLUMN IF EXISTS benchmark_atual;

-- Verificação final
SELECT
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'benchmark_history') AS benchmark_history_deve_ser_zero,
    (SELECT COUNT(*) FROM information_schema.columns
     WHERE table_name = 'programs' AND column_name = 'benchmark_atual') AS benchmark_atual_deve_ser_zero;
