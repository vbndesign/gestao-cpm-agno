-- ============================================================
-- MIGRATION: Adicionar tabela cpm_checkpoints
-- Data: 2026-02-23
-- Descrição: Cria a tabela cpm_checkpoints para suportar o
--            protocolo de reajuste de CPM. Permite confirmar
--            o estado correto do CPM em um ponto no tempo
--            (checkpoint), tornando reconciliações futuras
--            eficientes (lê apenas o delta desde o último
--            checkpoint, não todo o histórico).
-- ============================================================

CREATE TABLE IF NOT EXISTS cpm_checkpoints (
    id                    UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id            UUID           NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    programa_id           UUID           NOT NULL REFERENCES programs(id),
    data_checkpoint       DATE           NOT NULL DEFAULT CURRENT_DATE,
    total_milhas          INTEGER        NOT NULL,
    total_custo           NUMERIC(15,2)  NOT NULL,
    cpm_snapshot          NUMERIC(15,2)  NOT NULL,
    tipo                  TEXT           NOT NULL DEFAULT 'MANUAL'
                              CHECK (tipo IN ('MENSAL', 'MANUAL', 'AUTO')),
    periodo_referencia    TEXT,
    delta_data_inicio     DATE,
    delta_data_fim        DATE,
    descricao             TEXT,
    observacao            TEXT,
    created_at            TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

CREATE INDEX IF NOT EXISTS idx_cpm_checkpoints_account_programa
    ON cpm_checkpoints(account_id, programa_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cpm_checkpoints_mensal_unico
    ON cpm_checkpoints(account_id, programa_id, periodo_referencia)
    WHERE periodo_referencia IS NOT NULL;

ALTER TABLE cpm_checkpoints ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE  cpm_checkpoints                    IS 'Fotografias do estado de CPM por conta/programa. Base do protocolo de reajuste de CPM.';
COMMENT ON COLUMN cpm_checkpoints.tipo               IS 'MENSAL=fechamento de mês, MANUAL=confirmação manual, AUTO=criado automaticamente pós-ajuste';
COMMENT ON COLUMN cpm_checkpoints.periodo_referencia IS 'Formato YYYY-MM. Preenchido apenas em tipo=MENSAL. Índice único garante 1 fechamento por mês.';
COMMENT ON COLUMN cpm_checkpoints.delta_data_inicio  IS 'data_transacao mais antiga das transações cobertas por este checkpoint';
COMMENT ON COLUMN cpm_checkpoints.delta_data_fim     IS 'data_transacao mais recente das transações cobertas por este checkpoint';
COMMENT ON COLUMN cpm_checkpoints.descricao          IS 'Descrição automática gerada pelo sistema';
COMMENT ON COLUMN cpm_checkpoints.observacao         IS 'Observação opcional fornecida pelo usuário';

INSERT INTO schema_migrations (version, description)
VALUES ('20260223_001_add_cpm_checkpoints', 'Adiciona tabela cpm_checkpoints para protocolo de reajuste de CPM')
ON CONFLICT DO NOTHING;
