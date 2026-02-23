-- ============================================================
-- MIGRATION: Garantir unicidade de assinaturas ativas por contrato
-- Data: 2026-02-22
-- Descrição: Adiciona índice único parcial em subscriptions para impedir
--            múltiplas assinaturas ativas para o mesmo (account_id, programa_id).
--            O índice parcial (WHERE ativo = TRUE) não afeta assinaturas históricas.
-- ⚠️ ATENÇÃO: Se o banco já possuir duplicatas ativas, esta migration falhará.
--             Nesse caso, desativar as duplicatas manualmente antes de executar.
-- ============================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_unique_active
    ON subscriptions (account_id, programa_id)
    WHERE ativo = TRUE;

-- Verificação final
SELECT
    (SELECT COUNT(*) FROM pg_indexes
     WHERE tablename = 'subscriptions' AND indexname = 'idx_subs_unique_active') AS indice_deve_ser_1;
