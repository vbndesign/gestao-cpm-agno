-- ========================================================
-- SCHEMA DE DADOS WF MILHAS (v2.1 - Strict Business Rules)
-- ========================================================

-- Habilitar Foreign Keys no SQLite (Rodar a cada conexão, mas bom documentar)
PRAGMA foreign_keys = ON;

-- 1. CADASTROS BASE
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY, -- UUID
    cpf TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL,
    tipo_gestao TEXT CHECK(tipo_gestao IN ('PROPRIA', 'CLIENTE')) DEFAULT 'CLIENTE',
    status TEXT DEFAULT 'ATIVO',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS programs (
    id TEXT PRIMARY KEY, -- UUID ou Slug (ex: 'azul', 'livelo')
    nome TEXT NOT NULL UNIQUE, -- Azul, Latam, Livelo
    tipo TEXT NOT NULL, -- CIA_AEREA, BANCO, OPERADORA
    benchmark_atual REAL DEFAULT 0.0, -- Cache do valor vigente
    ativo BOOLEAN DEFAULT 1
);

-- 2. EXTENSÕES DE NEGÓCIO
CREATE TABLE IF NOT EXISTS cpf_slots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    programa_id TEXT NOT NULL,
    slots_totais INTEGER DEFAULT 25,
    slots_usados INTEGER DEFAULT 0,
    data_reset DATE,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 3. CORE: TRANSAÇÕES
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    data_registro DATE DEFAULT CURRENT_DATE,
    
    -- Modo de Aquisição (Enum do Python)
    modo_aquisicao TEXT NOT NULL, 
    
    -- Fluxo de Pontos
    origem_id TEXT, -- Pode ser NULL se for Acúmulo Orgânico direto
    destino_id TEXT NOT NULL,
    companhia_referencia_id TEXT NOT NULL, -- [RN: Explicitar referência]
    
    -- Valores Quantitativos
    milhas_base INTEGER NOT NULL,
    bonus_percent REAL DEFAULT 0,
    milhas_creditadas INTEGER NOT NULL,
    
    -- Valores Financeiros
    custo_total REAL NOT NULL,
    
    -- KPIs (Colunas Geradas Automaticamente para Integridade RN02)
    cpm_sem_bonus REAL GENERATED ALWAYS AS (CASE WHEN milhas_base > 0 THEN (custo_total / milhas_base) * 1000 ELSE 0 END) VIRTUAL,
    cpm_real REAL NOT NULL, -- Persistido para performance de leitura
    
    -- Metadados
    promocao_inicio DATE,
    promocao_fim DATE,
    descricao TEXT,
    
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(origem_id) REFERENCES programs(id),
    FOREIGN KEY(destino_id) REFERENCES programs(id),
    FOREIGN KEY(companhia_referencia_id) REFERENCES programs(id)
);

-- A Tabela de Lotes (Resolve o problema de Lote Orgânico + Pago)
CREATE TABLE IF NOT EXISTS transaction_batches (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    tipo TEXT CHECK(tipo IN ('ORGANICO', 'PAGO')),
    milhas_qtd INTEGER NOT NULL,
    cpm_origem REAL NOT NULL,
    custo_parcial REAL NOT NULL,
    ordem INTEGER DEFAULT 1,
    FOREIGN KEY(transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
);

-- 4. CACHE DE SALDOS (Para evitar somar milhões de linhas toda vez)
CREATE TABLE IF NOT EXISTS balances (
    account_id TEXT NOT NULL,
    programa_id TEXT NOT NULL,
    milhas_disponiveis INTEGER DEFAULT 0,
    custo_total_estoque REAL DEFAULT 0.0,
    cpm_medio REAL DEFAULT 0.0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, programa_id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 5. HISTÓRICO DE BENCHMARK (Série Temporal)
CREATE TABLE IF NOT EXISTS benchmark_history (
    id TEXT PRIMARY KEY,
    programa_id TEXT NOT NULL,
    valor_cpm REAL NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE, -- NULL = Vigente
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 6. SAÍDAS (EMISSÕES/VENDAS) - O "Caixa" do sistema
CREATE TABLE IF NOT EXISTS issuances (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL, -- De qual conta saíram as milhas
    programa_id TEXT NOT NULL, -- De qual programa (Latam, Azul, etc)
    data_emissao DATE DEFAULT CURRENT_DATE,
    
    -- Dados do Passageiro (Importante p/ controle de CPF Slots)
    passageiro_nome TEXT NOT NULL,
    passageiro_cpf TEXT, 
    localizador TEXT, -- Código da reserva
    
    -- Financeiro da Venda
    milhas_utilizadas INTEGER NOT NULL,
    cpm_medio_momento REAL NOT NULL, -- Quanto custava a milha (custo de reposição) NA HORA da venda
    custo_venda REAL NOT NULL, -- (milhas * cpm_medio)
    
    valor_venda REAL NOT NULL, -- Por quanto você vendeu a passagem
    
    -- KPIs de Lucro (Calculados automaticamente)
    lucro_bruto REAL GENERATED ALWAYS AS (valor_venda - custo_venda) VIRTUAL,
    margem_percent REAL GENERATED ALWAYS AS (CASE WHEN valor_venda > 0 THEN (valor_venda - custo_venda)/valor_venda*100 ELSE 0 END) VIRTUAL,
    
    status TEXT CHECK(status IN ('EMITIDA', 'VOADA', 'CANCELADA')) DEFAULT 'EMITIDA',
    
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);