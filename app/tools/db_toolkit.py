import psycopg
import re
from datetime import date
from typing import Optional, Tuple
from agno.tools import Toolkit
from app.core.database import Database
from app.core.enums import TipoLote, ModoAquisicao
from app.tools.date_parser import parse_date_natural

class DatabaseManager(Toolkit):
    def __init__(self):
        super().__init__(name="gerenciador_banco_dados")
        Database.initialize()

        # --- ATUALIZAÇÃO: Registrando as novas ferramentas corretas ---
        self.register(self.check_account_exists) # Nova: Para o agente "ver"
        self.register(self.create_account)       # Renomeada e atualizada
        self.register(self.get_programs)
        self.register(self.save_simple_transaction)
        # self.register(self.prepare_complex_transfer) # DESABILITADA: Validação prévia (economiza tokens)
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard)

    def _get_conn(self):
        """
        Retorna uma conexão do Pool seguro.
        Deve ser usado sempre dentro de um bloco 'with'.
        """
        return Database.get_connection()

    # --- Métodos Auxiliares (Privados) ---

    def _normalize_identifier(self, identificador: str) -> str:
        """
        Normaliza o identificador removendo prefixos comuns como "conta da".
        """
        texto = str(identificador).strip()
        texto = re.sub(r"^\s*conta\s+(da|do|de|para)\s+", "", texto, flags=re.IGNORECASE)
        return texto.strip()

    def _normalize_cpf(self, cpf: str) -> str:
        """Remove caracteres não numéricos do CPF."""
        return re.sub(r"\D", "", str(cpf or ""))

    def _is_valid_cpf(self, cpf: str) -> bool:
        """
        Valida CPF (tamanho, dígitos verificadores e repetição).
        """
        cpf_digits = self._normalize_cpf(cpf)
        if len(cpf_digits) != 11:
            return False
        if cpf_digits == cpf_digits[0] * 11:
            return False

        def calc_digit(base: str) -> str:
            total = sum(int(d) * w for d, w in zip(base, range(len(base) + 1, 1, -1)))
            resto = total % 11
            return "0" if resto < 2 else str(11 - resto)

        dig1 = calc_digit(cpf_digits[:9])
        dig2 = calc_digit(cpf_digits[:9] + dig1)
        return cpf_digits[-2:] == dig1 + dig2

    def _get_account_id(self, conn: psycopg.Connection, identificador: str) -> Tuple[Optional[str], Optional[str]]:
        """Busca ID e Nome da conta por UUID, CPF ou Nome parcial."""
        identificador_raw = str(identificador).strip()
        identificador_norm = self._normalize_identifier(identificador_raw)
        identificador_norm = identificador_norm.replace("%", "\\%").replace("_", "\\_")
        cpf_digits = self._normalize_cpf(identificador_raw)
        
        with conn.cursor() as cur:
            # 1. Tenta UUID primeiro (com ou sem hífens)
            # Remove tudo que não é hexadecimal para comparar
            uuid_clean = re.sub(r"[^a-fA-F0-9]", "", identificador_raw)
            if len(uuid_clean) == 32:  # UUID sem hífens tem 32 chars hex
                # Busca comparando apenas os caracteres hex (ignorando hífens)
                cur.execute("""
                    SELECT id, nome FROM accounts 
                    WHERE REPLACE(id::text, '-', '') = %s
                """, (uuid_clean,))
                row = cur.fetchone()
                if row:
                    return row[0], row[1]
            
            # 2. Tenta CPF (normalizando pontuações)
            if len(cpf_digits) == 11:
                cur.execute(
                    "SELECT id, nome FROM accounts WHERE regexp_replace(cpf, '\\D', '', 'g') = %s",
                    (cpf_digits,)
                )
                row = cur.fetchone()
                if row:
                    return row[0], row[1]
            
            # 3. Tenta Nome parcial (Case Insensitive)
            cur.execute("SELECT id, nome FROM accounts WHERE nome ILIKE %s", (f"%{identificador_norm}%",))
            row = cur.fetchone()
            if row:
                return row[0], row[1]
            
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
    def check_account_exists(self, nome_conta: str) -> str:
        """
        Verifica se uma conta existe pelo nome.
        Retorna o ID e Nome se achar, ou avisa que não encontrou.
        Use isso ANTES de registrar transações para nomes desconhecidos.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if acc_id:
                    return f"✅ Conta encontrada: {acc_nome} (ID: {acc_id})"
                return "❌ Conta não encontrada. Verifique o nome ou inicie o cadastro."
        except Exception as e:
            return f"Erro na busca: {str(e)}"

    def create_account(self, nome_completo: str, tipo_gestao: str, cpf: Optional[str] = None) -> str:
        """
        Cadastra um novo cliente. 
        Obrigatório: nome_completo e tipo_gestao ('PROPRIA' ou 'CLIENTE').
        Opcional: cpf.
        """
        try:
            # Normalização simples para o ENUM
            tipo = str(tipo_gestao).upper().strip()
            if tipo not in ['PROPRIA', 'CLIENTE']:
                return "❌ Erro: O tipo de gestão deve ser 'PROPRIA' ou 'CLIENTE'."

            cpf_clean = self._normalize_cpf(cpf) if cpf else None
            
            # Validação de CPF apenas se foi fornecido
            if cpf_clean and not self._is_valid_cpf(cpf_clean):
                 return "Ops, esse CPF não parece válido. Confere pra mim?"

            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    # Verifica duplicidade de CPF (se tiver CPF)
                    if cpf_clean:
                        cur.execute("SELECT 1 FROM accounts WHERE regexp_replace(cpf, '\\D', '', 'g') = %s", (cpf_clean,))
                        if cur.fetchone():
                            return "❌ Erro: Já existe uma conta com este CPF."

                    cur.execute(
                        "INSERT INTO accounts (nome, tipo_gestao, cpf) VALUES (%s, %s, %s) RETURNING id", 
                        (nome_completo, tipo, cpf_clean)
                    )
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a conta."
                    account_id = result[0]
                conn.commit()
            return f"✅ Conta criada com sucesso para **{nome_completo}** ({tipo})! ID: {account_id}"
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
                              data_transacao: Optional[str] = None,
                              observacao: Optional[str] = None) -> str:
        """
        Registra uma compra simples de milhas ou entrada orgânica.
        data_transacao: Data da transação em linguagem natural (ex: 'hoje', 'ontem', '17/03/2026'). Se omitido, usa data atual.
        observacao: Observação opcional fornecida pelo usuário.
        """
        try:
            # Parse e validação de data
            data_tx = parse_date_natural(data_transacao) if data_transacao else date.today()
            if not data_tx:
                return f"❌ Erro: Não consegui interpretar a data '{data_transacao}'. Use formatos como 'hoje', 'ontem', 'DD/MM/AAAA' ou 'DD de mês de AAAA'."
            
            with self._get_conn() as conn:
                # Validações dentro da mesma conexão
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return f"❌ Conta '{identificador_conta}' não encontrada."
                
                prog_id = self._get_program_id(conn, programa_nome)
                if not prog_id: return f"❌ Programa '{programa_nome}' não encontrado."

                # Cálculos
                cpm_real = (custo_total / milhas_quantidade * 1000) if milhas_quantidade > 0 else 0
                tipo_lote = TipoLote.PAGO if custo_total > 0 else TipoLote.ORGANICO

                with conn.cursor() as cur:
                    # 1. Inserir Transação
                    modo = ModoAquisicao.COMPRA_SIMPLES if custo_total > 0 else ModoAquisicao.ORGANICO
                    # Descrição sempre gerada automaticamente
                    descricao = f"{modo.value}: {milhas_quantidade:,} milhas em {programa_nome}"
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, observacao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), data_tx, modo.value, 
                          prog_id, prog_id, prog_id, milhas_quantidade, milhas_quantidade, 
                          custo_total, cpm_real, descricao, observacao),
                          prepare=False)
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a transação."
                    tx_id = result[0]

                    # 2. Inserir Lote Único
                    cur.execute("""
                        INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                        VALUES (%s, %s, %s, %s, %s, 1)
                    """, (tx_id, tipo_lote.value, milhas_quantidade, cpm_real, custo_total),
                         prepare=False)
                
                conn.commit()
                return f"✅ Transação Salva para {acc_nome}! CPM Final: **R$ {cpm_real:.2f}**"
        except Exception as e: return f"❌ Erro ao salvar transação: {str(e)}"

    # ============================================================================
    # FUNÇÃO DESABILITADA: prepare_complex_transfer
    # ============================================================================
    # CONTEXTO:
    # Esta função foi criada para validar transferências complexas ANTES de salvá-las
    # no banco de dados. Ela verifica se:
    # - Todos os parâmetros são válidos (milhas > 0, bônus >= 0, etc.)
    # - A soma dos lotes (orgânico + pago) é exatamente igual a milhas_base
    # - Exibe um resumo detalhado dos cálculos financeiros (CPM, custos, etc.)
    #
    # MOTIVO DA DESABILITAÇÃO:
    # - Gasta tokens extras (~5-10k) por validação
    # - As mesmas validações JÁ EXISTEM em save_complex_transfer
    # - save_complex_transfer retorna mensagens de erro claras se algo estiver errado
    # - A validação no nível de banco de dados (constraints/triggers) é planejada
    #
    # QUANDO REATIVAR:
    # - Se houver muitos erros de validação em produção
    # - Se o agente precisar "pré-visualizar" cálculos complexos antes de salvar
    # - Para debugging de problemas recorrentes com lotes mistos
    #
    # PARA REATIVAR: Descomente o código abaixo e adicione na linha 20:
    # self.register(self.prepare_complex_transfer)
    # ============================================================================
    # def prepare_complex_transfer(self,
    #                             identificador_conta: str,
    #                             origem_nome: str,
    #                             destino_nome: str,
    #                             milhas_base: int,
    #                             bonus_percent: float,
    #                             lote_organico_qtd: int,
    #                             lote_organico_cpm: float,
    #                             lote_pago_qtd: int,
    #                             lote_pago_custo_total: float) -> str:
    #     """
    #     FERRAMENTA DE VALIDAÇÃO: Use isso ANTES de save_complex_transfer.
    #     Valida todos os parâmetros e mostra o resumo do que será salvo.
    #     Ajuda o agente a confirmar se os cálculos estão corretos.
    #     """
    #     # Validações básicas
    #     errors = []
    #     if milhas_base <= 0:
    #         errors.append("❌ milhas_base deve ser maior que zero")
    #     if bonus_percent < 0:
    #         errors.append("❌ bonus_percent não pode ser negativo")
    #     if lote_organico_qtd < 0:
    #         errors.append("❌ lote_organico_qtd não pode ser negativo")
    #     if lote_pago_qtd < 0:
    #         errors.append("❌ lote_pago_qtd não pode ser negativo")
    #     
    #     soma_lotes = lote_organico_qtd + lote_pago_qtd
    #     if soma_lotes != milhas_base:
    #         errors.append(f"❌ ERRO CRÍTICO: Soma dos lotes ({soma_lotes}) ≠ milhas_base ({milhas_base})")
    #     
    #     if errors:
    #         return "⚠️ PROBLEMAS DETECTADOS:\n" + "\n".join(errors)
    #     
    #     # Cálculos (mesma lógica de save_complex_transfer)
    #     custo_organico = (lote_organico_qtd / 1000) * lote_organico_cpm
    #     custo_total = custo_organico + lote_pago_custo_total
    #     milhas_creditadas = int(milhas_base * (1 + bonus_percent / 100))
    #     cpm_real = (custo_total / milhas_creditadas * 1000) if milhas_creditadas > 0 else 0
    #     
    #     return f"""✅ Validação OK! Resumo da Transferência:
    # 
    # 📍 **Conta:** {identificador_conta}
    # 🔄 **Rota:** {origem_nome} → {destino_nome}
    # 📊 **Composição:**
    #    • Lote Orgânico: {lote_organico_qtd:,} milhas @ R$ {lote_organico_cpm:.2f}/k = R$ {custo_organico:.2f}
    #    • Lote Pago: {lote_pago_qtd:,} milhas = R$ {lote_pago_custo_total:.2f}
    # 
    # 💰 **Financeiro:**
    #    • Milhas Base: {milhas_base:,}
    #    • Bônus: {bonus_percent}%
    #    • **Milhas Creditadas: {milhas_creditadas:,}**
    #    • **Custo Total: R$ {custo_total:.2f}**
    #    • **CPM Final: R$ {cpm_real:.2f}**
    # 
    # ✅ Tudo certo! Pode chamar save_complex_transfer com esses mesmos parâmetros."""

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
                            data_transacao: Optional[str] = None,
                            observacao: Optional[str] = None) -> str:
        """
        Registra uma transferência bonificada com composição de lotes (Orgânico + Pago).
        data_transacao: Data da transação em linguagem natural (ex: 'hoje', 'ontem', '17/03/2026'). Se omitido, usa data atual.
        observacao: Observação opcional fornecida pelo usuário.
        """
        try:
            # Parse e validação de data
            data_tx = parse_date_natural(data_transacao) if data_transacao else date.today()
            if not data_tx:
                return f"❌ Erro: Não consegui interpretar a data '{data_transacao}'. Use formatos como 'hoje', 'ontem', 'DD/MM/AAAA' ou 'DD de mês de AAAA'."
            
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, identificador_conta)
                if not acc_id: return f"❌ Conta '{identificador_conta}' não encontrada."
                
                orig_id = self._get_program_id(conn, origem_nome)
                dest_id = self._get_program_id(conn, destino_nome)
                
                # Mensagens de erro mais específicas
                if not orig_id:
                    return f"❌ Programa de Origem '{origem_nome}' não encontrado."
                if not dest_id:
                    return f"❌ Programa de Destino '{destino_nome}' não encontrado."

                # Validações de entrada
                if milhas_base <= 0:
                    return "❌ Erro: milhas_base deve ser maior que zero."
                if bonus_percent < 0:
                    return "❌ Erro: bonus_percent não pode ser negativo."
                if lote_organico_qtd < 0 or lote_pago_qtd < 0:
                    return "❌ Erro: quantidades de lotes não podem ser negativas."
                if lote_organico_qtd + lote_pago_qtd != milhas_base:
                    return f"❌ Erro: A soma dos lotes ({lote_organico_qtd + lote_pago_qtd}) deve ser igual a milhas_base ({milhas_base})."

                # Cálculos Financeiros
                custo_organico = (lote_organico_qtd / 1000) * lote_organico_cpm
                custo_total = custo_organico + lote_pago_custo_total
                milhas_creditadas = int(milhas_base * (1 + bonus_percent / 100))
                cpm_real = (custo_total / milhas_creditadas * 1000) if milhas_creditadas > 0 else 0

                # Descrição sempre gerada automaticamente
                descricao = f"Transfer {origem_nome}→{destino_nome}: {lote_pago_qtd:,} pagos (R${lote_pago_custo_total:.2f}) + {lote_organico_qtd:,} orgânicos, bônus {bonus_percent}%"

                with conn.cursor() as cur:
                    # Desabilita prepared statements para evitar conflitos
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, observacao)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (acc_id, date.today(), data_tx, ModoAquisicao.TRANSFERENCIA.value, orig_id, dest_id, dest_id,
                          milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, observacao),
                          prepare=False)
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a transferência."
                    tx_id = result[0]

                    # Inserir Lotes Filhos
                    if lote_organico_qtd > 0:
                        cur.execute("""
                            INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                            VALUES (%s, %s, %s, %s, %s, 1)
                        """, (tx_id, TipoLote.ORGANICO.value, lote_organico_qtd, lote_organico_cpm, custo_organico),
                             prepare=False)
                    
                    if lote_pago_qtd > 0:
                        cpm_pago = (lote_pago_custo_total / lote_pago_qtd * 1000)
                        cur.execute("""
                            INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial, ordem)
                            VALUES (%s, %s, %s, %s, %s, 2)
                        """, (tx_id, TipoLote.PAGO.value, lote_pago_qtd, cpm_pago, lote_pago_custo_total),
                             prepare=False)

                conn.commit()
                return f"✅ Transferência Salva para {acc_nome}! CPM Final: **R$ {cpm_real:.2f}**"
        except psycopg.Error as db_err:
            return f"❌ Erro de Banco de Dados: {type(db_err).__name__} - {str(db_err)}"
        except Exception as e: 
            return f"❌ Erro na transferência: {type(e).__name__} - {str(e)}"

    def get_dashboard(self, identificador_conta: str) -> str:
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
