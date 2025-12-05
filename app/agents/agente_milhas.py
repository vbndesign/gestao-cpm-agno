import os
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.postgres import PostgresDb

from app.tools.db_manager import DatabaseManager
from app.tools.calculators import calculate_mixed_transfer, calculate_cpm 

load_dotenv()

# --- CONFIGURAÇÃO DE MEMÓRIA (FIX) ---
db_url = os.getenv("DATABASE_URL")

# CORREÇÃO CRÍTICA: O SQLAlchemy precisa saber que estamos usando o driver 'psycopg' (v3)
# Se a string for 'postgresql://', ele tenta usar 'psycopg2' e falha se não tiver.
if db_url and db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://")

# Configura o banco de sessões
session_db = PostgresDb(
    session_table="agent_sessions",
    db_url=db_url
)

# Garante que a tabela exista (cria se não existir)
try:
    session_db._create_all_tables()
    print("✅ Tabelas do banco de sessões criadas/verificadas com sucesso")
except Exception as e:
    print(f"⚠️ Aviso ao criar tabelas: {e}")

# Instancia as tools
db_tool = DatabaseManager()

# Agente Único
milhas_agent = Agent(
    id="gerente-wf-milhas",
    name="Gerente WF Milhas",
    role="Gestor operacional de contas e milhas aéreas",
    model=OpenAIChat(
        id="gpt-5-nano", 
        api_key=os.getenv("OPENAI_API_KEY")
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