-- ========================================================
-- SCHEMA POSTGRESQL - WF MILHAS
-- Versão: sincronizado com DEV/PROD em 2026-02-21
-- Fonte: gerado a partir do banco DEV via MCP
--
-- USO: Este arquivo representa SEMPRE o estado atual do banco.
--      Para subir um banco do zero, execute este arquivo.
--      Alterações no banco devem ser refletidas aqui.
--
-- Histórico de alterações aplicadas em PROD:
--   migrations/prod/ → arquivos de referência de cada mudança
-- ========================================================

SET timezone = 'America/Sao_Paulo';

-- --------------------------------------------------------
-- FUNÇÕES
-- --------------------------------------------------------

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW() AT TIME ZONE 'America/Sao_Paulo';
   RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION fn_auto_disable_subscription()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.data_fim IS NOT NULL THEN
        NEW.ativo := FALSE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- --------------------------------------------------------
-- TABELAS
-- --------------------------------------------------------

-- 1. accounts
CREATE TABLE IF NOT EXISTS accounts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    cpf         TEXT        NOT NULL UNIQUE,
    nome        TEXT        NOT NULL,
    tipo_gestao TEXT        DEFAULT 'CLIENTE' CHECK (tipo_gestao IN ('PROPRIA', 'CLIENTE')),
    status      TEXT        DEFAULT 'ATIVO',
    created_at  TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at  TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 2. programs
