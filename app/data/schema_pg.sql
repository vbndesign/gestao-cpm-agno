-- ========================================================
-- SCHEMA POSTGRESQL - WF MILHAS (v1.0 Cloud)
-- ========================================================

-- Define o fuso horário padrão da sessão para garantir
SET timezone = 'America/Sao_Paulo';

-- 1. FUNÇÃO PARA ATUALIZAR TIMESTAMP (TRIGGER)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW() AT TIME ZONE 'America/Sao_Paulo';
   RETURN NEW;
END;
$$ language 'plpgsql';

-- 2. CADASTROS BASE
CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cpf TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL,
    tipo_gestao TEXT CHECK(tipo_gestao IN ('PROPRIA', 'CLIENTE')) DEFAULT 'CLIENTE',
    status TEXT DEFAULT 'ATIVO',
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

CREATE TABLE IF NOT EXISTS programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL, -- CIA_AEREA, BANCO, OPERADORA
    benchmark_atual NUMERIC(10, 2) DEFAULT 0.00,
    ativo BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 3. EXTENSÕES
CREATE TABLE IF NOT EXISTS cpf_slots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    programa_id UUID NOT NULL REFERENCES programs(id),
    slots_totais INTEGER DEFAULT 25,
    slots_usados INTEGER DEFAULT 0,
    data_reset DATE,
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 4. CORE: TRANSAÇÕES
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    data_registro DATE DEFAULT CURRENT_DATE,
    
    modo_aquisicao TEXT NOT NULL, 
    origem_id UUID REFERENCES programs(id),
    destino_id UUID NOT NULL REFERENCES programs(id),
    companhia_referencia_id UUID NOT NULL REFERENCES programs(id),
    
    milhas_base INTEGER NOT NULL,
    bonus_percent NUMERIC(5, 2) DEFAULT 0,
    milhas_creditadas INTEGER NOT NULL,
    custo_total NUMERIC(15, 2) NOT NULL,
    
    -- Colunas Geradas (STORED no Postgres)
    cpm_sem_bonus NUMERIC(15, 2) GENERATED ALWAYS AS (
        CASE WHEN milhas_base > 0 THEN (custo_total / milhas_base) * 1000 ELSE 0 END
    ) STORED,
    
    cpm_real NUMERIC(15, 2) NOT NULL,
    
    promocao_inicio DATE,
    promocao_fim DATE,
    descricao TEXT,
    
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- Trigger Transaction
CREATE TRIGGER update_transactions_modtime
    BEFORE UPDATE ON transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Tabela de Lotes
CREATE TABLE IF NOT EXISTS transaction_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tipo TEXT CHECK(tipo IN ('ORGANICO', 'PAGO')),
    milhas_qtd INTEGER NOT NULL,
    cpm_origem NUMERIC(15, 2) NOT NULL,
    custo_parcial NUMERIC(15, 2) NOT NULL,
    ordem INTEGER DEFAULT 1
);

-- 5. SALDOS (Cache)
CREATE TABLE IF NOT EXISTS balances (
    account_id UUID NOT NULL REFERENCES accounts(id),
    programa_id UUID NOT NULL REFERENCES programs(id),
    milhas_disponiveis INTEGER DEFAULT 0,
    custo_total_estoque NUMERIC(15, 2) DEFAULT 0.00,
    cpm_medio NUMERIC(15, 2) DEFAULT 0.00,
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    PRIMARY KEY (account_id, programa_id)
);

-- 6. HISTÓRICO BENCHMARK
CREATE TABLE IF NOT EXISTS benchmark_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    programa_id UUID NOT NULL REFERENCES programs(id),
    valor_cpm NUMERIC(10, 2) NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE,
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- 7. SAÍDAS (EMISSÕES)
CREATE TABLE IF NOT EXISTS issuances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id),
    programa_id UUID NOT NULL REFERENCES programs(id),
    data_emissao DATE DEFAULT CURRENT_DATE,
    passageiro_nome TEXT NOT NULL,
    passageiro_cpf TEXT, 
    localizador TEXT,
    milhas_utilizadas INTEGER NOT NULL,
    cpm_medio_momento NUMERIC(15, 2) NOT NULL,
    custo_venda NUMERIC(15, 2) NOT NULL,
    valor_venda NUMERIC(15, 2) NOT NULL,
    
    lucro_bruto NUMERIC(15, 2) GENERATED ALWAYS AS (valor_venda - custo_venda) STORED,
    margem_percent NUMERIC(5, 2) GENERATED ALWAYS AS (
        CASE WHEN valor_venda > 0 THEN (valor_venda - custo_venda)/valor_venda*100 ELSE 0 END
    ) STORED,
    
    status TEXT CHECK(status IN ('EMITIDA', 'VOADA', 'CANCELADA')) DEFAULT 'EMITIDA',
    
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo')
);

-- Trigger Issuances
CREATE TRIGGER update_issuances_modtime
    BEFORE UPDATE ON issuances
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();