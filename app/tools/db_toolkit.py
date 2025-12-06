import psycopg
from datetime import date
from typing import Optional, Tuple
from agno.tools import Toolkit
from app.core.database import Database  # Importa nosso novo Pool Seguro

class DatabaseManager(Toolkit):
    def __init__(self):
        super().__init__(name="gerenciador_banco_dados")
        # Inicializa o pool de conexões (se já não estiver iniciado)
        Database.initialize()

        # Registra as ferramentas disponíveis para o Agente
        self.register(self.register_account)
        self.register(self.get_programs)
        self.register(self.save_simple_transaction)
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard_stats)

    def _get_conn(self):
        """
        Retorna uma conexão do Pool seguro.
        Deve ser usado sempre dentro de um bloco 'with'.
        """
        return Database.get_connection()

    # --- Métodos Auxiliares (Privados) ---

    def _get_account_id(self, conn: psycopg.Connection, identificador: str) -> Tuple[Optional[str], Optional[str]]:
        """Busca ID e Nome da conta por CPF ou Nome parcial."""
        identificador = str(identificador).strip()
        with conn.cursor() as cur:
            # 1. Tenta CPF exato
            cur.execute("SELECT id, nome FROM accounts WHERE cpf = %s", (identificador,))
            row = cur.fetchone()
            if row: return row[0], row[1]
            
            # 2. Tenta Nome parcial (Case Insensitive)
            cur.execute("SELECT id, nome FROM accounts WHERE nome ILIKE %s", (f"%{identificador}%",))
            row = cur.fetchone()
            if row: return row[0], row[1]
            
            return None, None

    def _get_program_id(self, conn: psycopg.Connection, nome_programa: str) -> Optional[str]:
        """Busca ID do programa pelo nome."""
        if not nome_programa: return None
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM programs WHERE nome ILIKE %s", (f"%{nome_programa}%",))
            row = cur.fetchone()
            if row: return row[0]
            return None

    # --- Ferramentas Públicas (Disponíveis para o Agente) ---

    def register_account(self, nome: str, cpf: str) -> str:
        """Cadastra um novo cliente no sistema."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO accounts (cpf, nome) VALUES (%s, %s) RETURNING id", 
                        (cpf, nome)
                    )
                    # Não precisa commit() explícito se o pool estiver em autocommit,
                    # mas por segurança em transações, mantemos o padrão do contexto.
                # O Pool faz o rollback automático em caso de erro se configurado,
                # ou commit ao sair do bloco com sucesso dependendo da config.
                # Aqui forçamos commit para garantir.
                conn.commit()
            return f"✅ Conta criada com sucesso: {nome}"
        except psycopg.errors.UniqueViolation:
            return "❌ Erro: Já existe uma conta com este CPF."
        except Exception as e:
            return f"❌ Erro Técnico ao criar conta: {str(e)}"

    def get_programs(self) -> str:
        """Lista todos os programas de fidelidade cadastrados."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT nome, benchmark_atual FROM programs WHERE ativo=TRUE ORDER BY nome")
                    rows = cur.fetchall()
            
            if not rows:
                return "Nenhum programa encontrado."
            
            return "📋 Programas Disponíveis:\n" + "\n".join([f"- {r[0]}: R$ {r[1]:.2f}" for r in rows])
        except Exception as e: return f"Erro ao buscar programas: {str(e)}"

    def save_simple_transaction(self, 
                              identificador_conta: str, 
                              programa_nome: str, 
                              milhas_quantidade: int, 
                              custo_total: float, 
                              descricao: str = "Compra Simples") -> str:
        """
        Registra uma compra simples de milhas ou entrada orgânica.
        """
        try:
            with self._get_conn() as conn:
                # Validações dentro da mesma conexão
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return f"❌ Conta '{identificador_conta}' não encontrada."
                
                prog_id = self._get_program_id(conn, programa_nome)
                if not prog_id: return f"❌ Programa '{programa_nome}' não encontrado."

                # Cálculos
                cpm_real = (custo_total / milhas_quantidade * 1000) if milhas_quantidade > 0 else 0
                tipo_lote = "PAGO" if custo_total > 0 else "ORGANICO"

                with conn.cursor() as cur:
                    # 1. Inserir Transação
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), 'COMPRA_SIMPLES' if custo_total > 0 else 'ORGANICO', 
                          prog_id, prog_id, prog_id, milhas_quantidade, milhas_quantidade, 
                          custo_total, cpm_real, descricao))
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a transação."
                    tx_id = result[0]

                    # 2. Inserir Lote Único
                    cur.execute("""
                        INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                        VALUES (%s, %s, %s, %s, %s, 1)
                    """, (tx_id, tipo_lote, milhas_quantidade, cpm_real, custo_total))
                
                conn.commit()
                return f"✅ Transação Salva para {acc_nome}! CPM Final: **R$ {cpm_real:.2f}**"
        except Exception as e: return f"❌ Erro ao salvar transação: {str(e)}"

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
        """
        Registra uma transferência bonificada com composição de lotes (Orgânico + Pago).
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return f"❌ Conta '{identificador_conta}' não encontrada."
                
                orig_id = self._get_program_id(conn, origem_nome)
                dest_id = self._get_program_id(conn, destino_nome)
                if not orig_id or not dest_id: return "❌ Programa de Origem ou Destino inválido."

                # Cálculos Financeiros
                custo_organico = (lote_organico_qtd / 1000) * lote_organico_cpm
                custo_total = custo_organico + lote_pago_custo_total
                milhas_creditadas = int(milhas_base * (1 + bonus_percent / 100))
                cpm_real = (custo_total / milhas_creditadas * 1000) if milhas_creditadas > 0 else 0

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                        VALUES (%s, %s, 'TRANSFERENCIA_BANCO_CIA', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), orig_id, dest_id, dest_id,
                          milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao))
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a transferência."
                    tx_id = result[0]

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
                return f"✅ Transferência Salva para {acc_nome}! CPM Final: **R$ {cpm_real:.2f}**"
        except Exception as e: return f"❌ Erro na transferência: {str(e)}"

    def get_dashboard_stats(self, identificador_conta: str) -> str:
        """Consulta saldo consolidado e CPM médio."""
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return f"❌ Conta '{identificador_conta}' não encontrada."

                with conn.cursor() as cur:
                    # Query Otimizada com GROUP BY
                    cur.execute("""
                        SELECT p.nome, 
                               SUM(t.milhas_creditadas) as saldo, 
                               SUM(t.custo_total) / SUM(t.milhas_creditadas) * 1000 as cpm_medio
                        FROM transactions t
                        JOIN programs p ON t.companhia_referencia_id = p.id
                        WHERE t.account_id = %s
                        GROUP BY p.nome
                        HAVING SUM(t.milhas_creditadas) > 0
                    """, (acc_id,))
                    rows = cur.fetchall()

            if not rows:
                return f"Nenhum saldo encontrado para {acc_nome}."

            res = f"📊 **Extrato de {acc_nome}:**\n"
            total_milhas = 0
            for row in rows:
                prog, saldo, cpm = row
                total_milhas += saldo
                res += f"- {prog}: {saldo:,.0f} milhas • CPM: R$ {cpm:.2f}\n"
            
            res += f"\n**Total Geral:** {total_milhas:,.0f} milhas"
            return res

        except Exception as e: return f"❌ Erro ao consultar dashboard: {str(e)}"