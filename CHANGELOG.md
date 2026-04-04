# Changelog — WF Milhas · Gerente de CPM

> Relatório completo da evolução do sistema, gerado a partir do histórico de commits.
> O projeto é um agente de IA conversacional (via Slack) que gerencia contas de milhas aéreas, calculando e rastreando o CPM (Custo Por Milha/Mil) de cada transação.

---

## [Fase 7] Robustez, Segurança e Observabilidade — Fev/2026 (22–23)

### 2026-02-23 · Consolidação final de robustez e segurança
**Commit:** `2585a7e` — *Robustez, observabilidade e correções de segurança no agente*

- **Logging estruturado em JSON** para ambientes de produção; `_sanitize_error` oculta dados internos nos erros expostos.
- Decorator `@log_tool_call` aplicado em todas as ferramentas: registra duração, desfecho e rastreabilidade de cada chamada.
- `correct_last_subscription`: operação tornada atômica com preservação completa de histórico.
- `delete_last_transaction`: fluxo dividido em **preview** + `confirm_delete_transaction(id)` para exigir confirmação explícita antes de qualquer deleção.
- `process_monthly_credit`: adicionados `FOR UPDATE` + `ORDER BY` para eliminar _race condition_ em créditos mensais simultâneos.
- **Índice único parcial** em `subscriptions WHERE ativo = TRUE`: impede duplicidade de assinaturas ativas para o mesmo clube/conta.
- **Remoção de tabelas não utilizadas**: `balances`, `cpf_slots`, `issuances`.
- `debug_mode` desativado automaticamente em produção (`APP_ENV=prod`).

---

### 2026-02-23 · Ajuste de prompts
**Commit:** `e0b608d` — *Ajustes nos prompts para as últimas alterações no código*

- Instruções do agente atualizadas para refletir os novos fluxos de deleção com confirmação e correção de assinaturas.

---

### 2026-02-23 · Barreira de confirmação para deleção
**Commit:** `7f4cac4` — *Para deletar uma transação existe uma barreira no código para haver uma confirmação seguida da exclusão*

- Introdução do fluxo em dois passos: `delete_last_transaction` retorna um preview; apenas `confirm_delete_transaction(id)` efetiva a deleção.

---

### 2026-02-23 · Migration de limpeza do banco
**Commit:** `ee32d4a` — *Migration para excluir tabelas não usadas e pareamento das bases dev e prod*

- Tabelas obsoletas removidas do banco.
- Bases de desenvolvimento e produção sincronizadas.

---

### 2026-02-23 · Sistema de migrations
**Commit:** `fcdd304` — *Mini sistema de migrations com regras definidas no schema_pg.sql e registro no Supabase*

- Criação da tabela `schema_migrations` para rastrear versões aplicadas.
- Convenção de nomenclatura definida: `YYYYMMDD_NNN_descricao.sql` com `_rollback.sql` associado.
- Cada migration registra sua própria aplicação via `INSERT INTO schema_migrations ... ON CONFLICT DO NOTHING`.

---

### 2026-02-23 · Prevenção de assinaturas duplicadas
**Commit:** `eef8539` — *Correção para impossibilitar a criação de 2 assinaturas ativas para o mesmo clube*

- Constraint + índice único parcial garantem apenas uma assinatura ativa por `(account_id, programa_id)`.

---

### 2026-02-23 · Correção de excesso de milhas creditadas
**Commit:** `28e7d86` — *Correção de risco de excesso de milhas creditadas*

- Controle transacional para evitar créditos duplicados ou excessivos no processamento mensal.

---

### 2026-02-23 · Histórico de assinaturas corrigidas
**Commit:** `0da203a` — *Ajuste na correção de assinaturas para criar um histórico e atualizar as transferências para a nova assinatura*

- `correct_last_subscription` agora desativa a assinatura anterior (preservando histórico) e re-vincula transações existentes à nova assinatura criada.

---

### 2026-02-22/23 · Logging e segurança de erros
**Commit:** `0b31deb` — *Não exposição de erros com dados dos usuários pelo Slack; rastreamento do código de erro retornado*

