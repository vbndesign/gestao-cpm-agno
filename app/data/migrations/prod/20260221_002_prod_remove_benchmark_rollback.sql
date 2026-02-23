-- ============================================================
-- ROLLBACK: 20260221_002_prod_remove_benchmark
-- Desfaz: remoção de benchmark_history e programs.benchmark_atual
-- ⚠️ ATENÇÃO: DADOS PERMANENTEMENTE PERDIDOS.
--             Este rollback recria apenas a estrutura (tabela vazia).
--             DDL original obtida do commit 25b3386 (2026-01-20).
-- ============================================================

ALTER TABLE programs
    ADD COLUMN IF NOT EXISTS benchmark_atual NUMERIC(10, 2) DEFAULT 0.00;

CREATE TABLE IF NOT EXISTS benchmark_history (
    id          UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    programa_id UUID           NOT NULL REFERENCES programs(id),
    valor_cpm   NUMERIC(10, 2) NOT NULL,
    data_inicio DATE           NOT NULL,
    data_fim    DATE,
    created_at  TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

DELETE FROM schema_migrations WHERE version = '20260221_002_prod_remove_benchmark';
