# app/config/settings.py
from pydantic_settings import BaseSettings
from functools import lru_cache
from pydantic import Field

class Settings(BaseSettings):
    # Credenciais Obrigatórias (Se faltar no .env, o app nem inicia)
    openai_api_key: str = Field(...)
    database_url: str = Field(...)
    slack_bot_token: str = Field(...)
    slack_signing_secret: str = Field(...)
    
    # Configurações com valor padrão (Opcionais)
    port: int = 10000
    app_env: str = "production"  # dev, staging, production
    log_level: str = "INFO"

    class Config:
        # Lê automaticamente do arquivo .env local
        env_file = ".env"
        extra = "ignore" # Ignora variáveis extras no .env

# Cria uma instância única (Singleton) cacheada
@lru_cache()
def get_settings():
    return Settings()  # type: ignore

# Instância pronta para uso
settings = get_settings()