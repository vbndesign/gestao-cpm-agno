# Gestão CPM — Agno

Agente de IA conversacional via **Slack** para gerenciar contas de milhas aéreas e calcular o **CPM (Custo Por Mil milhas)** de cada transação.

## Visão Geral

O agente atua como um gerente operacional que permite:

- Cadastrar contas de clientes (com CPF válido obrigatório)
- Registrar compras, transferências e movimentações de milhas
- Gerenciar assinaturas de clubes com CPM fixo e crédito mensal automático
- Corrigir ou desfazer o último lançamento
- Consultar saldos e CPM médio por conta/programa

## Stack

| Camada | Tecnologia |
|---|---|
| Agente | [agno](https://github.com/agno-agi/agno) |
| API | FastAPI + Uvicorn |
| Banco | PostgreSQL (Supabase) |
| Memória | agno `PostgresDb` (sessões por thread/DM) |
| Chat | Slack (DMs + Threads) |
| Deploy | Render |
| LLM | OpenAI GPT-4o-mini |

## Estrutura

```
app/
├── agents/         # Definição do agente e instruções
├── config/         # Configuração centralizada (Pydantic Settings)
├── core/           # Database pool e logging
├── data/           # Schema SQL e migrations versionadas
├── scripts/        # Scripts utilitários
└── tools/          # Ferramentas do agente (DB, calculadoras, parser de datas)
```

## Configuração

Crie um arquivo `.env` com as variáveis abaixo:

```env
APP_ENV=dev
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

## Executando localmente

```bash
uv run uvicorn app.main:app --reload
```

## Histórico de Evolução

Consulte o [CHANGELOG.md](CHANGELOG.md) para um relatório completo da evolução do sistema por fase e commit.
