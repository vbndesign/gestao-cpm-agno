from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.tools.calculators import MilhasCalculator

import os
from dotenv import load_dotenv

load_dotenv()

# Agente Especialista em Milhas
milhas_agent = Agent(
    name="Gerente WF Milhas",
    role="Especialista em gestão de CPM e análise de oportunidades de milhas aéreas",
    model=OpenAIChat(id="gpt-5-mini", api_key=os.getenv("OPENAI_API_KEY")),
    tools=[MilhasCalculator()],
    instructions=[
        "Você é o cérebro operacional da WF Milhas.",
        "Sua prioridade é a precisão matemática. NUNCA tente adivinhar cálculos.",
        "SEMPRE use a ferramenta 'calculadora_milhas' para qualquer conta de CPM ou Bônus.",
        "Ao analisar transferências com lote orgânico e pago, use estritamente a ferramenta calculate_mixed_transfer.",
        "Responda de forma direta e executiva.",
        "Se o CPM for abaixo de R$ 16,00, considere uma excelente oportunidade."
    ],
    markdown=True,
    add_datetime_to_context=True,
)
