-- ============================================================
-- ROLLBACK: 20260223_001_drop_unused_tables
-- Desfaz: recria as tabelas balances, cpf_slots e issuances
--         com suas definições originais, triggers, índices e RLS.
-- ============================================================

-- Recriar tabela cpf_slots
CREATE TABLE IF NOT EXISTS cpf_slots (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID        NOT NULL REFERENCES accounts(id),
    programa_id UUID        NOT NULL REFERENCES programs(id),
    slots_totais INTEGER    DEFAULT 25,
    slots_usados INTEGER    DEFAULT 0,
    data_reset  DATE,
    updated_at  TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- Recriar tabela balances
CREATE TABLE IF NOT EXISTS balances (
    account_id          UUID           NOT NULL REFERENCES accounts(id),
    programa_id         UUID           NOT NULL REFERENCES programs(id),
    milhas_disponiveis  INTEGER        DEFAULT 0,
    custo_total_estoque NUMERIC(15, 2) DEFAULT 0.00,
    cpm_medio           NUMERIC(15, 2) DEFAULT 0.00,
    updated_at          TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    PRIMARY KEY (account_id, programa_id)
);

-- Recriar tabela issuances
CREATE TABLE IF NOT EXISTS issuances (
    id                UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id        UUID           NOT NULL REFERENCES accounts(id),
    programa_id       UUID           NOT NULL REFERENCES programs(id),
    data_emissao      DATE           DEFAULT CURRENT_DATE,
    passageiro_nome   TEXT           NOT NULL,
    passageiro_cpf    TEXT,
    localizador       TEXT,
    milhas_utilizadas INTEGER        NOT NULL,
    cpm_medio_momento NUMERIC(15, 2) NOT NULL,
    custo_venda       NUMERIC(15, 2) NOT NULL,
    valor_venda       NUMERIC(15, 2) NOT NULL,
    lucro_bruto NUMERIC(15, 2) GENERATED ALWAYS AS (valor_venda - custo_venda) STORED,
    margem_percent NUMERIC(5, 2) GENERATED ALWAYS AS (
        CASE WHEN valor_venda > 0 THEN (valor_venda - custo_venda) / valor_venda * 100 ELSE 0 END
    ) STORED,
    status     TEXT        CHECK (status IN ('EMITIDA', 'VOADA', 'CANCELADA')) DEFAULT 'EMITIDA',
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- Recriar trigger de issuances
CREATE TRIGGER update_issuances_modtime
    BEFORE UPDATE ON issuances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Recriar índices
CREATE INDEX IF NOT EXISTS idx_cpf_slots_account_id  ON cpf_slots(account_id);
CREATE INDEX IF NOT EXISTS idx_cpf_slots_programa_id ON cpf_slots(programa_id);
CREATE INDEX IF NOT EXISTS idx_balances_programa_id  ON balances(programa_id);
CREATE INDEX IF NOT EXISTS idx_issuances_account_id  ON issuances(account_id);
CREATE INDEX IF NOT EXISTS idx_issuances_programa_id ON issuances(programa_id);

-- Reativar RLS
ALTER TABLE cpf_slots  ENABLE ROW LEVEL SECURITY;
ALTER TABLE balances   ENABLE ROW LEVEL SECURITY;
ALTER TABLE issuances  ENABLE ROW LEVEL SECURITY;

-- Remover registro da migration
DELETE FROM schema_migrations WHERE version = '20260223_001_drop_unused_tables';