CREATE TABLE IF NOT EXISTS programs (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    nome       TEXT        NOT NULL UNIQUE,
    tipo       TEXT        NOT NULL, -- CIA_AEREA, BANCO, OPERADORA
    ativo      BOOLEAN     DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 3. cpf_slots
CREATE TABLE IF NOT EXISTS cpf_slots (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID        NOT NULL REFERENCES accounts(id),
    programa_id UUID        NOT NULL REFERENCES programs(id),
    slots_totais INTEGER    DEFAULT 25,
    slots_usados INTEGER    DEFAULT 0,
    data_reset  DATE,
    updated_at  TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 4. subscriptions (clubes/recorrência)
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID           NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    programa_id             UUID           NOT NULL REFERENCES programs(id),
    valor_total_ciclo       NUMERIC(10, 2) NOT NULL CHECK (valor_total_ciclo > 0),
    milhas_garantidas_ciclo INTEGER        NOT NULL CHECK (milhas_garantidas_ciclo > 0),
    -- CPM calculado automaticamente (coluna gerada, imutável)
    cpm_fixo     NUMERIC(10, 2) GENERATED ALWAYS AS (
        (valor_total_ciclo / milhas_garantidas_ciclo::NUMERIC) * 1000
    ) STORED,
    data_inicio    DATE    NOT NULL DEFAULT CURRENT_DATE,
    data_renovacao DATE    NOT NULL,
    data_fim       DATE,
    ativo          BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    -- Integridade temporal
    CONSTRAINT chk_subs_fluxo_tempo    CHECK (data_renovacao >= data_inicio),
    CONSTRAINT chk_subs_fim_futuro     CHECK (data_fim IS NULL OR data_fim >= data_inicio),
    -- ativo=TRUE implica data_fim=NULL
    CONSTRAINT chk_subs_status_coerente CHECK ((ativo = FALSE) OR (data_fim IS NULL))
);

-- 5. transactions
CREATE TABLE IF NOT EXISTS transactions (
    id                     UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id             UUID           NOT NULL REFERENCES accounts(id),
    -- data_registro: quando foi lançado no sistema
    -- data_transacao: quando a transação realmente ocorreu
    data_registro          DATE           DEFAULT CURRENT_DATE,
    data_transacao         DATE           NOT NULL CHECK (data_transacao <= CURRENT_DATE),
    modo_aquisicao         TEXT           NOT NULL,
    origem_id              UUID           REFERENCES programs(id),
    destino_id             UUID           NOT NULL REFERENCES programs(id),
    companhia_referencia_id UUID          NOT NULL REFERENCES programs(id),
    milhas_base            INTEGER        NOT NULL,
    bonus_percent          NUMERIC(5, 2)  DEFAULT 0,
    milhas_creditadas      INTEGER        NOT NULL,
    custo_total            NUMERIC(15, 2) NOT NULL,
    cpm_sem_bonus NUMERIC(15, 2) GENERATED ALWAYS AS (
        CASE WHEN milhas_base > 0 THEN (custo_total / milhas_base) * 1000 ELSE 0 END
    ) STORED,
    cpm_real               NUMERIC(15, 2) NOT NULL,
    promocao_inicio        DATE,
    promocao_fim           DATE,
    descricao              TEXT,           -- descrição automática gerada pelo sistema
    observacao             TEXT,           -- observação opcional fornecida pelo usuário
    subscription_id        UUID           REFERENCES subscriptions(id) ON DELETE SET NULL,
    created_at             TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at             TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 6. transaction_batches
CREATE TABLE IF NOT EXISTS transaction_batches (
    id             UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID           NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tipo           TEXT           CHECK (tipo IN ('ORGANICO', 'PAGO')),
    milhas_qtd     INTEGER        NOT NULL,
    cpm_origem     NUMERIC(15, 2) NOT NULL,
    custo_parcial  NUMERIC(15, 2) NOT NULL,
    ordem          INTEGER        DEFAULT 1
);

-- 7. balances (cache de saldo por conta/programa)
CREATE TABLE IF NOT EXISTS balances (
    account_id          UUID           NOT NULL REFERENCES accounts(id),
    programa_id         UUID           NOT NULL REFERENCES programs(id),
    milhas_disponiveis  INTEGER        DEFAULT 0,
    custo_total_estoque NUMERIC(15, 2) DEFAULT 0.00,
    cpm_medio           NUMERIC(15, 2) DEFAULT 0.00,
    updated_at          TIMESTAMPTZ    DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    PRIMARY KEY (account_id, programa_id)
);

-- 8. issuances (emissões de passagens)
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

-- --------------------------------------------------------
-- TRIGGERS
-- --------------------------------------------------------

CREATE TRIGGER update_transactions_modtime
    BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_issuances_modtime
    BEFORE UPDATE ON issuances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Desativa subscription automaticamente quando data_fim é preenchida
CREATE TRIGGER trg_maintain_consistency
    BEFORE INSERT OR UPDATE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION fn_auto_disable_subscription();

-- --------------------------------------------------------
-- ÍNDICES
-- --------------------------------------------------------

-- accounts
CREATE UNIQUE INDEX IF NOT EXISTS accounts_cpf_key ON accounts(cpf);

-- programs
CREATE UNIQUE INDEX IF NOT EXISTS programs_nome_key ON programs(nome);

-- cpf_slots
CREATE INDEX IF NOT EXISTS idx_cpf_slots_account_id  ON cpf_slots(account_id);
CREATE INDEX IF NOT EXISTS idx_cpf_slots_programa_id ON cpf_slots(programa_id);

-- subscriptions
CREATE INDEX IF NOT EXISTS idx_subs_account          ON subscriptions(account_id);
CREATE INDEX IF NOT EXISTS idx_subs_programa         ON subscriptions(programa_id);
CREATE INDEX IF NOT EXISTS idx_subs_renovacao        ON subscriptions(data_renovacao);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_unique_active ON subscriptions (account_id, programa_id) WHERE ativo = TRUE;

-- transactions
CREATE INDEX IF NOT EXISTS idx_transactions_account_id             ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_transactions_origem_id              ON transactions(origem_id);
CREATE INDEX IF NOT EXISTS idx_transactions_destino_id             ON transactions(destino_id);
CREATE INDEX IF NOT EXISTS idx_transactions_companhia_referencia_id ON transactions(companhia_referencia_id);
CREATE INDEX IF NOT EXISTS idx_transactions_subscription_id        ON transactions(subscription_id);

-- transaction_batches
CREATE INDEX IF NOT EXISTS idx_transaction_batches_transaction_id ON transaction_batches(transaction_id);

-- balances
CREATE INDEX IF NOT EXISTS idx_balances_programa_id ON balances(programa_id);

-- issuances
CREATE INDEX IF NOT EXISTS idx_issuances_account_id  ON issuances(account_id);
CREATE INDEX IF NOT EXISTS idx_issuances_programa_id ON issuances(programa_id);

-- --------------------------------------------------------
-- RLS (Row Level Security)
-- --------------------------------------------------------

ALTER TABLE accounts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE programs           ENABLE ROW LEVEL SECURITY;
ALTER TABLE cpf_slots          ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE balances           ENABLE ROW LEVEL SECURITY;
ALTER TABLE issuances          ENABLE ROW LEVEL SECURITY;

-- --------------------------------------------------------
-- COMENTÁRIOS
-- --------------------------------------------------------

COMMENT ON COLUMN transactions.data_registro  IS 'Data em que a transação foi registrada no sistema';
COMMENT ON COLUMN transactions.data_transacao IS 'Data em que a transação realmente ocorreu';
COMMENT ON COLUMN transactions.descricao      IS 'Descrição automática gerada pelo sistema';
COMMENT ON COLUMN transactions.observacao     IS 'Observação opcional fornecida pelo usuário';
COMMENT ON COLUMN transactions.subscription_id IS 'Rastreia se a milha veio de um Clube. NULL = transação avulsa';

COMMENT ON TABLE  subscriptions IS 'Contratos de recorrência (Clubes de milhas). CPM calculado automaticamente.';
COMMENT ON COLUMN subscriptions.cpm_fixo               IS 'Coluna CALCULADA (gerada). Imutável manualmente.';
COMMENT ON COLUMN subscriptions.valor_total_ciclo      IS 'Custo total pago no ciclo.';
COMMENT ON COLUMN subscriptions.milhas_garantidas_ciclo IS 'Total de milhas garantidas no ciclo.';
COMMENT ON COLUMN subscriptions.data_renovacao         IS 'Data da próxima renovação ou débito.';
