# app/agents/milhas_agent.py
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.postgres import PostgresDb

# --- NOVOS IMPORTS DA ARQUITETURA ---
from app.config.settings import settings

# Import das Tools
from app.tools.db_toolkit import DatabaseManager
from app.tools.calculators import calculate_mixed_transfer, calculate_cpm 

# --- CONFIGURAÇÃO DE MEMÓRIA ---
db_url = settings.database_url

# Configura o banco de sessões (Persistência do Chat)
session_db = PostgresDb(
    session_table="agent_sessions",
    db_url=db_url
)

# só ativa o debug mode se estiver em dev
debug_mode = (settings.app_env == "dev")

# Instancia as tools (Agora usando o Pool de Conexões internamente)
db_tool = DatabaseManager()

# --- DEFINIÇÃO DO AGENTE ---
milhas_agent = Agent(
    id="gerente-wf-milhas",
    name="Gerente WF Milhas",
    role="Gestor operacional de contas e milhas aéreas",
    model=OpenAIChat(
        id="gpt-5-mini",                # <--- CORRIGIDO: Modelo válido e barato
        api_key=settings.openai_api_key  # <--- CORRIGIDO: Chave segura via Settings
    ),
    
    # --- PERSISTÊNCIA ---
    db=session_db,
    add_history_to_context=True,    
    num_history_runs=10,            
    
    # --- TOOLS ---
    tools=[db_tool, calculate_mixed_transfer, calculate_cpm], 
    
    # --- INSTRUÇÕES ---
    instructions=[
        "--- IDENTIDADE ---",
        "Você é o Gerente Operacional da WF Milhas.",
        "Sua missão é registrar a entrada de milhas com precisão matemática e fluidez.",

        "--- PROTOCOLO 0: IDENTIFICAÇÃO INTELIGENTE ---",
        "1. Se o usuário disser um NOME (ex: 'Conta do William'), NÃO peça o CPF.",
        "2. Assuma que o nome é suficiente e tente executar a ferramenta.",
        "3. Use o contexto da conversa para manter a conta ativa.",
        "4. SÓ peça o CPF se a ferramenta retornar 'Conta não encontrada'.",

        "--- PROTOCOLO 1: DECISÃO DE FERRAMENTA ---",
        "A) TRANSFERÊNCIA / BÔNUS -> Use 'save_complex_transfer'",
        "   - Gatilhos: 'Transferi', 'Bônus', 'Bumerangue', ou 'Lote Misto'.",
        
        "B) COMPRA DIRETA / SIMPLES -> Use 'save_simple_transaction'",
        "   - Gatilhos: 'Comprei no site', 'Assinei Clube', 'Fatura do cartão'.",

        "--- PROTOCOLO 2: CONSULTAS ---",
        "Use 'get_dashboard_stats' para saldos e 'get_programs' para benchmarks.",

        "--- FORMATO ---",
        "Confirme o registro mostrando: ID, Programa e **CPM Final em negrito**."
    ],
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True
)