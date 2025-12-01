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
        self.register(self.save_simple_transaction)
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard_stats)

        # Ferramentas para FASE 2 (Desativadas no MVP)
        # self.register(self.save_issuance)

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
        
        [USO RESTRITO] Registra APENAS:
        1. Compra Direta de Pontos (Sem bônus de transferência).
        2. Acúmulo Orgânico (Cartão, Voo).
        3. Clube de Assinatura.
        
        PROIBIDO USAR PARA: Transferências com Bônus ou Lotes Mistos.
        Se houver origem diferente do destino ou bônus %, use 'save_complex_transfer'.
        Args:
            identificador_conta: Nome do cliente (ex: 'Ana') ou CPF. Não peça CPF se já tiver o nome.
            programa_nome: Onde as milhas entraram (ex: 'Latam', 'Livelo').
            milhas_quantidade: Total de milhas recebidas.
            custo_total: Valor total pago (coloque 0 se for orgânico).
            descricao: Texto livre para identificar a operação.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return "❌ Conta não encontrada."
                prog_id = self._get_program_id(conn, programa_nome)
                if not prog_id: return "❌ Programa não encontrado."

                tx_id = str(uuid.uuid4())
                tipo_lote = "PAGO" if custo_total > 0 else "ORGANICO"
                cpm_real = (custo_total / milhas_quantidade * 1000) if milhas_quantidade > 0 else 0

                conn.execute("""
                    INSERT INTO transactions 
                    (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                     milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (tx_id, acc_id, date.today(), 'COMPRA_SIMPLES' if custo_total > 0 else 'ORGANICO', 
                      prog_id, prog_id, prog_id, milhas_quantidade, 0, milhas_quantidade, 
                      custo_total, cpm_real, descricao))

                conn.execute("""
                    INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (str(uuid.uuid4()), tx_id, tipo_lote, milhas_quantidade, cpm_real, custo_total))
                
                conn.commit()
                return f"✅ Simples Salva! ID: {tx_id} | CPM: R$ {cpm_real:.2f}"
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
        """
        [USO OBRIGATÓRIO] Para qualquer TRANSFERÊNCIA entre programas (ex: Livelo -> Latam).
        Use esta ferramenta sempre que houver:
        - Bônus de Transferência (%).
        - Mistura de milhas antigas (Orgânicas) com novas (Pagas).
        
        Args:
            identificador_conta: Apenas o Primeiro Nome (ex: 'William') ou CPF. O sistema busca automaticamente.
            milhas_base: Total transferido da origem (antes do bônus).
            bonus_percent: O percentual extra ganho (ex: 80).
            lote_organico_qtd: Parte das milhas base que era estoque antigo/grátis.
            lote_pago_qtd: Parte das milhas base que foi comprada/nova.
            lote_pago_custo_total: Quanto custou comprar o lote pago.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return "❌ Conta não encontrada."
                orig_id = self._get_program_id(conn, origem_nome)
                dest_id = self._get_program_id(conn, destino_nome)
                if not orig_id or not dest_id: return "❌ Origem ou Destino não encontrado."

                # Lógica
                custo_organico = (lote_organico_qtd / 1000) * lote_organico_cpm
                custo_total = custo_organico + lote_pago_custo_total
                milhas_creditadas = int(milhas_base * (1 + bonus_percent / 100))
                cpm_real = (custo_total / milhas_creditadas * 1000) if milhas_creditadas > 0 else 0

                tx_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO transactions 
                    (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                     milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
                    VALUES (?, ?, ?, 'TRANSFERENCIA_BANCO_CIA', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (tx_id, acc_id, date.today(), orig_id, dest_id, dest_id,
                      milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao))

                if lote_organico_qtd > 0:
                    conn.execute("INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem) VALUES (?, ?, 'ORGANICO', ?, ?, ?, 1)", 
                                 (str(uuid.uuid4()), tx_id, lote_organico_qtd, lote_organico_cpm, custo_organico))
                
                if lote_pago_qtd > 0:
                    cpm_pago = (lote_pago_custo_total / lote_pago_qtd * 1000)
                    conn.execute("INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem) VALUES (?, ?, 'PAGO', ?, ?, ?, 2)", 
                                 (str(uuid.uuid4()), tx_id, lote_pago_qtd, cpm_pago, lote_pago_custo_total))

                conn.commit()
                return f"✅ Transferência Complexa Salva! CPM Final: R$ {cpm_real:.2f}"
        except Exception as e: return f"Erro: {str(e)}"

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

    def get_dashboard_stats(self, identificador_conta: str) -> str:
        """Gera relatório de saldo e CPM médio por programa."""
        with self._get_conn() as conn:
            acc_id, nome = self._get_account_id(conn, identificador_conta)
            if not acc_id: return "❌ Conta não encontrada."
            
            rows = conn.execute("""
                SELECT p.nome, sum(t.milhas_creditadas), sum(t.custo_total)
                FROM transactions t JOIN programs p ON t.destino_id = p.id
                WHERE t.account_id = ? GROUP BY p.nome
            """, (acc_id,)).fetchall()
            
            if not rows: return f"📊 Sem dados para {nome}."
            
            res = f"📊 **Extrato: {nome}**\n\n| Programa | Saldo | CPM Médio |\n|---|---|---|\n"
            for r in rows:
                cpm = (r[2]/r[1]*1000) if r[1] > 0 else 0
                res += f"| {r[0]} | {r[1]:,} | R$ {cpm:.2f} |\n"
            return res