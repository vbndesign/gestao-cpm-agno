from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.tools.db_manager import DatabaseManager
# Importamos as funções diretamente agora
from app.tools.calculators import calculate_mixed_transfer, calculate_cpm 

import os
from dotenv import load_dotenv

load_dotenv()

# Instancia as tools com estado (DB)
db_tool = DatabaseManager()

# Agente Único
milhas_agent = Agent(
    name="Gerente WF Milhas",
    role="Gestor operacional de contas e milhas aéreas",
    model=OpenAIChat(id="gpt-5-mini", api_key=os.getenv("OPENAI_API_KEY")),
    # A lista de tools agora mistura a Instância do Toolkit com as Funções Puras
    tools=[db_tool, calculate_mixed_transfer, calculate_cpm], 
    instructions=[
        "Você é o recepcionista da WF Milhas.",
        "Sua função é entender o pedido e delegar para o especialista correto:",
        
        "--- ROTEAMENTO ---",
        "1. Entrada de Milhas (Compra, Bônus, Ganho) -> Chame 'Especialista em Aquisição'.",
        "2. Consulta (Saldo, Resumo, Benchmark) -> Chame 'Analista de Carteira'.",
        
        "--- REGRAS GERAIS ---",
        "1. Se o usuário falar de 'Venda' ou 'Emissão', avise que esse módulo está desativado temporariamente.",
        "2. Não tente resolver cálculos complexos sozinho, delegue."
    ],
    markdown=True,
    add_datetime_to_context=True,
    debug_mode=True
)