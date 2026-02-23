-- ============================================================
-- MIGRATION: Criar tabela subscriptions no PROD + subscription_id em transactions
-- Data: 2026-02-21
-- Descrição: Traz para o PROD a feature de assinaturas/clubes já presente no DEV.
--            ⚠️ NÃO faz DROP da tabela — seguro para produção.
-- ============================================================

-- 1. Criar tabela de assinaturas (somente se não existir)
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    programa_id             UUID NOT NULL REFERENCES programs(id),

    -- Configuração do plano
    valor_total_ciclo       NUMERIC(10, 2) NOT NULL CHECK (valor_total_ciclo > 0),
    milhas_garantidas_ciclo INTEGER        NOT NULL CHECK (milhas_garantidas_ciclo > 0),

    -- CPM calculado automaticamente (coluna gerada, imutável)
    cpm_fixo NUMERIC(10, 2) GENERATED ALWAYS AS (
        (valor_total_ciclo / milhas_garantidas_ciclo::NUMERIC) * 1000
    ) STORED,

    -- Gestão de datas e status
    data_inicio    DATE    NOT NULL DEFAULT CURRENT_DATE,
    data_renovacao DATE    NOT NULL,
    data_fim       DATE,
    ativo          BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Integridade temporal
    CONSTRAINT chk_subs_fluxo_tempo CHECK (data_renovacao >= data_inicio),
    CONSTRAINT chk_subs_fim_futuro  CHECK (data_fim IS NULL OR data_fim >= data_inicio),

    -- Consistência de status: ativo=TRUE implica data_fim=NULL
    CONSTRAINT chk_subs_status_coerente CHECK (
        (ativo = FALSE) OR (data_fim IS NULL)
    )
);

-- 2. Função e trigger para manter consistência automática
CREATE OR REPLACE FUNCTION fn_auto_disable_subscription()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.data_fim IS NOT NULL THEN
        NEW.ativo := FALSE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_maintain_consistency ON subscriptions;
CREATE TRIGGER trg_maintain_consistency
BEFORE INSERT OR UPDATE ON subscriptions
FOR EACH ROW EXECUTE FUNCTION fn_auto_disable_subscription();

-- 3. Índices
CREATE INDEX IF NOT EXISTS idx_subs_account    ON subscriptions(account_id);
CREATE INDEX IF NOT EXISTS idx_subs_renovacao  ON subscriptions(data_renovacao);
CREATE INDEX IF NOT EXISTS idx_subs_programa   ON subscriptions(programa_id);

-- 4. Comentários
COMMENT ON TABLE subscriptions IS 'Contratos de recorrência (Clubes de milhas). CPM calculado automaticamente.';
COMMENT ON COLUMN subscriptions.cpm_fixo              IS 'Coluna CALCULADA (gerada). Imutável manualmente.';
COMMENT ON COLUMN subscriptions.valor_total_ciclo     IS 'Custo total pago no ciclo (mensal/anual).';
COMMENT ON COLUMN subscriptions.milhas_garantidas_ciclo IS 'Total de milhas garantidas no ciclo.';
COMMENT ON COLUMN subscriptions.data_renovacao        IS 'Data da próxima renovação ou débito.';

-- 5. RLS
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

-- 6. Adicionar subscription_id em transactions (FK para rastreio de origem clube)
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS subscription_id UUID REFERENCES subscriptions(id) ON DELETE SET NULL;

COMMENT ON COLUMN transactions.subscription_id IS 'Rastreia se a milha veio de um Clube (subscription). NULL = transação avulsa.';

-- Verificação final
SELECT
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'subscriptions') AS tabela_subscriptions_existe,
    (SELECT COUNT(*) FROM information_schema.columns
     WHERE table_name = 'transactions' AND column_name = 'subscription_id') AS coluna_subscription_id_existe;
