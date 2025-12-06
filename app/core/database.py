# app/core/database.py
from psycopg_pool import ConnectionPool
from app.config.settings import settings

class Database:
    """
    Gerenciador Singleton de Pool de Conexões.
    Garante que só exista UM pool para toda a aplicação.
    """
    _pool = None

    @classmethod
    def initialize(cls):
        """Inicializa o pool se ainda não existir."""
        if cls._pool is None:
            # Configura o driver correto para o Agno/Supabase
            db_url = settings.database_url
            # if db_url.startswith("postgresql://"):
                # db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
            
            # Cria o pool
            cls._pool = ConnectionPool(
                conninfo=db_url,
                min_size=1,  # Sempre mantém 1 conexão viva
                max_size=20, # Aguenta até 20 conversas simultâneas
                timeout=30,  # Espera 30s por uma conexão livre
                name="wf_milhas_pool"
            )
            print("✅ Database Connection Pool inicializado.")

    @classmethod
    def get_connection(cls):
        """Retorna uma conexão do pool (use com 'with')."""
        if cls._pool is None:
            cls.initialize()
        
        if cls._pool is None:
            raise RuntimeError("Failed to initialize database pool")
        
        # O pool gerencia automaticamente o 'putconn' (devolver conexão)
        # quando usado dentro de um bloco 'with'
        return cls._pool.connection()

    @classmethod
    def close(cls):
        """Fecha todas as conexões ao desligar o app."""
        if cls._pool:
            cls._pool.close()
            print("🛑 Database Connection Pool encerrado.")