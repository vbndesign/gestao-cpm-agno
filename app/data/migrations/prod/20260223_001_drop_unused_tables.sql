-- ============================================================
-- MIGRATION: Remover tabelas não utilizadas no MVP
-- Data: 2026-02-23
-- Descrição: Remove as tabelas balances, cpf_slots e issuances,
--            que foram criadas durante o processo de design mas
--            não chegaram a ser implementadas. Nenhuma delas é
--            referenciada no db_toolkit.py ou em qualquer rota/agente.
--            Índices e políticas de RLS são removidos automaticamente.
-- ⚠️ ATENÇÃO: Esta operação é destrutiva. Certifique-se de que não há
--             dados relevantes nestas tabelas antes de executar.
-- ============================================================

-- Remove trigger que depende de issuances antes de dropar a tabela
DROP TRIGGER IF EXISTS update_issuances_modtime ON issuances;

-- Remove tabelas (índices e RLS caem automaticamente com a tabela)
DROP TABLE IF EXISTS issuances;
DROP TABLE IF EXISTS cpf_slots;
DROP TABLE IF EXISTS balances;

-- Verificação final
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('issuances', 'cpf_slots', 'balances')
ORDER BY tablename;
-- Deve retornar 0 linhas

-- Registrar migration como aplicada
INSERT INTO schema_migrations (version, description)
VALUES ('20260223_001_drop_unused_tables', 'Remove tabelas não utilizadas no MVP: balances, cpf_slots, issuances')
ON CONFLICT DO NOTHING;
