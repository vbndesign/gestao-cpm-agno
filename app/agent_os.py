from agno.os import AgentOS
from app.agents.agente_milhas import milhas_agent
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
    ag_os.serve(app="app.agent_os:app", host="localhost", port=7777, reload=True)