- Mensagens de erro enviadas ao Slack passam por sanitização: dados de usuários nunca aparecem nas respostas.
- O `session_id` é exposto como código de rastreamento para suporte.

**Commit:** `d05a97c` — *Debug mode em dev; log JSON para dashboard do Render*

- Log em formato JSON estruturado integrado ao dashboard do Render.
- `debug_mode` restrito ao ambiente `dev`.

---

## [Fase 6] Ajustes Operacionais e Organização do Banco — Fev/2026 (21)

### 2026-02-21 · Remoção do benchmark
**Commit:** `6f1fd92` — *Ajustes para a exclusão completa do benchmark*

- Ferramenta e tabela de benchmark removidas do sistema (funcionalidade descontinuada).

---

### 2026-02-21 · Reorganização de dados e schema (Model B)
**Commit:** `f40dafa` — *chore: reorganize data structure and update schema (Model B)*

- `schema_pg.sql` atualizado para refletir o estado DEV/PROD com 8 tabelas, índices, triggers e políticas RLS.
- Arquivos de migration movidos para `app/data/migrations/prod/`.
- Novas migrations de PROD documentadas:
  - `migration_prod_sync_transactions.sql`
  - `migration_prod_add_subscriptions.sql`
  - `migration_prod_remove_benchmark.sql`
- `.gitignore` atualizado: scripts MCP e `mcp.json` excluídos do versionamento.

---

### 2026-02-21 · MCP read-only conectado ao Supabase de desenvolvimento
**Commit:** `af0e51a` — *MCP Read-only conectado ao Supabase de desenvolvimento*

- Integração MCP (Model Context Protocol) somente leitura para consultas diretas ao banco de desenvolvimento.

---

### 2026-02-21 · Deleção da última transação
**Commit:** `a17c727` — *Agora é possível deletar a última transação para corrigir a entrada de dados*

- Nova ferramenta `delete_last_transaction`: permite ao agente desfazer o último lançamento de uma conta/programa específicos.

---

### 2026-02-21 · Validação obrigatória de CPF no cadastro
**Commit:** `942544d` — *Ajustes no registro de novas contas com CPF válido obrigatório*

- Validação de CPF reforçada: campo obrigatório com 11 dígitos; CPF inválido impede a criação da conta.

---

## [Fase 5] Assinaturas e Datas Retroativas — Fev/2026 (07)

### 2026-02-07 · Anualização automática de assinaturas mensais
**Commit:** `2cfab0b` — *Adiciona suporte a assinaturas mensais com anualização automática*

- Parâmetro `is_mensal=True` instrui o sistema a multiplicar os valores mensais por 12 automaticamente.
- Impede erros de CPM causados por confundir ciclo mensal com anual.

---

### 2026-02-07 · Gestão completa de assinaturas e créditos mensais
**Commit:** `e3f2138` — *Adiciona gestão completa de assinaturas com créditos mensais controlados, transações intra-clube e protocolo de roteamento de cenários para o agente*

- Nova tabela `subscriptions` com CPM fixo calculado automaticamente (coluna gerada no banco).
- Ferramenta `process_monthly_credit`: crédita mensalidade de clube preservando o CPM contratado.
- Ferramenta `register_intra_club_transaction`: registra transações avulsas dentro do clube com rastreio da origem.
- Ferramenta `correct_last_subscription`: corrige dados de assinatura mantendo o vínculo com transações anteriores.
- **Protocolo de roteamento de cenários** adicionado às instruções do agente:
  - Cenário A: Mensalidade → `process_monthly_credit`
  - Cenário B: Transação avulsa no clube → `register_intra_club_transaction`
  - Cenário C: Transação externa → `save_simple_transaction`

---

### 2026-02-07 · Parser de datas PT-BR e tabela de assinaturas inicial
**Commit:** `fc5061c` — *Adiciona datas retroativas com parser PT-BR, tabela de assinaturas com CPM fixo*

