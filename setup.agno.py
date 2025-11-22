import os
from pathlib import Path

def create_file(path, content=""):
    if path.exists() and path.name != ".gitignore":
        print(f"⚠️  Mantendo existente: {path.name}")
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"✅ Criado: {path}")

def create_structure():
    base_path = Path.cwd()
    print(f"🚀 Iniciando estrutura WF Milhas (Agno) em: {base_path}\n")

    # 1. Diretórios
    dirs = [
        "app",
        "app/agents",
        "app/tools",
        "storage",
    ]
    
    for d in dirs:
        (base_path / d).mkdir(parents=True, exist_ok=True)
        if "app" in d:
            (base_path / d / "__init__.py").touch()

    # 2. Conteúdos dos Arquivos

    # --- .env ---
    content_env = """OPENAI_API_KEY=sk-...
    """

    # --- app/tools/calculators.py (Lógica Pura) ---
    content_calc = """from agno.tools import Toolkit

class MilhasCalculator(Toolkit):
    def __init__(self):
        super().__init__(name="calculadora_milhas")
        self.register(self.calculate_cpm)
        self.register(self.calculate_bonus_miles)
        self.register(self.calculate_mixed_transfer)

    def calculate_cpm(self, custo_total: float, milhas_totais: int) -> float:
        \"\"\"
        Calcula o CPM (Custo Por Milheiro) Real.
        Fórmula: (custo / milhas) * 1000
        \"\"\"
        if milhas_totais == 0: return 0.0
        return round((custo_total / milhas_totais) * 1000, 2)

    def calculate_bonus_miles(self, milhas_base: int, bonus_percent: float) -> int:
        \"\"\"
        Calcula o total de milhas creditadas após o bônus.
        Ex: 1000 milhas + 100% bonus = 2000 milhas.
        \"\"\"
        return int(milhas_base * (1 + bonus_percent / 100))

    def calculate_mixed_transfer(self, 
                               lote_organico_milhas: int, 
                               lote_organico_cpm: float,
                               lote_pago_milhas: int,
                               preco_milheiro_pago: float,
                               bonus_percent: float) -> str:
        \"\"\"
        Calcula o CPM Final de uma transferência que mistura milhas orgânicas (antigas)
        com milhas compradas (novas), aplicando o bônus no total.
        Retorna uma string explicativa com o cálculo detalhado.
        \"\"\"
        # 1. Custos
        custo_organico = (lote_organico_milhas / 1000) * lote_organico_cpm
        custo_pago = (lote_pago_milhas / 1000) * preco_milheiro_pago
        custo_total = custo_organico + custo_pago

        # 2. Milhas
        total_transferido = lote_organico_milhas + lote_pago_milhas
        total_creditado = int(total_transferido * (1 + bonus_percent / 100))

        # 3. CPM Final
        cpm_final = 0.0
        if total_creditado > 0:
            cpm_final = (custo_total / total_creditado) * 1000

        return (f"--- Resultado do Cálculo Misto ---\\n"
                f"1. Total Transferido: {total_transferido:,} milhas\\n"
                f"2. Total Creditado (com {bonus_percent}% bônus): {total_creditado:,} milhas\\n"
                f"3. Custo Total: R$ {custo_total:.2f}\\n"
                f"4. CPM FINAL: R$ {cpm_final:.2f}")
"""

    # --- app/agents/milhas.py (O Agente) ---
    content_agent = """from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.tools.calculators import MilhasCalculator

# Agente Especialista em Milhas
milhas_agent = Agent(
    name="Gerente WF Milhas",
    role="Especialista em gestão de CPM e análise de oportunidades de milhas aéreas",
    model=OpenAIChat(id="gpt-4o"),
    tools=[MilhasCalculator()],
    instructions=[
        "Você é o cérebro operacional da WF Milhas.",
        "Sua prioridade é a precisão matemática. NUNCA tente adivinhar cálculos.",
        "SEMPRE use a ferramenta 'calculadora_milhas' para qualquer conta de CPM ou Bônus.",
        "Ao analisar transferências com lote orgânico e pago, use estritamente a ferramenta calculate_mixed_transfer.",
        "Responda de forma direta e executiva.",
        "Se o CPM for abaixo de R$ 16,00, considere uma excelente oportunidade."
    ],
    show_tool_calls=True,
    markdown=True,
    add_datetime_to_context=True,
)
"""

    # --- app/agent_os.py (Entry Point) ---
    content_os = """from agno.os import AgentOS
from app.agents.milhas import milhas_agent
from fastapi import FastAPI

# Definição do Sistema Operacional de Agentes
ag_os = AgentOS(
    id="wf-milhas-os",
    description="Sistema de Gestão de Milhas WF",
    agents=[milhas_agent]
)

# Exporta o app FastAPI para o Render/Uvicorn
app = ag_os.get_app()

if __name__ == "__main__":
    # Roda localmente na porta 7777
    ag_os.serve(app="app.agent_os:app", host="0.0.0.0", port=7777, reload=True)
"""

    # --- .gitignore ---
    content_git = """__pycache__/
.env
storage/
.venv/
*.db
"""

    create_file(base_path / ".env", content_env)
    create_file(base_path / "app/tools/calculators.py", content_calc)
    create_file(base_path / "app/agents/milhas.py", content_agent)
    create_file(base_path / "app/agent_os.py", content_os)
    create_file(base_path / ".gitignore", content_git)
    
    print("\n🎉 Estrutura criada! Instale as dependências:")
    print("uv add agno openai fastapi uvicorn")

if __name__ == "__main__":
    create_structure()