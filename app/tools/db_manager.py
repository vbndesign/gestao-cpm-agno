import sqlite3
import uuid
from pathlib import Path
from datetime import date
from agno.tools import Toolkit

class DatabaseManager(Toolkit):
    def __init__(self, db_path: str = "storage/milhas.db"):
        super().__init__(name="gerenciador_banco_dados")
        self.db_path = db_path
        self._init_db()
        
        # Ferramentas expostas
        self.register(self.register_account)
        self.register(self.get_programs)
        self.register(self.save_simple_transaction) # Agora atualizada
        self.register(self.get_dashboard_stats)

    def _get_conn(self):
        """Conexão com suporte a Foreign Keys"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON") # Crítico para o Schema funcionar
        return conn

    def _init_db(self):
        # Apenas garante que o arquivo existe. A criação real é via schema.sql se necessário
        # (Assumimos que você já rodou o seed_full_history.py e o banco está lá)
        pass

    def _get_account_id(self, conn, identificador: str):
        """Busca ID da conta por CPF ou Nome (parcial)"""
        # Tenta CPF exato
        row = conn.execute("SELECT id, nome FROM accounts WHERE cpf = ?", (identificador,)).fetchone()
        if row: return row[0], row[1]
        
        # Tenta Nome parcial
        row = conn.execute("SELECT id, nome FROM accounts WHERE nome LIKE ?", (f"%{identificador}%",)).fetchone()
        if row: return row[0], row[1]
        
        return None, None

    def _get_program_id(self, conn, nome_programa: str):
        """Busca ID do programa por nome aproximado"""
        if not nome_programa: return None
        row = conn.execute("SELECT id, nome FROM programs WHERE nome LIKE ?", (f"%{nome_programa}%",)).fetchone()
        if row: return row[0]
        return None

    def save_simple_transaction(self, 
                              identificador_conta: str, 
                              programa_nome: str, 
                              milhas_quantidade: int, 
                              custo_total: float, 
                              descricao: str = "Compra Simples") -> str:
        """
        Registra uma compra direta ou acúmulo simples (sem bônus complexo ou múltiplos lotes).
        
        Args:
            identificador_conta: Nome ou CPF do cliente.
            programa_nome: Onde as milhas entraram (ex: 'Latam', 'Livelo').
            milhas_quantidade: Total de milhas recebidas.
            custo_total: Valor total pago (coloque 0 se for orgânico).
            descricao: Texto livre para identificar a operação.
        """
        try:
            with self._get_conn() as conn:
                # 1. Identificar Conta
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id:
                    return f"❌ Erro: Conta '{identificador_conta}' não encontrada. Cadastre primeiro."

                # 2. Identificar Programa
                prog_id = self._get_program_id(conn, programa_nome)
                if not prog_id:
                    return f"❌ Erro: Programa '{programa_nome}' não encontrado. Use 'get_programs' para ver os nomes."

                # 3. Preparar Dados
                tx_id = str(uuid.uuid4())
                batch_id = str(uuid.uuid4())
                
                # Se custo > 0 é PAGO, senão é ORGANICO
                tipo_lote = "PAGO" if custo_total > 0 else "ORGANICO"
                
                # Cálculo CPM
                cpm_real = 0.0
                if milhas_quantidade > 0:
                    cpm_real = (custo_total / milhas_quantidade) * 1000

                # 4. Inserir Transação (Capa)
                conn.execute("""
                    INSERT INTO transactions 
                    (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                     milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tx_id, acc_id, date.today(), 
                    'COMPRA_SIMPLES' if custo_total > 0 else 'ORGANICO', 
                    prog_id, prog_id, prog_id, # Na simples, origem = destino = referencia
                    milhas_quantidade, 0, milhas_quantidade, 
                    custo_total, cpm_real, descricao
                ))

                # 5. Inserir Lote (Miolo - Obrigatório pelo Schema)
                conn.execute("""
                    INSERT INTO transaction_batches 
                    (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (
                    batch_id, tx_id, tipo_lote, 
                    milhas_quantidade, cpm_real, custo_total
                ))
                
                conn.commit()
                
                return (f"✅ Transação Registrada com Sucesso!\n"
                        f"🆔 ID: {tx_id}\n"
                        f"👤 Conta: {acc_nome}\n"
                        f"✈️ Programa: {programa_nome}\n"
                        f"💰 CPM Final: R$ {cpm_real:.2f}")

        except Exception as e:
            return f"❌ Erro de Banco de Dados: {str(e)}"
            
    # Mantenha os outros métodos (register_account, get_programs, get_dashboard_stats) aqui...
    def register_account(self, nome: str, cpf: str) -> str:
        try:
            with self._get_conn() as conn:
                conn.execute("INSERT INTO accounts (id, cpf, nome) VALUES (?, ?, ?)", (str(uuid.uuid4()), cpf, nome))
                conn.commit()
            return f"✅ Conta criada: {nome}"
        except sqlite3.IntegrityError: return "Erro: CPF já existe."

    def get_programs(self) -> str:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT nome FROM programs WHERE ativo=1").fetchall()
        return "Programas: " + ", ".join([r[0] for r in rows])

    def get_dashboard_stats(self, identificador: str) -> str:
        with self._get_conn() as conn:
            acc_id, nome = self._get_account_id(conn, identificador)
            if not acc_id: return "Conta não encontrada."
            
            # Soma simples via SQL
            row = conn.execute("""
                SELECT sum(milhas_creditadas), sum(custo_total) 
                FROM transactions WHERE account_id = ?
            """, (acc_id,)).fetchone()
            
            total_milhas = row[0] or 0
            total_custo = row[1] or 0
            cpm = (total_custo / total_milhas * 1000) if total_milhas > 0 else 0
            
            return f"📊 Resumo {nome}: {total_milhas:,} milhas acumuladas. Investimento: R$ {total_custo:.2f} (CPM Médio: R$ {cpm:.2f})"