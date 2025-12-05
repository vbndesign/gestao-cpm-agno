import os
import logging
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from dotenv import load_dotenv

# Importa nosso agente configurado
from app.agents.agente_milhas import milhas_agent

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuração do Slack
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")

# Inicializa Cliente e Verificador (apenas se as credenciais existirem)
slack_client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None
verifier = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None

app = FastAPI(title="WF Milhas - Slack Bot")

async def process_slack_message(event: dict):
    """
    Roda em background para não travar o Slack (timeout de 3s).
    """
    channel_id = event.get("channel")
    user_id = event.get("user")
    text = event.get("text")
    ts = event.get("ts") # Timestamp da mensagem original
    
    # Validação de dados obrigatórios
    if not channel_id or not user_id or not text or not ts or not slack_client:
        logger.error("Dados incompletos do evento Slack ou cliente não configurado")
        return
    
    # Remove a menção ao bot para não confundir a IA (ex: "<@U123> registrar..." vira "registrar...")
    # O Slack manda o ID do bot no evento, mas simplificamos limpando qualquer menção
    cleaned_text = text.split(">")[-1].strip() if "<@" in text else text

    logger.info(f"🤖 Processando para {user_id}: {cleaned_text}")

    try:
        # 1. Reação Visual (Olhos) - Indica "Estou pensando" (opcional, pode falhar por falta de scope)
        try:
            slack_client.reactions_add(channel=channel_id, name="eyes", timestamp=ts)
        except Exception as e:
            logger.warning(f"Não foi possível adicionar reação (falta scope reactions:write?): {e}")

        # 2. Chama o Agente Agno
        # O session_id garante memória única por usuário do Slack
        logger.info(f"🤖 Chamando agente com session_id=slack_{user_id}")
        response_stream = milhas_agent.run(
            cleaned_text, 
            session_id=f"slack_{user_id}",
            stream=False  # Desabilita streaming para simplificar
        )
        
        # O .run() retorna um objeto RunResponse, pegamos o conteúdo texto
        response_text = response_stream.content if response_stream and response_stream.content else "Desculpe, não consegui processar sua solicitação."
        logger.info(f"✅ Resposta gerada: {response_text[:100] if len(response_text) > 100 else response_text}...")

        # 3. Feedback de Sucesso (Check) (opcional)
        try:
            slack_client.reactions_remove(channel=channel_id, name="eyes", timestamp=ts)
            slack_client.reactions_add(channel=channel_id, name="white_check_mark", timestamp=ts)
        except Exception as e:
            logger.warning(f"Não foi possível atualizar reação: {e}")

        # 4. Responde no canal
        slack_client.chat_postMessage(
            channel=channel_id,
            text=response_text,
            mrkdwn=True # Habilita formatação Markdown do Agente
        )
        logger.info(f"✅ Mensagem enviada ao Slack no canal {channel_id}")

    except Exception as e:
        logger.error(f"❌ Erro ao processar: {e}")
        # Tenta avisar o erro no Slack
        try:
            slack_client.reactions_remove(channel=channel_id, name="eyes", timestamp=ts)
            slack_client.reactions_add(channel=channel_id, name="x", timestamp=ts)
            slack_client.chat_postMessage(channel=channel_id, text=f"⚠️ Erro interno: {str(e)}")
        except:
            pass

@app.post("/slack/events")
async def slack_events_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Rota única que o Slack chama para tudo (Event Subscription).
    """
    # Verificar se o Slack está configurado
    if not verifier or not slack_client:
        raise HTTPException(status_code=503, detail="Slack not configured")
    
    # [NOVO] Ignora retentativas do Slack (X-Slack-Retry-Num)
    if "X-Slack-Retry-Num" in request.headers:
        # Se o Slack está tentando de novo, dizemos "OK" e ignoramos para não duplicar
        return {"status": "skipped_retry"}
    
    # 1. Ler o corpo da requisição (bytes) para validação
    body_bytes = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "0")
    signature = request.headers.get("X-Slack-Signature", "")

    # 2. Validar Assinatura (Segurança: Garante que veio do Slack)
    if not verifier.is_valid(body_bytes.decode('utf-8'), timestamp, signature):
        raise HTTPException(status_code=403, detail="Invalid request signature")

    # 3. Parse do JSON
    body = await request.json()

    # 4. Handshake de Verificação de URL (Obrigatório na configuração inicial)
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 5. Processar Eventos Reais
    if "event" in body:
        event = body["event"]
        
        # Ignora mensagens de bots para evitar loop infinito
        if "bot_id" in event:
            return {"status": "ignored"}
        
        # O tipo 'message' captura tudo (texto normal, imagens, etc)
        # O 'app_mention' captura quando marcam o bot explicitamente
        event_type = event.get("type")
        
        if event_type == "message" or event_type == "app_mention":
            # [CRÍTICO] Verificação dupla para evitar Loop Infinito
            # Se a mensagem tiver 'bot_id', ignoramos.
            if "bot_id" not in event:
                background_tasks.add_task(process_slack_message, event)

    return {"status": "ok"}

# Rota de Saúde para o Render
@app.get("/health")
def health_check():
    return {"status": "active", "service": "wf-milhas-bot"}

# if __name__ == "__main__":
    # import uvicorn
    # Roda o servidor FastAPI para o Slack Bot
    # uvicorn.run(app, host="0.0.0.0", port=10000, reload=True)

if __name__ == "__main__":
    import uvicorn
    # Tenta pegar a porta do ambiente (Render). Se não achar, usa 10000 (Local).
    port = int(os.getenv("PORT", 10000)) 
    uvicorn.run(app, host="0.0.0.0", port=port)