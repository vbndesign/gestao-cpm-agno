-- ⚠️ ATENÇÃO: Se já criou a tabela antes, o ideal é dropar para recriar com a estrutura limpa nesta fase de DEV.
DROP TABLE IF EXISTS subscriptions CASCADE;

-- 1. Criação da Tabela de Assinaturas (Nível Enterprise)
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    programa_id UUID NOT NULL REFERENCES programs(id),
    
    -- Configuração do Plano
    periodicidade VARCHAR(20) NOT NULL CHECK (periodicidade IN ('MENSAL', 'ANUAL')),
    valor_total_ciclo NUMERIC(10, 2) NOT NULL CHECK (valor_total_ciclo > 0),
    milhas_garantidas_ciclo INTEGER NOT NULL CHECK (milhas_garantidas_ciclo > 0),
    
    -- CPM Automático (Coluna Gerada - Matemática Inviolável)
    cpm_fixo NUMERIC(10, 2) GENERATED ALWAYS AS (
        (valor_total_ciclo / milhas_garantidas_ciclo::NUMERIC) * 1000
    ) STORED,
    
    -- Gestão de Datas e Status
    data_inicio DATE NOT NULL DEFAULT CURRENT_DATE,
    data_renovacao DATE NOT NULL,
    data_fim DATE, 
    ativo BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- 🛡️ CONSTRAINTS DE INTEGRIDADE (O "Cinto de Segurança") --

    -- 1. Lógica Temporal: A renovação não pode ser antes do início. O fim não pode ser antes do início.
    CONSTRAINT check_fluxo_tempo CHECK (data_renovacao >= data_inicio),
    CONSTRAINT check_fim_futuro CHECK (data_fim IS NULL OR data_fim >= data_inicio),

    -- 2. Consistência de Status (Sua sugestão vital):
    -- "Se está ATIVO, data_fim TEM que ser NULL".
    -- "Se tem data_fim, ATIVO TEM que ser FALSE".
    CONSTRAINT check_status_coerente CHECK (
        (ativo = FALSE) OR (data_fim IS NULL)
    )
);

-- 2. Trigger de "UX do Banco"
-- Se alguém preencher data_fim, o banco desativa automaticamente para satisfazer a constraint acima.
CREATE OR REPLACE FUNCTION fn_auto_disable_subscription()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.data_fim IS NOT NULL THEN
        NEW.ativo := FALSE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_maintain_consistency
BEFORE INSERT OR UPDATE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION fn_auto_disable_subscription();

-- 3. Índices
CREATE INDEX idx_subs_account ON subscriptions(account_id);
CREATE INDEX idx_subs_renovacao ON subscriptions(data_renovacao); -- Útil para buscar o que vence logo

-- 4. Documentação
COMMENT ON TABLE subscriptions IS 'Contratos de recorrência (Clubes). CPM é calculado automaticamente.';
COMMENT ON COLUMN subscriptions.periodicidade IS 'MENSAL ou ANUAL. Define a frequência do débito/bônus.';
COMMENT ON COLUMN subscriptions.cpm_fixo IS 'Coluna CALCULADA. Impossível editar manualmente.';

-- 5. Alteração Defensiva na Transactions
DO $$
BEGIN
    -- Só tenta adicionar a coluna se a tabela transactions existir
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'transactions') THEN
        ALTER TABLE transactions 
        ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL;
        
        COMMENT ON COLUMN transactions.subscription_id IS 'Rastreia se a milha veio de um Clube.';
    END IF;
END $$;