- Parser de linguagem natural em português para datas: aceita `"ontem"`, `"dia 15"`, `"15 de jan"`, `"daqui a 1 ano"` etc.

---

### 2026-02-07 · Separação entre data de registro e data da transação
**Commit:** `f92c4db` — *Adiciona suporte a datas retroativas; separa data_transacao de data_registro no banco*

- Banco de dados passa a ter dois campos de data:
  - `data_registro`: quando o lançamento foi feito no sistema.
  - `data_transacao`: quando a transação realmente ocorreu (pode ser retroativa).

---

## [Fase 4] Qualidade e Correções — Jan/2026

### 2026-01-17 · Busca por UUID e correções de banco
**Commit:** `65f7989` — *Adiciona busca de contas por UUID (com/sem hífens), corrige erro DuplicatePreparedStatement*

- Contas podem ser buscadas por UUID completo (com ou sem hífens).
- Correção do erro `DuplicatePreparedStatement`: INSERTs passam a usar `prepare=False`.
- Separação definitiva entre `descricao` (gerada automaticamente pelo sistema) e `observacao` (opcional, inserida pelo usuário).

---

### 2026-01-09 · Centralização de enums e validação SQL
**Commit:** `6b29e7a` — *Refatora enums para centralização, melhora validação SQL e adiciona utilitário para escapar senhas de banco*

- Enums centralizados em módulo dedicado (evita divergências entre tools).
- Validação SQL aprimorada para evitar injeção ou erros de tipo.
- Utilitário de escape seguro para senhas de banco de dados.

---

## [Fase 3] Infraestrutura de Produção — Dez/2025

### 2025-12-06 · Salvamento de user_id na sessão
**Commit:** `f34a95e` — *Salvando user_id na sessão do agente*

- `user_id` do Slack persistido na sessão do agente para rastreabilidade por usuário.

---

### 2025-12-06 · Memória híbrida com suporte a Threads no Slack
**Commit:** `a4cd068` — *feat(slack): implementa memória híbrida com suporte a Threads*

- **Canais públicos**: bot responde criando Threads automaticamente (`session_id = thread_ts`).
- **DMs**: histórico pessoal e contínuo por usuário (`session_id = dm_user_id`).
- **Threads existentes**: memória compartilhada por todos os participantes da thread.

---

### 2025-12-06 · Connection pool e configuração centralizada
**Commit:** `50bb93b` — *refactor: implementação connection pool e config centralizada*

- `app/config/settings.py`: configuração centralizada via **Pydantic Settings** (lê variáveis de ambiente).
- `app/core/database.py`: Singleton com **Connection Pool** para reúso de conexões PostgreSQL.
- `main.py` refatorado com `lifespan` (FastAPI): pool inicializado no startup, fechado no shutdown.
- Modelo corrigido para `gpt-4o-mini`.

---

### 2025-12-05 · Configuração de deploy no Render
**Commits:** `92e07773`, `e8596c2a` — *Porta dinâmica e configurações do Render*

- Porta lida dinamicamente da variável de ambiente `PORT` (obrigatório no Render).
- `pyproject.toml` ajustado para `uv run` com porta correta.

---

### 2025-12-05 · Agente funcionando no Slack
**Commit:** `3e7db65` — *Agente funcionando no Slack e usando o Ngrok*

- Endpoint `POST /slack/events` implementado no FastAPI.
- Validação de assinatura Slack (`X-Slack-Signature`).
- Reações visuais: 👀 durante processamento, ✅ ao concluir.
- Tratamento de retries do Slack (ignora `X-Slack-Retry-Num`).
- Teste local via **Ngrok**.

---

### 2025-12-05 · Migração completa: SQLite → PostgreSQL no Supabase
**Commit:** `25b3386` — *Migração completa do banco de dados SQLite para Postgres no Supabase*

- Banco de dados movido de SQLite local para **PostgreSQL gerenciado no Supabase**.
- Row Level Security (RLS) ativado em todas as tabelas.
- Schema com triggers de `updated_at` automático.

---

