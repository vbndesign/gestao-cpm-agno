import os
import psycopg
from datetime import date
from agno.tools import Toolkit
from dotenv import load_dotenv

load_dotenv()

class DatabaseManager(Toolkit):
    def __init__(self):
        super().__init__(name="gerenciador_banco_dados")
        
        # Pega a URL do .env (Coloque sua string lá com a chave DATABASE_URL)
        self.db_url = os.getenv("DATABASE_URL")
        
        if not self.db_url:
            print("❌ ERRO: DATABASE_URL não encontrada no .env")

        # --- FERRAMENTAS ATIVAS ---
        self.register(self.register_account)
        self.register(self.get_programs)
        self.register(self.save_simple_transaction)
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard_stats)

    def _get_conn(self):
        """Retorna conexão com PostgreSQL"""
        if not self.db_url:
            raise ValueError("DATABASE_URL não configurada")
        return psycopg.connect(self.db_url)

    def _init_db(self):
        # O Schema agora é gerenciado pelo painel do Supabase, não aqui.
        pass

    def _get_account_id(self, conn, identificador: str):
        identificador = str(identificador).strip()
        with conn.cursor() as cur:
            # 1. Tenta CPF exato
            cur.execute("SELECT id, nome FROM accounts WHERE cpf = %s", (identificador,))
            row = cur.fetchone()
            if row: return row[0], row[1]
            
            # 2. Tenta Nome parcial (ILIKE é case-insensitive no Postgres)
            cur.execute("SELECT id, nome FROM accounts WHERE nome ILIKE %s", (f"%{identificador}%",))
            row = cur.fetchone()
            if row: return row[0], row[1]
            
            return None, None

    def _get_program_id(self, conn, nome_programa: str):
        if not nome_programa: return None
        with conn.cursor() as cur:
            # ILIKE para ignorar maiúsculas/minúsculas
            cur.execute("SELECT id, nome FROM programs WHERE nome ILIKE %s", (f"%{nome_programa}%",))
            row = cur.fetchone()
            if row: return row[0]
            return None

    # --- TOOLS ADAPTADAS PARA POSTGRESQL (%s em vez de ?) ---

    def register_account(self, nome: str, cpf: str) -> str:
        """Cadastra um novo cliente."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO accounts (cpf, nome) VALUES (%s, %s) RETURNING id", 
                        (cpf, nome)
                    )
                conn.commit() # Commit explícito é necessário
            return f"✅ Conta criada: {nome}"
        except psycopg.errors.UniqueViolation:
            return "❌ Erro: CPF já existe."
        except Exception as e:
            return f"❌ Erro Técnico: {str(e)}"

    def get_programs(self) -> str:
        """Lista programas e benchmarks."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT nome, benchmark_atual FROM programs WHERE ativo=TRUE")
                    rows = cur.fetchall()
            return "📋 Programas:\n" + "\n".join([f"- {r[0]}: R$ {r[1]:.2f}" for r in rows])
        except Exception as e: return f"Erro: {str(e)}"

    def save_simple_transaction(self, 
                              identificador_conta: str, 
                              programa_nome: str, 
                              milhas_quantidade: int, 
                              custo_total: float, 
                              descricao: str = "Compra Simples") -> str:
        """Registra compra simples (Postgres Version)."""
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return "❌ Conta não encontrada."
                prog_id = self._get_program_id(conn, programa_nome)
                if not prog_id: return "❌ Programa não encontrado."

                # O ID é UUID gerado pelo banco automaticamente se omitido, 
                # mas aqui vamos deixar o banco gerar ou passar explicitamente se precisar.
                # No Schema Postgres definimos DEFAULT gen_random_uuid(), então não precisamos passar ID.
                
                cpm_real = (custo_total / milhas_quantidade * 1000) if milhas_quantidade > 0 else 0
                tipo_lote = "PAGO" if custo_total > 0 else "ORGANICO"

                with conn.cursor() as cur:
                    # 1. Inserir Transação e recuperar ID gerado
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), 'COMPRA_SIMPLES' if custo_total > 0 else 'ORGANICO', 
                          prog_id, prog_id, prog_id, milhas_quantidade, 0, milhas_quantidade, 
                          custo_total, cpm_real, descricao))
                    
                    row = cur.fetchone()
                    if not row: raise ValueError("Erro ao inserir transação")
                    tx_id = row[0]

                    # 2. Inserir Lote
                    cur.execute("""
                        INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                        VALUES (%s, %s, %s, %s, %s, 1)
                    """, (tx_id, tipo_lote, milhas_quantidade, cpm_real, custo_total))
                
                conn.commit()
                return f"✅ Simples Salva! CPM: R$ {cpm_real:.2f}"
        except Exception as e: return f"Erro: {str(e)}"

    def save_complex_transfer(self,
                            identificador_conta: str,
                            origem_nome: str,
                            destino_nome: str,
                            milhas_base: int,
                            bonus_percent: float,
                            lote_organico_qtd: int,
                            lote_organico_cpm: float,
                            lote_pago_qtd: int,
                            lote_pago_custo_total: float,
                            descricao: str = "Transferência Bonificada") -> str:
        """Registra transferência complexa (Postgres Version)."""
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return "❌ Conta não encontrada."
                orig_id = self._get_program_id(conn, origem_nome)
                dest_id = self._get_program_id(conn, destino_nome)
                if not orig_id or not dest_id: return "❌ Origem ou Destino não encontrado."

                custo_organico = (lote_organico_qtd / 1000) * lote_organico_cpm
                custo_total = custo_organico + lote_pago_custo_total
                milhas_creditadas = int(milhas_base * (1 + bonus_percent / 100))
                cpm_real = (custo_total / milhas_creditadas * 1000) if milhas_creditadas > 0 else 0

                with conn.cursor() as cur:
                    # Inserir Transação Pai
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                        VALUES (%s, %s, 'TRANSFERENCIA_BANCO_CIA', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), orig_id, dest_id, dest_id,
                          milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao))
                    
                    row = cur.fetchone()
                    if not row: raise ValueError("Erro ao inserir transação")
                    tx_id = row[0]

                    # Inserir Lotes Filhos
                    if lote_organico_qtd > 0:
                        cur.execute("""
                            INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                            VALUES (%s, 'ORGANICO', %s, %s, %s, 1)
                        """, (tx_id, lote_organico_qtd, lote_organico_cpm, custo_organico))
                    
                    if lote_pago_qtd > 0:
                        cpm_pago = (lote_pago_custo_total / lote_pago_qtd * 1000)
                        cur.execute("""
                            INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                            VALUES (%s, 'PAGO', %s, %s, %s, 2)
                        """, (tx_id, lote_pago_qtd, cpm_pago, lote_pago_custo_total))

                conn.commit()
                return f"✅ Transferência Salva! CPM Final: R$ {cpm_real:.2f}"
        except Exception as e: return f"Erro: {str(e)}"

    def get_dashboard_stats(self, identificador_conta: str) -> str:
        """Gera relatório de saldo (Postgres Version)."""
        with self._get_conn() as conn:
            acc_id, nome = self._get_account_id(conn, identificador_conta)
            if not acc_id: return "❌ Conta não encontrada."
            
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.nome, sum(t.milhas_creditadas), sum(t.custo_total)
                    FROM transactions t JOIN programs p ON t.destino_id = p.id
                    WHERE t.account_id = %s GROUP BY p.nome
                """, (acc_id,))
                rows = cur.fetchall()
            
            if not rows: return f"📊 Sem dados para {nome}."
            
            res = f"📊 **Extrato: {nome}**\n\n| Programa | Saldo | CPM Médio |\n|---|---|---|\n"
            for r in rows:
                cpm = (float(r[2])/r[1]*1000) if r[1] > 0 else 0
                res += f"| {r[0]} | {r[1]:,} | R$ {cpm:.2f} |\n"
            return res