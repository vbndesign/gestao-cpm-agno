from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat

# Importa os especialistas modulares
from app.agents.specialists.acquisition import acquisition_agent
from app.agents.specialists.analyst import analyst_agent

import os
from dotenv import load_dotenv

load_dotenv()

# O Líder agora é uma instância de TEAM, não de Agent
milhas_team = Team(
    name="Equipe WF Milhas",
    role="Gerente de Atendimento",
    model=OpenAIChat(id="gpt-5-mini", api_key=os.getenv("OPENAI_API_KEY")),
    # A lista de agentes agora entra no parâmetro 'members'
    members=[acquisition_agent, analyst_agent],
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