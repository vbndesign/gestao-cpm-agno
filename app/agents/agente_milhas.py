import os
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.db.sqlite import SqliteDb  # <--- Importante para persistência

from app.tools.db_manager import DatabaseManager
from app.tools.calculators import calculate_mixed_transfer, calculate_cpm 

load_dotenv()

# --- CONFIGURAÇÃO DE MEMÓRIA ---
# Cria um banco separado apenas para guardar o histórico das conversas
# Isso é diferente do milhas.db que guarda as transações financeiras
session_db = SqliteDb(session_table="agent_sessions", db_file="storage/sessions.db")

# Instancia as tools
db_tool = DatabaseManager()

# Agente Único (Configurado com gpt-5-mini)
milhas_agent = Agent(
    name="Gerente WF Milhas",
    role="Gestor operacional de contas e milhas aéreas",
    model=OpenAIChat(
        id="gpt-5-mini", 
        api_key=os.getenv("OPENAI_API_KEY")
    ),
    # --- PERSISTÊNCIA E MEMÓRIA ---
    db=session_db,                  # Onde salvar o chat
    add_history_to_context=True,    # Agente "lê" o que foi dito antes
    num_history_runs=10,            # Lembra das últimas 10 trocas de mensagem
    
    # --- TOOLS ---
    tools=[db_tool, calculate_mixed_transfer, calculate_cpm], 
    # --- INSTRUÇÕES (Mantidas) ---
    instructions=[
        "--- IDENTIDADE ---",
        "Você é o Gerente Operacional da WF Milhas.",
        "Sua missão é registrar a entrada de milhas com precisão matemática.",

        "--- PROTOCOLO 0: IDENTIFICAÇÃO ---",
        "1. Identifique o Cliente e a Conta antes de qualquer ação.",
        "2. Se não existir, cadastre.",

        "--- PROTOCOLO 1: DECISÃO DE FERRAMENTA (CRÍTICO) ---",
        "Analise a operação e escolha o caminho:",

        "🚨 CAMINHO A: TRANSFERÊNCIA OU BÔNUS",
        "Gatilhos: Usuário menciona 'Transferi', 'Bônus', 'Bumerangue', ou 'Lote Misto'.",
        "AÇÃO OBRIGATÓRIA: Use a ferramenta 'save_complex_transfer'.",
        "PROIBIDO: Jamais use 'save_simple_transaction' nestes casos.",
        "Dados necessários (pergunte se faltar):",
        "   - Origem e Destino",
        "   - Milhas Base (Antes do bônus)",
        "   - % de Bônus",
        "   - Divisão: Quanto era orgânico (velho/grátis) e quanto foi pago (novo)?",

        "🟢 CAMINHO B: COMPRA DIRETA / SIMPLES",
        "Gatilhos: 'Comprei no site', 'Assinei Clube', 'Fatura do cartão'.",
        "Condição: NÃO tem bônus de transferência entre programas.",
        "AÇÃO: Use 'save_simple_transaction'.",

        "--- PROTOCOLO 2: CONSULTAS ---",
        "Use 'get_dashboard_stats' para saldos e 'get_programs' para benchmarks.",

        "--- FORMATO ---",
        "Confirme o registro mostrando: ID, Programa e **CPM Final em negrito**."
    ],
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True
)