-- ============================================================
-- ROLLBACK: 20260222_001_schema_migrations_bootstrap
-- Desfaz: criação da tabela schema_migrations
-- ⚠️ ATENÇÃO: Remove TODO o histórico de rastreamento de migrations.
--             Executar este rollback apenas como último recurso.
-- ============================================================

DROP TABLE IF EXISTS public.schema_migrations;
