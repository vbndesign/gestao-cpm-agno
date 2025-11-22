import sqlite3
import uuid
from pathlib import Path
from agno.tools import Toolkit

class DatabaseManager(Toolkit):
    def __init__(self, db_path: str = "storage/milhas.db"):
        super().__init__(name="gerenciador_banco_dados")
        self.db_path = db_path
        self._init_db()
        
        # Ferramentas expostas para o Agente
        self.register(self.register_account)
        self.register(self.get_programs)
        self.register(self.save_simple_transaction) # Simplificado para o teste inicial
        self.register(self.get_dashboard_stats)

    def _get_conn(self):
        """Conexão com suporte a Foreign Keys"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON") # Crítico para o Schema funcionar
        return conn

    def _init_db(self):
        """Lê o schema.sql e popula dados iniciais (Seed)"""
        schema_path = Path("app/data/schema.sql")
        if not schema_path.exists():
            print("⚠️ ERRO: app/data/schema.sql não encontrado.")
            return

        with self._get_conn() as conn:
            # 1. Cria estrutura
            with open(schema_path, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            
            # 2. Seed: Verifica se existem programas, se não, cria os básicos
            cursor = conn.execute("SELECT count(*) FROM programs")
            if cursor.fetchone()[0] == 0:
                print("🌱 Populando banco com dados iniciais (Seed)...")
                self._seed_data(conn)

    def _seed_data(self, conn):
        """Popula Programas e Benchmarks iniciais"""
        programs = [
            ("livelo", "Livelo", "BANCO", 28.00),
            ("azul", "Azul Fidelidade", "CIA_AEREA", 24.00),
            ("latam", "LATAM Pass", "CIA_AEREA", 29.50),
            ("gol", "Smiles", "CIA_AEREA", 26.00),
            ("esfera", "Esfera", "BANCO", 27.00)
        ]
        
        for prog_id, nome, tipo, bench in programs:
            # Inserir Programa
            conn.execute(
                "INSERT INTO programs (id, nome, tipo, benchmark_atual) VALUES (?, ?, ?, ?)",
                (prog_id, nome, tipo, bench)
            )
            # Inserir Histórico de Benchmark
            conn.execute(
                "INSERT INTO benchmark_history (id, programa_id, valor_cpm, data_inicio) VALUES (?, ?, ?, DATE('now'))",
                (str(uuid.uuid4()), prog_id, bench)
            )
        conn.commit()

    # --- TOOLS PARA O AGENTE ---

    def register_account(self, nome: str, cpf: str) -> str:
        """Cadastra um novo cliente/conta."""
        try:
            with self._get_conn() as conn:
                conn.execute(
                    "INSERT INTO accounts (id, nome, cpf) VALUES (?, ?, ?)", 
                    (str(uuid.uuid4()), nome, cpf)
                )
                conn.commit()
            return f"✅ Conta criada: {nome}"
        except sqlite3.IntegrityError:
            return f"⚠️ Erro: CPF {cpf} já cadastrado."

    def get_programs(self) -> str:
        """Lista programas disponíveis e seus benchmarks atuais."""
        with self._get_conn() as conn:
            rows = conn.execute("SELECT nome, tipo, benchmark_atual FROM programs WHERE ativo=1").fetchall()
        return "📋 Programas Ativos:\n" + "\n".join([f"- {r[0]} ({r[1]}): Ref R$ {r[2]:.2f}" for r in rows])

    def save_simple_transaction(self, 
                              cpf_conta: str, 
                              origem_nome: str, 
                              destino_nome: str, 
                              milhas_base: int, 
                              custo_total: float, 
                              milhas_creditadas: int) -> str:
        """
        Registra uma transação SIMPLES (sem lotes complexos por enquanto).
        O Agente deve buscar os IDs dos programas baseado nos nomes.
        """
        try:
            with self._get_conn() as conn:
                # 1. Buscar IDs (Simplificação)
                acc = conn.execute("SELECT id FROM accounts WHERE cpf=?", (cpf_conta,)).fetchone()
                if not acc: return "❌ Conta não encontrada."
                
                # Busca genérica por nome (like)
                orig = conn.execute("SELECT id FROM programs WHERE nome LIKE ?", (f"%{origem_nome}%",)).fetchone()
                dest = conn.execute("SELECT id FROM programs WHERE nome LIKE ?", (f"%{destino_nome}%",)).fetchone()
                
                if not dest: return f"❌ Programa destino '{destino_nome}' não encontrado."
                orig_id = orig[0] if orig else None
                dest_id = dest[0]
                
                # 2. Calcular CPM Real
                cpm_real = (custo_total / milhas_creditadas) * 1000
                
                # 3. Inserir
                tx_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO transactions 
                    (id, account_id, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, 
                     milhas_base, milhas_creditadas, custo_total, cpm_real)
                    VALUES (?, ?, 'COMPRA_SIMPLES', ?, ?, ?, ?, ?, ?, ?)
                """, (tx_id, acc[0], orig_id, dest_id, dest_id, milhas_base, milhas_creditadas, custo_total, cpm_real))
                
                conn.commit()
                return f"✅ Transação Salva! ID: {tx_id} | CPM: R$ {cpm_real:.2f}"
        except Exception as e:
            return f"Erro DB: {str(e)}"

    def get_dashboard_stats(self, cpf_conta: str) -> str:
        """Retorna resumo financeiro da conta."""
        with self._get_conn() as conn:
            # Soma CPM médio ponderado "na bruta" (apenas para MVP, depois usaremos a tabela balances)
            row = conn.execute("""
                SELECT sum(milhas_creditadas), sum(custo_total) 
                FROM transactions t 
                JOIN accounts a ON t.account_id = a.id 
                WHERE a.cpf = ?
            """, (cpf_conta,)).fetchone()
            
            if not row or not row[0]: return "Sem transações."
            
            total_milhas = row[0]
            total_custo = row[1]
            cpm_medio = (total_custo / total_milhas) * 1000
            
            return f"📊 Resumo Conta {cpf_conta}:\n- Estoque: {total_milhas:,} milhas\n- Investido: R$ {total_custo:.2f}\n- CPM Médio Geral: R$ {cpm_medio:.2f}"