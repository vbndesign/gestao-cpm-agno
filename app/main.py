import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier

# --- NOVOS IMPORTS DA ARQUITETURA ---
from app.config.settings import settings
from app.core.database import Database
# Import do Agente (Certifique-se que o arquivo está em app/agents/milhas_agent.py ou ajuste aqui)
try:
    from app.agents.milhas_agent import milhas_agent
except ImportError:
    # Fallback caso você ainda não tenha renomeado o arquivo antigo
    from app.agents.milhas_agent import milhas_agent

# Configuração de Logs via Settings
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("wf_milhas")

# --- LIFESPAN (Gerenciamento de Vida do App) ---
# Isso substitui a inicialização solta. Garante que o banco conecte antes de aceitar requisições.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup: Inicializa o Pool de Conexões
    logger.info("🔄 Inicializando Database Connection Pool...")
    Database.initialize()
    logger.info("✅ Sistema pronto para receber eventos.")
    yield
    # 2. Shutdown: Fecha conexões graciosamente
    logger.info("🛑 Fechando conexões...")
    Database.close()

# Inicializa FastAPI com o gerenciador de vida
app = FastAPI(title="WF Milhas - Slack Bot", lifespan=lifespan)

# Inicializa Cliente Slack usando as Settings validadas
slack_client = WebClient(token=settings.slack_bot_token)
verifier = SignatureVerifier(settings.slack_signing_secret)

async def process_slack_message(event: dict):
    """
    Processa a mensagem em background.
    """
    user_id = event.get("user")
    text = event.get("text")
    channel_id = event.get("channel")
    ts = event.get("ts")

    # Validação: Garante que temos channel_id e ts
    if not channel_id or not ts:
        logger.warning("⚠️ Evento sem channel_id ou ts. Ignorando.")
        return

    # Limpeza de texto (remove menção <@BOTID>)
    cleaned_text = text.split(">")[-1].strip() if text and "<@" in text else (text or "")
    
    logger.info(f"🤖 Processando mensagem de {user_id}: {cleaned_text[:50]}...")

    try:
        # Reação: Olhos (Processando)
        try:
            slack_client.reactions_add(channel=channel_id, name="eyes", timestamp=ts)
        except Exception as e:
            logger.warning(f"Slack Reaction Error: {e}")

        # --- CHAMADA AO AGENTE ---
        # Note: O agente já usa o db_toolkit novo internamente
        response_stream = milhas_agent.run(
            cleaned_text, 
            session_id=f"slack_{user_id}",
            stream=False
        )
        
        response_text = response_stream.content or "Desculpe, fiquei sem resposta."

        # Reação: Check (Sucesso)
        try:
            slack_client.reactions_remove(channel=channel_id, name="eyes", timestamp=ts)
            slack_client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=ts)
        except: pass

        # Envia Resposta
        slack_client.chat_postMessage(
            channel=channel_id,
            text=response_text,
            mrkdwn=True
        )

    except Exception as e:
        logger.error(f"❌ Erro crítico no processamento: {e}", exc_info=True)
        try:
            slack_client.chat_postMessage(channel=channel_id, text=f"⚠️ Erro interno: {str(e)}")
        except: pass

@app.post("/slack/events")
async def slack_events_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint único para Webhooks do Slack.
    """
    # 1. Validação de Retry do Slack (Evita duplicidade)
    if "X-Slack-Retry-Num" in request.headers:
        logger.info("♻️ Ignorando retry do Slack.")
        return {"status": "skipped_retry"}

    # 2. Validação de Assinatura (Segurança)
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")

    if not verifier.is_valid(body_bytes.decode('utf-8'), timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # 3. Processamento do Evento
    body = await request.json()

    # Handshake (Challenge)
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    if "event" in body:
        event = body["event"]
        
        # Ignora bots (incluindo a si mesmo)
        if "bot_id" in event:
            return {"status": "ignored"}

        event_type = event.get("type")
        if event_type in ["message", "app_mention"]:
            # Enfileira para background (regra dos 3 segundos)
            background_tasks.add_task(process_slack_message, event)

    return {"status": "ok"}

@app.get("/health")
def health_check():
    """
    Health Check para o Render saber que estamos vivos.
    """
    return {
        "status": "active", 
        "env": settings.app_env, 
        "service": "wf-milhas-bot"
    }

if __name__ == "__main__":
    import uvicorn
    # Usa a porta configurada no settings (lê PORT do Render ou 10000 padrão)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)