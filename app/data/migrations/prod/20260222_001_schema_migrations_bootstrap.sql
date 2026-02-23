-- ============================================================
-- MIGRATION: Bootstrap do sistema de rastreamento de migrations
-- Data: 2026-02-22
-- Descrição: Cria a tabela schema_migrations e registra o histórico
--            de todas as migrations já aplicadas em cada ambiente.
-- ============================================================

-- 1. Criar tabela de rastreamento
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version     TEXT        PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT
);
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 2. Seed histórico — rodar os INSERTs do ambiente correspondente
-- ============================================================

-- ⬇️ PROD: executar no banco de PRODUÇÃO
INSERT INTO schema_migrations (version, description, applied_at) VALUES
    ('20260221_001_prod_add_subscriptions', 'Cria tabela subscriptions com trigger e índices', '2026-02-21 00:00:00+00'),
    ('20260221_002_prod_remove_benchmark',  'Remove benchmark_history e programs.benchmark_atual', '2026-02-21 00:00:00+00'),
    ('20260221_003_prod_sync_transactions', 'Adiciona data_transacao e observacao em transactions', '2026-02-21 00:00:00+00')
ON CONFLICT DO NOTHING;

-- ⬇️ DEV: executar no banco de DESENVOLVIMENTO
-- INSERT INTO schema_migrations (version, description, applied_at) VALUES
--     ('20260221_001_add_subscriptions',  'Cria tabela subscriptions versão DEV (com DROP TABLE)', '2026-02-21 00:00:00+00'),
--     ('20260221_002_add_observacao',     'Adiciona coluna observacao em transactions', '2026-02-21 00:00:00+00'),
--     ('20260221_003_add_data_transacao', 'Adiciona coluna data_transacao em transactions', '2026-02-21 00:00:00+00')
-- ON CONFLICT DO NOTHING;

-- Verificação final
SELECT version, applied_at, description
FROM schema_migrations
ORDER BY version;
