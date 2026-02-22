import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier

# --- IMPORTS DA ARQUITETURA ---
from app.config.settings import settings
from app.core.database import Database
from app.core.logging_config import setup_logging
from app.agents.milhas_agent import milhas_agent

# Configuração de Logs via Settings
setup_logging(settings.app_env, settings.log_level)
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
    Processa mensagens com inteligência de contexto (Thread vs DM).
    """
    user_id = event.get("user")
    text = event.get("text")
    channel_id = event.get("channel")
    ts = event.get("ts")             # Timestamp da mensagem atual
    thread_ts = event.get("thread_ts") # Timestamp da thread (se já existir)

    # Validação: Garante que temos channel_id e ts
    if not channel_id or not ts:
        logger.warning("⚠️ Evento sem channel_id ou ts. Ignorando.")
        return

    # Limpeza de texto (remove menção <@BOTID>)
    cleaned_text = text.split(">")[-1].strip() if text and "<@" in text else (text or "")
    
    logger.info("msg_received", extra={"event": "msg_received", "user_id": user_id})

    # --- ESTRATÉGIA DE MEMÓRIA E ROTEAMENTO ---
    # Definição de onde responder e qual memória usar
    if thread_ts:
        # CASO 1: Mensagem dentro de uma Thread existente
        # A memória é compartilhada por todos naquela thread
        session_id = f"thread_{thread_ts}"
        target_thread = thread_ts
        context_type = "EXISTING_THREAD"
        
    elif channel_id.startswith("D"):
        # CASO 2: Mensagem Direta (DM)
        # A memória é pessoal do usuário (contínua)
        session_id = f"dm_{user_id}"
        target_thread = None # Em DM não forçamos thread
        context_type = "DM_PRIVATE"
        
    else:
        # CASO 3: Mensagem solta em Canal Público
        # Criamos uma NOVA thread para organizar a bagunça
        session_id = f"thread_{ts}" # A memória nasce com essa mensagem
        target_thread = ts # Força a resposta a criar o fio
        context_type = "NEW_THREAD_CHANNEL"

    logger.info(f"🧠 Processando [{context_type}] | Session: {session_id} | User: {user_id}")

    try:
        # 1. Reação Visual: Olhos (Processando)
        try:
            slack_client.reactions_add(channel=channel_id, name="eyes", timestamp=ts)
        except: pass

        # 2. Chamada ao Agente
        _t0 = time.perf_counter()
        response_stream = milhas_agent.run(
            cleaned_text,
            session_id=session_id, # Memória dinâmica
            user_id=user_id,
            stream=False
        )
        logger.info("agent_run_ok", extra={
            "event": "agent_run_ok",
            "session_id": session_id,
            "context_type": context_type,
            "duration_ms": int((time.perf_counter() - _t0) * 1000),
        })

        response_text = response_stream.content or "Desculpe, fiquei sem resposta."

        # 3. Reação Visual: Check (Sucesso)
        try:
            slack_client.reactions_remove(channel=channel_id, name="eyes", timestamp=ts)
            slack_client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=ts)
        except: pass

        # 4. Envia Resposta (Na Thread correta ou DM)
        slack_client.chat_postMessage(
            channel=channel_id,
            text=response_text,
            thread_ts=target_thread, # <--- A Mágica acontece aqui
            mrkdwn=True
        )

    except Exception as e:
        logger.error("agent_run_error", extra={
            "event": "agent_run_error",
            "session_id": session_id,
            "error_type": type(e).__name__,
        }, exc_info=True)
        try:
            slack_client.chat_postMessage(
                channel=channel_id, 
                text=f"⚠️ Erro interno: {str(e)}",
                thread_ts=target_thread # Avisa o erro na thread certa também
            )
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
    try:
        with Database.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "active",
        "database": db_status,
        "env": settings.app_env
    }

if __name__ == "__main__":
    import uvicorn
    # Usa a porta configurada no settings (lê PORT do Render ou 10000 padrão)
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)