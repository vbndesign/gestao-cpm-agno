-- ========================================================
-- SCHEMA DE DADOS WF MILHAS (v2.3 - Timezone Fix)
-- ========================================================
--
-- [DEPLOYMENT NOTES / NOTAS DE DEPLOY]
-- Para que o comando (datetime('now', 'localtime')) funcione 
-- corretamente mostrando o horário de Brasília em servidores 
-- Linux/Render (que usam UTC por padrão), você DEVE configurar:
--
-- Variável de Ambiente (Environment Variable):
-- Key:   TZ
-- Value: America/Sao_Paulo
--
-- Sem isso, o 'localtime' continuará sendo UTC (+3h de diferença).
-- ========================================================

PRAGMA foreign_keys = ON;

-- 1. CADASTROS BASE
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    cpf TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL,
    tipo_gestao TEXT CHECK(tipo_gestao IN ('PROPRIA', 'CLIENTE')) DEFAULT 'CLIENTE',
    status TEXT DEFAULT 'ATIVO',
    created_at DATETIME DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS programs (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL,
    benchmark_atual REAL DEFAULT 0.0,
    ativo BOOLEAN DEFAULT 1,
    updated_at DATETIME DEFAULT (datetime('now', 'localtime'))
);

-- 2. EXTENSÕES
CREATE TABLE IF NOT EXISTS cpf_slots (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    programa_id TEXT NOT NULL,
    slots_totais INTEGER DEFAULT 25,
    slots_usados INTEGER DEFAULT 0,
    data_reset DATE,
    updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 3. CORE: TRANSAÇÕES
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    data_registro DATE DEFAULT CURRENT_DATE, 
    
    modo_aquisicao TEXT NOT NULL, 
    origem_id TEXT,
    destino_id TEXT NOT NULL,
    companhia_referencia_id TEXT NOT NULL,
    
    milhas_base INTEGER NOT NULL,
    bonus_percent REAL DEFAULT 0,
    milhas_creditadas INTEGER NOT NULL,
    custo_total REAL NOT NULL,
    
    cpm_sem_bonus REAL GENERATED ALWAYS AS (CASE WHEN milhas_base > 0 THEN (custo_total / milhas_base) * 1000 ELSE 0 END) VIRTUAL,
    cpm_real REAL NOT NULL,
    
    promocao_inicio DATE,
    promocao_fim DATE,
    descricao TEXT,
    
    created_at DATETIME DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
    
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(origem_id) REFERENCES programs(id),
    FOREIGN KEY(destino_id) REFERENCES programs(id),
    FOREIGN KEY(companhia_referencia_id) REFERENCES programs(id)
);

CREATE TRIGGER IF NOT EXISTS update_transactions_timestamp 
AFTER UPDATE ON transactions
BEGIN
    UPDATE transactions SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;

-- Tabela de Lotes
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

-- 4. SALDOS
CREATE TABLE IF NOT EXISTS balances (
    account_id TEXT NOT NULL,
    programa_id TEXT NOT NULL,
    milhas_disponiveis INTEGER DEFAULT 0,
    custo_total_estoque REAL DEFAULT 0.0,
    cpm_medio REAL DEFAULT 0.0,
    updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (account_id, programa_id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 5. HISTÓRICO BENCHMARK
CREATE TABLE IF NOT EXISTS benchmark_history (
    id TEXT PRIMARY KEY,
    programa_id TEXT NOT NULL,
    valor_cpm REAL NOT NULL,
    data_inicio DATE NOT NULL,
    data_fim DATE,
    created_at DATETIME DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

-- 6. SAÍDAS (EMISSÕES)
CREATE TABLE IF NOT EXISTS issuances (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    programa_id TEXT NOT NULL,
    data_emissao DATE DEFAULT CURRENT_DATE,
    passageiro_nome TEXT NOT NULL,
    passageiro_cpf TEXT, 
    localizador TEXT,
    milhas_utilizadas INTEGER NOT NULL,
    cpm_medio_momento REAL NOT NULL,
    custo_venda REAL NOT NULL,
    valor_venda REAL NOT NULL,
    
    lucro_bruto REAL GENERATED ALWAYS AS (valor_venda - custo_venda) VIRTUAL,
    margem_percent REAL GENERATED ALWAYS AS (CASE WHEN valor_venda > 0 THEN (valor_venda - custo_venda)/valor_venda*100 ELSE 0 END) VIRTUAL,
    status TEXT CHECK(status IN ('EMITIDA', 'VOADA', 'CANCELADA')) DEFAULT 'EMITIDA',
    
    created_at DATETIME DEFAULT (datetime('now', 'localtime')),
    updated_at DATETIME DEFAULT (datetime('now', 'localtime')),
    
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(programa_id) REFERENCES programs(id)
);

CREATE TRIGGER IF NOT EXISTS update_issuances_timestamp 
AFTER UPDATE ON issuances
BEGIN
    UPDATE issuances SET updated_at = datetime('now', 'localtime') WHERE id = NEW.id;
END;