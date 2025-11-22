from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.tools.calculators import MilhasCalculator
from app.tools.db_manager import DatabaseManager

import os
from dotenv import load_dotenv

load_dotenv()

# Instanciamos as ferramentas aqui. 
# Ao rodar esta linha, o DatabaseManager vai verificar/criar o banco storage/milhas.db
db_tool = DatabaseManager()
calc_tool = MilhasCalculator()

# Agente Especialista em Milhas
milhas_agent = Agent(
    name="Gerente WF Milhas",
    role="Gestor operacional de contas e milhas aéreas",
    model=OpenAIChat(id="gpt-5-mini", api_key=os.getenv("OPENAI_API_KEY")),
    tools=[
        db_tool,   # Acesso ao Banco (SQL)
        calc_tool  # Acesso à Matemática (Calculadoras)
    ],
    instructions=[
        "Você é o braço direito operacional da WF Milhas.",
        "Sua função é gerenciar contas, transações e analisar oportunidades de milhas.",
        
        "--- FLUXO DE INÍCIO ---",
        "1. Ao iniciar, verifique se o usuário já identificou a conta (Cliente).",
        "2. Se não, pergunte o nome ou CPF. Se não existir, use 'register_account'.",
        "3. Se o usuário pedir 'quais programas existem', use 'get_programs'.",
        
        "--- FLUXO DE REGISTRO DE TRANSAÇÃO ---",
        "1. Colete: Origem, Destino, Qtd Milhas, Custo Total.",
        "2. Use 'calculadora_milhas' para validar o CPM antes de salvar.",
        "3. Use 'save_simple_transaction' para persistir no banco.",
        "4. Após salvar, confirme o ID e o CPM Real registrado.",
        
        "--- CONSULTA ---",
        "1. Se o usuário pedir um resumo, use 'get_dashboard_stats'.",
        
        "Seja executivo, preciso e use tabelas markdown para listar dados."
    ],
    markdown=True,
    add_datetime_to_context=True,
)