## [Fase 2] Agente Único com Tools Especializadas — Nov/2025

### 2025-12-01 · Atualização do agente e libs para o Supabase
**Commit:** `5f4ccf6` — *Update no agente milhas e inserção das libs para migrar o DB para o Supabase*

- Dependências de PostgreSQL (asyncpg, psycopg2) adicionadas.
- Agente preparado para conectar ao banco remoto.

---

### 2025-11-30 · Correção para transações complexas
**Commit:** `0d40ccdf` — *Ajuste para o agente salvar as transações complexas*

- Bugs de mapeamento de parâmetros corrigidos para transações com lotes mistos.

---

### 2025-11-30 · Suporte a transações complexas (milhas orgânicas + lotes pagos)
**Commit:** `01a6395` — *Evolução do agente para salvar transações complexas envolvendo milhas orgânicas e lotes*

- Nova ferramenta `save_complex_transfer`: suporte a transferências bonificadas compostas de lotes orgânicos e pagos.
- Tabela `transaction_batches` criada para detalhar a composição de cada transferência.
- Validação interna: `lote_organico_qtd + lote_pago_qtd` deve ser igual a `milhas_base`.

---

### 2025-11-30 · Refatoração para agente único
**Commit:** `d50422443` — *Atualização para um único agente que conecta as tools dependendo do contexto do input*

- Arquitetura consolidada: **um agente central** com múltiplas tools chamadas conforme contexto.
- Eliminação da lentidão causada pelo sistema multi-agente.

---

### 2025-11-30 · Sistema multi-agente (descontinuado)
**Commit:** `791a13f` — *Sistema inicial de multiagente (tornou a execução muito lenta)*

- Experimento inicial com múltiplos sub-agentes especializados.
- Descontinuado por baixa performance; substituído pelo modelo de agente único com tools.

---

## [Fase 1] Fundação — Nov/2025

### 2025-11-23 · Agente lendo e escrevendo no banco via tools
**Commit:** `dc4e2b2` — *Agente salvando e lendo dados no banco através das tools*

- Integração completa entre o agente agno e as ferramentas de banco de dados.
- Fluxo end-to-end: pergunta do usuário → tool call → resposta com dados reais.

---

### 2025-11-22 · Banco de dados criado e populado
**Commit:** `7520ee1` — *Banco de dados criado e populado com o script seed_database.py; versão rodando no agentUI*

- Schema SQLite inicial com tabelas: `accounts`, `programs`, `transactions`.
- Script `seed_database.py` para popular dados de teste.
- Interface web via **agentUI** rodando localmente.

---

### 2025-11-22 · Commit inicial
**Commit:** `8efd0f8` — *Primeiro commit com a estrutura inicial do projeto*

- Estrutura base do projeto com **agno** (framework de agentes de IA).
- Dependências instaladas via `uv`.
- Interface frontend **agentUI** rodando.

---

## Resumo Técnico da Evolução

| Aspecto | Estado Inicial (Nov/2025) | Estado Atual (Fev/2026) |
|---|---|---|
| **Banco de dados** | SQLite local | PostgreSQL (Supabase) com RLS e migrations |
| **Interface** | agentUI web local | Slack (DMs + Threads) |
| **Agente** | Único, simples | Único com 8+ tools especializadas |
| **Memória** | Sem persistência | Híbrida: por thread ou por usuário DM |
| **Deploy** | Local (Ngrok) | Render (porta dinâmica, connection pool) |
| **Transações** | Simples (1 programa) | Complexas (lotes mistos, orgânico + pago) |
| **Assinaturas** | Não existia | Clubes com CPM fixo, crédito mensal, anualização |
| **Datas** | Apenas data atual | Retroativas com parser PT-BR |
| **Segurança** | Básica | Sanitização de erros, índice único parcial, FOR UPDATE |
| **Observabilidade** | Print/debug | Logging JSON estruturado, `@log_tool_call` em todas as tools |
| **Migrations** | Manual (ad hoc) | Sistema versionado com rollback documentado |
