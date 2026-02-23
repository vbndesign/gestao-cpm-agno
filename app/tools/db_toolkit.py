import functools
import logging
import psycopg
import re
import time
import uuid
from datetime import date
from typing import Optional, Tuple
from agno.tools import Toolkit
from app.core.database import Database
from app.core.enums import TipoLote, ModoAquisicao
from app.tools.date_parser import parse_date_natural

_logger = logging.getLogger("wf_milhas.tools")

_MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


def _sanitize_error(tool_name: str, e: Exception) -> str:
    """Loga a exceção real e retorna mensagem genérica com ref rastreável ao agente (segurança)."""
    ref = uuid.uuid4().hex[:8]
    _logger.error("tool_exception", extra={
        "event": "tool_exception",
        "tool": tool_name,
        "error_type": type(e).__name__,
        "ref": ref,
    }, exc_info=True)
    return f"❌ Erro interno ao executar '{tool_name}' [ref: {ref}]. Operação não concluída."


def log_tool_call(func):
    """Loga início, duração e outcome de cada tool call. Nunca loga parâmetros (LGPD)."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        _logger.info("tool_start", extra={"event": "tool_start", "tool": func.__name__})
        t0 = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            _logger.info("tool_ok", extra={
                "event": "tool_ok",
                "tool": func.__name__,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            })
            return result
        except Exception as e:
            _logger.error("tool_error", extra={
                "event": "tool_error",
                "tool": func.__name__,
                "error_type": type(e).__name__,
                "duration_ms": int((time.perf_counter() - t0) * 1000),
            })
            raise
    return wrapper

class DatabaseManager(Toolkit):
    def __init__(self):
        super().__init__(name="gerenciador_banco_dados")
        Database.initialize()

        # Contas e programas
        self.register(self.check_account_exists)
        self.register(self.create_account)
        self.register(self.get_programs)

        # Transações e saldo
        self.register(self.save_simple_transaction)
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard)

        # Assinaturas de clube
        self.register(self.register_subscription)
        self.register(self.correct_last_subscription)
        self.register(self.process_monthly_credit)
        self.register(self.register_intra_club_transaction)

        # Deleção com confirmação em 2 etapas
        self.register(self.delete_last_transaction)
        self.register(self.confirm_delete_transaction)

        # Protocolo de CPM (checkpoints e reajuste)
        self.register(self.confirm_cpm_checkpoint)
        self.register(self.get_cpm_summary)
        self.register(self.calculate_cpm_adjustment)
        self.register(self.apply_cpm_adjustment)
        self.register(self.get_client_panorama)

    def _get_conn(self):
        """
        Retorna uma conexão do Pool seguro.
        Deve ser usado sempre dentro de um bloco 'with'.
        """
        return Database.get_connection()

    # ── Helpers: normalização de identificadores ─────────────────────────────

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
        Espera receber CPF já normalizado (apenas dígitos).
        """
        cpf_digits = cpf  # já normalizado pelo chamador
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

    # ── Helpers: lookup de entidades no banco ────────────────────────────────

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
            #    Prefixos como 'conta da/do/de' já foram removidos por _normalize_identifier
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

    # ── Helpers: validação e inserção de assinaturas ─────────────────────────

    def _parse_subscription_params(
        self,
        valor_total_ciclo: float,
        milhas_garantidas_ciclo: int,
        data_renovacao: str,
        data_inicio: Optional[str],
        is_mensal: bool,
    ) -> Tuple[Optional[str], Optional[float], Optional[int], Optional[date], Optional[date], Optional[str]]:
        """
        Valida e normaliza os parâmetros de uma assinatura antes de qualquer acesso ao banco.
        Retorna (error, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt, tipo_contrato).
        Se error não for None, todos os demais campos são None e o chamador deve retornar o erro.
        """
        if data_inicio:
            dt_inicio = parse_date_natural(data_inicio, prefer_future=False)
            if not dt_inicio:
                return (
                    f"❌ Erro: Não consegui interpretar a data de início '{data_inicio}'. "
                    "Use formatos como 'DD/MM/AAAA' ou 'DD de mês de AAAA'.",
                    None, None, None, None, None,
                )
        else:
            dt_inicio = date.today()

        data_renov_dt = parse_date_natural(data_renovacao, prefer_future=True)
        if not data_renov_dt:
            return (
                f"❌ Erro: Não consegui interpretar a data de renovação '{data_renovacao}'. "
                "Use formatos como 'daqui a 1 ano', 'DD/MM/AAAA' ou 'DD de mês de AAAA'.",
                None, None, None, None, None,
            )

        if data_renov_dt <= dt_inicio:
            return (
                f"❌ Erro: A data de renovação deve ser posterior à data de início. "
                f"Início: {dt_inicio.strftime('%d/%m/%Y')}, Renovação: {data_renov_dt.strftime('%d/%m/%Y')}.",
                None, None, None, None, None,
            )

        if is_mensal:
            valor_contrato = float(valor_total_ciclo) * 12
            milhas_contrato = int(milhas_garantidas_ciclo) * 12
            tipo_contrato = "MENSAL (Anualizado x12)"
        else:
            valor_contrato = float(valor_total_ciclo)
            milhas_contrato = int(milhas_garantidas_ciclo)
            tipo_contrato = "ANUAL (Valor Cheio)"

        if valor_contrato <= 0:
            return ("❌ Erro: valor_total_ciclo deve ser maior que zero.", None, None, None, None, None)
        if milhas_contrato <= 0:
            return ("❌ Erro: milhas_garantidas_ciclo deve ser maior que zero.", None, None, None, None, None)

        return (None, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt, tipo_contrato)

    def _insert_subscription(
        self,
        conn: psycopg.Connection,
        acc_id: str,
        prog_id: str,
        valor_contrato: float,
        milhas_contrato: int,
        dt_inicio: date,
        data_renov_dt: date,
    ) -> Optional[Tuple[str, float]]:
        """
        Executa o INSERT na tabela subscriptions usando a conexão fornecida.
        Não faz commit — responsabilidade do chamador.
        Retorna (new_sub_id, cpm_fixo) calculado pelo banco, ou None se o RETURNING não retornar linha.
        """
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO subscriptions
                (account_id, programa_id, valor_total_ciclo, milhas_garantidas_ciclo,
                 data_inicio, data_renovacao, ativo)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                RETURNING id, cpm_fixo
            """, (acc_id, prog_id, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt),
            prepare=False)
            result = cur.fetchone()
            if not result:
                return None
            return (str(result[0]), result[1])

    # ── Ferramentas públicas: contas e programas ─────────────────────────────

    @log_tool_call
    def check_account_exists(self, nome_conta: str) -> str:
        """
        Verifica se uma conta existe pelo nome, alias, CPF ou UUID.
        Retorna o ID, Nome e Alias (se houver) se achar, ou avisa que não encontrou.
        Use isso ANTES de registrar transações para nomes desconhecidos.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if acc_id:
                    return f"✅ Conta encontrada: {acc_nome} (ID: {acc_id})"
                return "❌ Conta não encontrada. Verifique o nome ou inicie o cadastro."
        except Exception as e:
            return _sanitize_error("check_account_exists", e)

    @log_tool_call
    def create_account(self, nome_completo: str, tipo_gestao: str, cpf: str) -> str:
        """
        Cadastra um novo cliente.
        Obrigatório: nome_completo, tipo_gestao ('PROPRIA' ou 'CLIENTE') e cpf.
        """
        try:
            # Normalização simples para o ENUM
            tipo = str(tipo_gestao).upper().strip()
            if tipo not in ['PROPRIA', 'CLIENTE']:
                return "❌ Erro: O tipo de gestão deve ser 'PROPRIA' ou 'CLIENTE'."

            # Normalização do CPF (strip antes para eliminar whitespace puro)
            cpf_stripped = str(cpf or "").strip()
            if not cpf_stripped:
                return "❌ Erro: O CPF é obrigatório para cadastrar uma conta."

            cpf_clean = self._normalize_cpf(cpf_stripped)
            if not self._is_valid_cpf(cpf_clean):
                return "❌ Erro: CPF inválido. Confira os dígitos e tente novamente."

            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    # Verifica duplicidade de CPF
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
            return _sanitize_error("create_account", e)

    @log_tool_call
    def get_programs(self) -> str:
        """Lista todos os programas de fidelidade cadastrados."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT nome, tipo FROM programs WHERE ativo=TRUE ORDER BY nome")
                    rows = cur.fetchall()
            
            if not rows:
                return "Nenhum programa encontrado."
            
            return "📋 Programas Disponíveis:\n" + "\n".join([f"- {r[0]} ({r[1]})" for r in rows])
        except Exception as e:
            return _sanitize_error("get_programs", e)

    # ── Ferramentas públicas: transações e saldo ─────────────────────────────

    @log_tool_call
    def save_simple_transaction(self,
                              nome_conta: str, 
                              nome_programa: str, 
                              milhas: int, 
                              custo_total: float,
                              bonus_percent: float = 0.0,
                              data_transacao: Optional[str] = None,
                              observacao: Optional[str] = None) -> str:
        """
        Registra uma compra simples de milhas ou entrada orgânica.
        Suporta bônus sobre o valor base (ex: 25% de bônus aumenta as milhas creditadas).

        Args:
            bonus_percent: Percentual de bônus (ex: 25 para 25%)
            data_transacao: Data em formato padrão. IMPORTANTE: Quando o usuário usar 
                expressões relativas complexas (ex: "daqui 1 ano"), converta você mesmo 
                calculando a data exata e passe no formato DD/MM/AAAA ou DD/MM. 
                Exemplo: "daqui 1 ano" de 07/02/2026 = passe "07/02/2027".
                Se omitido, usa data atual.
            observacao: Observação livre do usuário
        """
        try:
            # 1. Parse de data
            data_tx = parse_date_natural(data_transacao) if data_transacao else date.today()
            if not data_tx:
                return f"❌ Erro: Não consegui interpretar a data '{data_transacao}'."
            
            # 2. Cálculo de bônus
            milhas_base = int(milhas)
            bonus = float(bonus_percent)
            total_milhas = int(milhas_base * (1 + bonus / 100))
            
            # 3. Define modo e descrição
            if custo_total <= 0:
                modo = ModoAquisicao.ORGANICO
                custo_final = 0.0
                tag_bonus = f" + {int(bonus)}% bônus" if bonus > 0 else ""
                descricao = f"Entrada Orgânica: {total_milhas:,} milhas{tag_bonus} em {nome_programa}"
            else:
                modo = ModoAquisicao.COMPRA_SIMPLES
                custo_final = float(custo_total)
                tag_bonus = f" (com {int(bonus)}% bônus)" if bonus > 0 else ""
                descricao = f"Compra Simples: {milhas_base:,} milhas{tag_bonus} em {nome_programa}"
            
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."
                
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: return f"❌ Programa '{nome_programa}' não encontrado."
                
                # 4. CPM Real baseado no total creditado
                cpm_real = (custo_final / total_milhas * 1000) if total_milhas > 0 else 0
                
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO transactions
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, observacao, subscription_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (acc_id, date.today(), data_tx, modo.value,
                          prog_id, prog_id, prog_id, 
                          milhas_base, bonus, total_milhas, 
                          custo_final, cpm_real, descricao, observacao, None),
                          prepare=False)
                    
                    conn.commit()
                    
                    msg_bonus = f"\n🎁 **Bônus:** {int(bonus)}% aplicado" if bonus > 0 else ""
                    return (
                        f"✅ Transação Salva para {acc_nome}!{msg_bonus}\n"
                        f"📊 **Milhas Creditadas:** {total_milhas:,}\n"
                        f"💰 **CPM Final:** R$ {cpm_real:.2f}"
                    )
            
        except Exception as e:
            return _sanitize_error("save_simple_transaction", e)

    @log_tool_call
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
        
        Args:
            data_transacao: Data em formato padrão. Para expressões relativas complexas 
                (ex: "daqui 1 ano"), converta calculando a data exata e passe DD/MM/AAAA. 
                Se omitido, usa data atual.
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
        except Exception as e:
            return _sanitize_error("save_complex_transfer", e)

    @log_tool_call
    def get_dashboard(self, identificador_conta: str) -> str:
        """
        Retorna o extrato consolidado de milhas e CPM médio por programa.
        Agrega todas as transações da conta, exibindo saldo total e custo médio
        por milheiro em cada programa com saldo positivo.
        """
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

        except Exception as e:
            return _sanitize_error("get_dashboard", e)

    # ── Ferramentas públicas: assinaturas de clube ───────────────────────────

    @log_tool_call
    def register_subscription(self,
                            nome_conta: str, 
                            nome_programa: str, 
                            valor_total_ciclo: float, 
                            milhas_garantidas_ciclo: int, 
                            data_renovacao: str,
                            data_inicio: Optional[str] = None,
                            is_mensal: bool = False) -> str:
        """
        Registra uma assinatura de Clube (recorrência mensal/anual).
        O CPM é calculado automaticamente pelo banco de dados.
        
        Args:
            valor_total_ciclo: Valor monetário do ciclo (mensal ou anual, dependendo de is_mensal).
            milhas_garantidas_ciclo: Quantidade de milhas do ciclo (mensal ou anual).
            data_renovacao: Data de renovação FUTURA. Aceita linguagem natural:
                'daqui a 1 ano', '07/02/2027', '7 de fevereiro de 2027'.
            data_inicio: Data de início da assinatura (opcional). Se não informada, usa hoje.
                Pode ser no passado. Aceita linguagem natural: '15 de janeiro', '01/01/2026'.
            is_mensal: Se True, multiplica os valores por 12 para criar o contrato anual.
                Use True quando o usuário informar valores mensais (ex: "R$40 por mês").
                Use False quando o usuário informar valores anuais/totais.
        """
        try:
            err, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt, tipo_contrato = \
                self._parse_subscription_params(
                    valor_total_ciclo, milhas_garantidas_ciclo,
                    data_renovacao, data_inicio, is_mensal,
                )
            if err:
                return err
            # _parse_subscription_params garante que, sem erro, todos os campos são não-None.
            if valor_contrato is None or milhas_contrato is None or dt_inicio is None \
                    or data_renov_dt is None or tipo_contrato is None:
                return _sanitize_error("register_subscription", ValueError("parse retornou None inesperado"))

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                insert_result = self._insert_subscription(
                    conn, acc_id, prog_id,
                    valor_contrato, milhas_contrato, dt_inicio, data_renov_dt,
                )
                if insert_result is None:
                    return "❌ Erro: Não foi possível criar a assinatura."
                _, cpm_calculado = insert_result

                conn.commit()
                return (
                    f"✅ **Assinatura Criada com Sucesso!**\n"
                    f"📋 **Tipo:** {tipo_contrato}\n"
                    f"📊 **Contrato Anual:** {milhas_contrato:,} milhas\n"
                    f"💰 **Valor Global:** R$ {valor_contrato:.2f}\n"
                    f"📉 **CPM Travado:** R$ {cpm_calculado:.2f}\n"
                    f"� **Início:** {dt_inicio.strftime('%d/%m/%Y')}\n"
                    f"�🔄 **Renovação:** {data_renov_dt.strftime('%d/%m/%Y')}\n"
                    f"✅ **Status:** Ativo\n"
                    f"ℹ️ *Nota: O sistema baixará 1/12 desse saldo a cada mensalidade.*"
                )

        except Exception as e:
            return _sanitize_error("register_subscription", e)
        

    @log_tool_call
    def correct_last_subscription(self,
                                nome_conta: str, 
                                nome_programa: str, 
                                valor_total_ciclo: float, 
                                milhas_garantidas_ciclo: int, 
                                data_renovacao: str,
                                data_inicio: Optional[str] = None,
                                is_mensal: bool = False) -> str:
        """
        CORREÇÃO: Desativa a assinatura ativa mais recente do programa informado e cria uma nova
        com os dados corrigidos. As transações vinculadas são re-linkadas ao novo contrato,
        preservando o histórico e a trava de segurança de créditos mensais.
        Use ISSO quando o usuário disser 'Errei o valor', 'Corrige a data', etc.

        IMPORTANTE: nome_programa é obrigatório — confirme com o usuário qual clube
        precisa ser corrigido antes de chamar esta ferramenta.

        Args:
            nome_programa: Nome do programa/clube a corrigir. SEMPRE confirmar com o usuário.
            valor_total_ciclo: Valor monetário do ciclo (mensal ou anual, dependendo de is_mensal).
            milhas_garantidas_ciclo: Quantidade de milhas do ciclo (mensal ou anual).
            data_renovacao: Data de renovação FUTURA. Aceita linguagem natural.
            data_inicio: Data de início da assinatura (opcional). Pode ser no passado.
            is_mensal: Se True, multiplica os valores por 12 para criar o contrato anual.
        """
        try:
            # 1. Valida e normaliza parâmetros antes de abrir conexão (fail-fast).
            err, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt, tipo_contrato = \
                self._parse_subscription_params(
                    valor_total_ciclo, milhas_garantidas_ciclo,
                    data_renovacao, data_inicio, is_mensal,
                )
            if err:
                return err
            # _parse_subscription_params garante que, sem erro, todos os campos são não-None.
            if valor_contrato is None or milhas_contrato is None or dt_inicio is None \
                    or data_renov_dt is None or tipo_contrato is None:
                return _sanitize_error("correct_last_subscription", ValueError("parse retornou None inesperado"))

            # 2. UMA conexão, UMA transação — tudo atômico
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                # 3. Desativa a assinatura ativa mais recente do programa (sem deletar)
                #    O trigger trg_maintain_consistency seta ativo=FALSE automaticamente ao preencher data_fim
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE subscriptions
                        SET data_fim = CURRENT_DATE
                        WHERE id = (
                            SELECT id FROM subscriptions
                            WHERE account_id = %s AND programa_id = %s AND ativo = TRUE
                            ORDER BY created_at DESC
                            LIMIT 1
                        )
                        RETURNING id;
                    """, (acc_id, prog_id), prepare=False)
                    row = cur.fetchone()
                old_sub_id = str(row[0]) if row else None

                msg_anterior = (
                    "(Anterior desativada — histórico preservado)"
                    if old_sub_id else
                    "(Nenhuma ativa encontrada — criando nova)"
                )

                # 4. Cria nova assinatura corrigida na mesma conexão
                insert_result = self._insert_subscription(
                    conn, acc_id, prog_id,
                    valor_contrato, milhas_contrato, dt_inicio, data_renov_dt,
                )
                if insert_result is None:
                    return "❌ Erro: Não foi possível criar a nova assinatura. A correção foi cancelada."
                new_sub_id, cpm_calculado = insert_result

                # 5. Re-vincula transações anteriores ao novo subscription_id
                #    Mantém a trava de segurança de process_monthly_credit funcionando
                if old_sub_id:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE transactions
                            SET subscription_id = %s
                            WHERE subscription_id = %s
                        """, (new_sub_id, old_sub_id), prepare=False)

                # 6. Único commit — desativação + inserção + re-vínculo sobem juntos
                conn.commit()

            return (
                f"✅ **Assinatura Corrigida com Sucesso!** {msg_anterior}\n"
                f"📋 **Tipo:** {tipo_contrato}\n"
                f"📊 **Contrato Anual:** {milhas_contrato:,} milhas\n"
                f"💰 **Valor Global:** R$ {valor_contrato:.2f}\n"
                f"📉 **CPM Travado:** R$ {cpm_calculado:.2f}\n"
                f"📅 **Início:** {dt_inicio.strftime('%d/%m/%Y')}\n"
                f"🔄 **Renovação:** {data_renov_dt.strftime('%d/%m/%Y')}\n"
                f"✅ **Status:** Ativo"
            )

        except Exception as e:
            return _sanitize_error("correct_last_subscription", e)

    # ── Ferramentas públicas: deleção com confirmação em 2 etapas ────────────

    @log_tool_call
    def delete_last_transaction(self,
                               nome_conta: str,
                               nome_programa: Optional[str] = None) -> str:
        """
        Etapa 1/2: Exibe a última transação da conta para revisão antes de deletar.

        ⚠️ REGRA DE SEGURANÇA: Só é seguro apagar a ÚLTIMA transação.
        Transações anteriores já influenciaram o CPM das seguintes.

        Retorna um resumo da transação com o transaction_id necessário para
        confirmar a deleção via confirm_delete_transaction(transaction_id=...).
        Mostre o resumo ao usuário e aguarde confirmação explícita antes de prosseguir.

        Args:
            nome_conta:    Nome, CPF ou UUID da conta.
            nome_programa: Filtro opcional por programa. Use quando a conta tem
                           múltiplas transações recentes e precisa de precisão.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."

                # Monta a query de busca com filtro opcional de programa
                with conn.cursor() as cur:
                    if nome_programa:
                        prog_id = self._get_program_id(conn, nome_programa)
                        if not prog_id:
                            return f"❌ Programa '{nome_programa}' não encontrado."
                        cur.execute("""
                            SELECT t.id, p.nome, t.modo_aquisicao,
                                   t.milhas_base, t.bonus_percent, t.milhas_creditadas,
                                   t.custo_total, t.cpm_real, t.data_transacao,
                                   t.descricao, t.subscription_id
                            FROM transactions t
                            JOIN programs p ON p.id = t.companhia_referencia_id
                            WHERE t.account_id = %s AND t.companhia_referencia_id = %s
                            ORDER BY t.created_at DESC
                            LIMIT 1
                        """, (acc_id, prog_id))
                    else:
                        cur.execute("""
                            SELECT t.id, p.nome, t.modo_aquisicao,
                                   t.milhas_base, t.bonus_percent, t.milhas_creditadas,
                                   t.custo_total, t.cpm_real, t.data_transacao,
                                   t.descricao, t.subscription_id
                            FROM transactions t
                            JOIN programs p ON p.id = t.companhia_referencia_id
                            WHERE t.account_id = %s
                            ORDER BY t.created_at DESC
                            LIMIT 1
                        """, (acc_id,))

                    row = cur.fetchone()
                    if not row:
                        filtro = f" no programa '{nome_programa}'" if nome_programa else ""
                        return f"❌ Nenhuma transação encontrada para {acc_nome}{filtro}."

                    tx_id, prog_nome, modo, milhas_base, bonus_pct, milhas_cred, \
                        custo, cpm, data_tx, descricao, sub_id = row

                    aviso_clube = (
                        "\n⚠️ *Esta transação pertence a uma assinatura. "
                        "Deletá-la altera o progresso do contrato.*"
                    ) if sub_id else ""

                    # Verifica se existe checkpoint criado após esta transação
                    # (significaria que a transação está na base do snapshot e corromperia o checkpoint)
                    cur.execute("""
                        SELECT tipo, cpm_snapshot, periodo_referencia
                        FROM cpm_checkpoints
                        WHERE account_id = %s
                          AND programa_id = (SELECT companhia_referencia_id FROM transactions WHERE id = %s)
                          AND created_at > (SELECT created_at FROM transactions WHERE id = %s)
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (acc_id, tx_id, tx_id))
                    chk = cur.fetchone()
                    if chk:
                        chk_tipo, chk_cpm, chk_ref = chk
                        ref_txt = f" ({chk_ref})" if chk_ref else f" ({chk_tipo})"
                        aviso_checkpoint = (
                            f"\n🚨 *Esta transação está incluída em um checkpoint de CPM{ref_txt} "
                            f"(CPM confirmado: R$ {float(chk_cpm):.2f}). "
                            f"Deletá-la invalidará esse checkpoint, que será removido automaticamente.*"
                        )
                    else:
                        aviso_checkpoint = ""

                    bonus_info = f" + {int(bonus_pct)}% bônus" if bonus_pct else ""
                    resumo = (
                        f"📋 **Última transação de {acc_nome}:**\n"
                        f"- Programa : {prog_nome}\n"
                        f"- Modo     : {modo}\n"
                        f"- Milhas   : {milhas_base:,} base{bonus_info} → {milhas_cred:,} creditadas\n"
                        f"- Custo    : R$ {custo:.2f} | CPM R$ {cpm:.2f}\n"
                        f"- Data     : {data_tx.strftime('%d/%m/%Y') if data_tx else 'N/A'}\n"
                        f"- Descrição: {descricao or '—'}"
                        f"{aviso_clube}"
                        f"{aviso_checkpoint}"
                    )

                    return (
                        f"{resumo}\n\n"
                        f"❓ Confirma a exclusão? Se sim, chame `confirm_delete_transaction`"
                        f" com `transaction_id='{tx_id}'`."
                    )

        except Exception as e:
            return _sanitize_error("delete_last_transaction", e)

    @log_tool_call
    def confirm_delete_transaction(self, transaction_id: str) -> str:
        """
        Etapa 2/2: Executa a deleção de uma transação previamente exibida em preview.
        Requer o transaction_id retornado por delete_last_transaction().

        ⚠️ Só chame após mostrar o preview ao usuário e obter confirmação explícita.
        transaction_batches vinculados são removidos automaticamente (ON DELETE CASCADE).
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT t.id, p.nome, t.milhas_creditadas, t.custo_total, t.data_transacao,
                               t.account_id, t.companhia_referencia_id, t.created_at
                        FROM transactions t
                        JOIN programs p ON p.id = t.companhia_referencia_id
                        WHERE t.id = %s
                    """, (transaction_id,))
                    row = cur.fetchone()
                    if not row:
                        return "❌ Transação não encontrada. Verifique o ID ou execute o preview novamente."

                    tx_id, prog_nome, milhas, custo, data_tx, acc_id, prog_id_ref, tx_created_at = row

                    # Remove checkpoints que incluíam esta transação na sua base
                    cur.execute("""
                        DELETE FROM cpm_checkpoints
                        WHERE account_id = %s AND programa_id = %s AND created_at > %s
                        RETURNING tipo, periodo_referencia, cpm_snapshot
                    """, (acc_id, prog_id_ref, tx_created_at))
                    chks_removidos = cur.fetchall()

                    cur.execute("DELETE FROM transactions WHERE id = %s", (tx_id,), prepare=False)
                conn.commit()

            data_fmt = data_tx.strftime('%d/%m/%Y') if data_tx else 'N/A'
            aviso_chk = ""
            if chks_removidos:
                descricoes = []
                for tipo, ref, snap in chks_removidos:
                    ref_txt = f" ({ref})" if ref else f" ({tipo})"
                    descricoes.append(f"CPM R$ {float(snap):.2f}{ref_txt}")
                aviso_chk = (
                    f"\n🗑️ Checkpoint(s) invalidado(s) e removido(s): {', '.join(descricoes)}.\n"
                    f"   O histórico de CPM precisará ser reconfirmado."
                )

            return (
                f"🗑️ **Transação deletada com sucesso!**\n"
                f"- Programa: {prog_nome} | {milhas:,} milhas | R$ {custo:.2f} | {data_fmt}"
                f"{aviso_chk}\n\n"
                f"✅ O registro foi removido. Você pode lançar novamente com os dados corretos."
            )
        except Exception as e:
            return _sanitize_error("confirm_delete_transaction", e)

    @log_tool_call
    def process_monthly_credit(self, nome_conta: str, nome_programa: str, milhas_do_mes: int = 0) -> str:
        """
        Registra a entrada mensal de milhas de um clube de assinatura.

        Aplica uma trava de segurança: bloqueia o crédito se a soma de todas as
        entradas anteriores mais a nova parcela ultrapassar o total contratado no ciclo.
        Isso previne sobrecrédito acidental por parte do agente.

        Args:
            milhas_do_mes: Quantidade a creditar neste mês. Se omitido ou zero,
                calcula automaticamente 1/12 do contrato (média linear mensal).
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: return f"❌ Programa '{nome_programa}' não encontrado."

                with conn.cursor() as cur:
                    # 1. Busca os dados do CONTRATO com lock exclusivo para evitar race condition.
                    # FOR UPDATE bloqueia a linha da assinatura até o commit, garantindo que
                    # execuções concorrentes para a mesma assinatura aguardem e nunca passem
                    # pela validação de saldo com dados desatualizados.
                    cur.execute("""
                        SELECT id, cpm_fixo, milhas_garantidas_ciclo, valor_total_ciclo
                        FROM subscriptions
                        WHERE account_id = %s AND programa_id = %s AND ativo = TRUE
                        ORDER BY created_at DESC
                        LIMIT 1
                        FOR UPDATE
                    """, (acc_id, prog_id))
                    
                    sub = cur.fetchone()
                    if not sub: return f"❌ Nenhuma assinatura ativa encontrada para {acc_nome} no programa {nome_programa}."
                    
                    sub_id, cpm_fixo, milhas_totais_contrato, valor_anual = sub

                    # 2. Define a Quantidade
                    if milhas_do_mes > 0:
                        qtd_inserir = milhas_do_mes
                        obs_origem = "(Manual)"
                    else:
                        qtd_inserir = int(milhas_totais_contrato / 12)
                        obs_origem = "(Média linear)"

                    # Trava de segurança: soma todas as milhas já creditadas nesta assinatura
                    # e verifica se há saldo suficiente para a nova parcela.
                    cur.execute("""
                        SELECT COALESCE(SUM(milhas_creditadas), 0)
                        FROM transactions
                        WHERE subscription_id = %s
                    """, (sub_id,))
                    result = cur.fetchone()
                    total_ja_creditado = result[0] if result else 0
                    saldo_restante = milhas_totais_contrato - total_ja_creditado

                    if qtd_inserir > saldo_restante:
                        return (
                            f"⛔ **BLOQUEIO DE SEGURANÇA**\n"
                            f"Você tentou creditar **{qtd_inserir}** milhas, mas este contrato só tem **{saldo_restante}** milhas pendentes.\n\n"
                            f"📊 **Resumo do Contrato:**\n"
                            f"- Total Contratado: {milhas_totais_contrato}\n"
                            f"- Já Creditado: {total_ja_creditado}\n"
                            f"- Restante: {saldo_restante}\n\n"
                            # MUDANÇA AQUI: Texto menos "sugestivo" para o Agente
                            f"💡 *Dica: Se isso for um bônus extra, solicite uma nova operação de 'Compra Avulsa' ou 'Bônus' separadamente.*" 
                        )

                    # 3. Cálculo do custo contábil proporcional à parcela creditada.
                    custo_contabil = (qtd_inserir / 1000) * float(cpm_fixo)

                    # Usa o CPM fixo do contrato diretamente (sem recalcular sobre float)
                    # para evitar dízimas e garantir consistência com o valor travado na assinatura.
                    # Modo CLUBE_ASSINATURA distingue créditos de contrato de compras avulsas.
                    cur.execute("""
                        INSERT INTO transactions
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, subscription_id)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s)
                    """, (
                        acc_id,
                        ModoAquisicao.CLUBE.value,
                        prog_id, prog_id, prog_id,  # origem/destino/ref = programa (operação interna)
                        qtd_inserir,                # milhas_base
                        qtd_inserir,                # milhas_creditadas (sem bônus em créditos de clube)
                        custo_contabil,
                        cpm_fixo,
                        f'Crédito Mensal Clube - {nome_programa}',
                        sub_id
                    ), prepare=False)
                    
                    # Verifica Fim de Ciclo
                    aviso_fim = ""
                    if (saldo_restante - qtd_inserir) == 0:
                        aviso_fim = "\n🏁 **Atenção:** O saldo deste contrato zerou! O ciclo anual foi concluído."

                    conn.commit()
                    
                    percentual_concluido = ((total_ja_creditado + qtd_inserir) / milhas_totais_contrato) * 100
                    
                    return (
                        f"✅ Crédito registrado com sucesso!\n"
                        f"📊 +{qtd_inserir} milhas {obs_origem}\n"
                        f"💰 Custo Contábil: R$ {custo_contabil:.2f} (CPM R$ {cpm_fixo:.2f})\n"
                        f"📉 Progresso do Contrato: {percentual_concluido:.1f}% concluído.{aviso_fim}"
                    )

        except Exception as e:
            return _sanitize_error("process_monthly_credit", e)
        

    @log_tool_call
    def register_intra_club_transaction(self,
                                      nome_conta: str,
                                      nome_programa: str,
                                      milhas: int,
                                      custo_total: float,
                                      descricao: str,
                                      bonus_percent: float = 0.0) -> str:
        """
        Registra uma transação avulsa dentro de um clube de assinatura ativo.
        Usada para bônus pontuais, compras adicionais e créditos orgânicos do clube
        que não fazem parte da recorrência mensal.

        Args:
            milhas: Milhas base da operação (antes do bônus).
            custo_total: Custo em reais. Se zero ou negativo, registra como ORGANICO.
            descricao: Texto descritivo fornecido pelo usuário ou agente.
            bonus_percent: Percentual de bônus sobre as milhas base (ex: 25 para 25%).
        """
        try:
            milhas_base = int(milhas)
            bonus = float(bonus_percent)
            # Milhas finais = base + bônus proporcional
            total_milhas = int(milhas_base * (1 + bonus / 100))

            if custo_total <= 0:
                modo = ModoAquisicao.ORGANICO.value
                custo_final = 0.0
                tag_desc = "(Bônus/Orgânico Clube)"
            else:
                modo = ModoAquisicao.COMPRA_SIMPLES.value
                custo_final = float(custo_total)
                tag_desc = f"(Compra Clube + {int(bonus)}% Bônus)"

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: return f"❌ Programa '{nome_programa}' não encontrado."

                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM subscriptions
                        WHERE account_id = %s AND programa_id = %s AND ativo = TRUE
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (acc_id, prog_id))
                    
                    sub = cur.fetchone()
                    if not sub:
                        return f"❌ Operação negada: Cliente sem Clube Ativo na {nome_programa}."
                    sub_id = sub[0]

                    # CPM Real baseado no TOTAL creditado
                    cpm_transacao = (custo_final / total_milhas * 1000) if total_milhas > 0 else 0

                    full_desc = f"{descricao} {tag_desc}"
                    
                    cur.execute("""
                        INSERT INTO transactions
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, subscription_id)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        acc_id,
                        modo,
                        prog_id, prog_id, prog_id,
                        milhas_base,
                        bonus,
                        total_milhas,
                        custo_final,
                        cpm_transacao,
                        full_desc,
                        sub_id
                    ), prepare=False)
                    
                    conn.commit()
                    
                    return (
                        f"✅ **Transação Intra-Clube Registrada!**\n"
                        f"🔢 **Estrutura:** {milhas_base} milhas + {int(bonus)}% bônus\n"
                        f"🛒 **Total Creditado:** {total_milhas} milhas\n"
                        f"💸 **Custo:** R$ {custo_final:.2f}\n"
                        f"📉 **CPM:** R$ {cpm_transacao:.2f}"
                    )

        except Exception as e:
            return _sanitize_error("register_intra_club_transaction", e)

    # ── Protocolo de CPM: helpers privados ───────────────────────────────────

    def _get_cpm_totals(self, conn: psycopg.Connection, acc_id: str, prog_id: str):
        """
        Retorna (total_milhas, total_custo, checkpoint, delta) combinando o
        último checkpoint com as transações posteriores.

        Padrão base + delta:
          - Se há checkpoint: total = snapshot acumulado + transações POSTERIORES à data do checkpoint.
            Isso torna a reconciliação incremental — não relê o histórico inteiro a cada consulta.
          - Se não há checkpoint: total = soma de TODAS as transações do programa.

        Retornos:
            total_milhas: milhas acumuladas (base + delta)
            total_custo:  custo acumulado (base + delta)
            checkpoint:   dict com campos do registro, ou None se não houver
            delta:        tupla (count, sum_milhas, sum_custo, min_dt, max_dt, count_ajustes)
        """
        checkpoint = None
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, total_milhas, total_custo, cpm_snapshot, created_at,
                       tipo, periodo_referencia
                FROM cpm_checkpoints
                WHERE account_id = %s AND programa_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (acc_id, prog_id))
            row = cur.fetchone()
            if row:
                checkpoint = {
                    "id": row[0], "total_milhas": row[1], "total_custo": float(row[2]),
                    "cpm_snapshot": float(row[3]), "created_at": row[4],
                    "tipo": row[5], "periodo_referencia": row[6],
                }

            # Filtra apenas as transações posteriores ao checkpoint (se existir),
            # evitando reprocessar o histórico já consolidado no snapshot.
            cutoff = checkpoint["created_at"] if checkpoint else None
            if cutoff:
                cur.execute("""
                    SELECT COUNT(*),
                           COALESCE(SUM(milhas_creditadas), 0),
                           COALESCE(SUM(custo_total), 0),
                           MIN(data_transacao),
                           MAX(data_transacao),
                           COUNT(*) FILTER (WHERE modo_aquisicao = 'AJUSTE_CPM')
                    FROM transactions
                    WHERE account_id = %s AND companhia_referencia_id = %s
                      AND created_at > %s
                """, (acc_id, prog_id, cutoff))
            else:
                cur.execute("""
                    SELECT COUNT(*),
                           COALESCE(SUM(milhas_creditadas), 0),
                           COALESCE(SUM(custo_total), 0),
                           MIN(data_transacao),
                           MAX(data_transacao),
                           COUNT(*) FILTER (WHERE modo_aquisicao = 'AJUSTE_CPM')
                    FROM transactions
                    WHERE account_id = %s AND companhia_referencia_id = %s
                """, (acc_id, prog_id))
            delta = cur.fetchone() or (0, 0, 0.0, None, None, 0)

        base_milhas = checkpoint["total_milhas"] if checkpoint else 0
        base_custo  = checkpoint["total_custo"]  if checkpoint else 0.0
        total_milhas = base_milhas + int(delta[1] or 0)
        total_custo  = base_custo  + float(delta[2] or 0)
        return total_milhas, total_custo, checkpoint, delta

    def _build_checkpoint_descricao(
        self, tipo: str, programa_nome: str,
        periodo_referencia: Optional[str] = None,
        tipo_ajuste: Optional[str] = None,
        valor_ajuste: Optional[float] = None,
    ) -> str:
        """Gera a descrição automática do checkpoint conforme o tipo."""
        if tipo == "MENSAL":
            ano, mes = map(int, (periodo_referencia or "").split("-"))
            return f"Fechamento {_MESES_PT[mes]}/{ano} — {programa_nome}"
        elif tipo == "AUTO":
            if tipo_ajuste == "CUSTO":
                return f"[Auto] Pós-ajuste de custo: {(valor_ajuste or 0):+.2f} — {programa_nome}"
            else:
                return f"[Auto] Pós-ajuste de milhas: {int(valor_ajuste or 0):+,} mi — {programa_nome}"
        else:
            return f"Confirmação de CPM — {programa_nome}"

    def _insert_cpm_checkpoint(
        self, conn: psycopg.Connection,
        acc_id: str, prog_id: str, programa_nome: str,
        tipo: str, total_milhas: int, total_custo: float, delta: Optional[tuple],
        periodo_referencia: Optional[str] = None,
        observacao: Optional[str] = None,
        tipo_ajuste: Optional[str] = None,
        valor_ajuste: Optional[float] = None,
    ) -> str:
        """
        Insere em cpm_checkpoints. Não faz commit — responsabilidade do chamador.
        Retorna o id do checkpoint criado.
        """
        cpm_snapshot = round(total_custo / total_milhas * 1000, 2) if total_milhas > 0 else 0.0
        descricao = self._build_checkpoint_descricao(
            tipo, programa_nome, periodo_referencia, tipo_ajuste, valor_ajuste
        )
        delta_inicio = delta[3] if delta else None
        delta_fim    = delta[4] if delta else None

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO cpm_checkpoints
                (account_id, programa_id, data_checkpoint, total_milhas, total_custo,
                 cpm_snapshot, tipo, periodo_referencia, delta_data_inicio, delta_data_fim,
                 descricao, observacao)
                VALUES (%s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                acc_id, prog_id, total_milhas, total_custo, cpm_snapshot,
                tipo, periodo_referencia, delta_inicio, delta_fim,
                descricao, observacao,
            ))
            row = cur.fetchone()
            return str(row[0]) if row else ""

    # ── Protocolo de CPM: ferramentas públicas ───────────────────────────────

    @log_tool_call
    def confirm_cpm_checkpoint(
        self,
        nome_conta: str,
        nome_programa: str,
        tipo: str,
        periodo_referencia: Optional[str] = None,
        observacao: Optional[str] = None,
    ) -> str:
        """
        Cria um checkpoint de CPM confirmando que o estado atual está correto.

        tipo: 'MENSAL' (fechamento de mês), 'MANUAL' (confirmação pontual).
        periodo_referencia: obrigatório para tipo='MENSAL', formato 'YYYY-MM'
            (ex: '2026-01' para fechar janeiro/2026).
        observacao: campo livre opcional do usuário.
        """
        try:
            tipo = tipo.upper().strip()
            if tipo not in ("MENSAL", "MANUAL"):
                return "❌ tipo deve ser 'MENSAL' ou 'MANUAL'."
            if tipo == "MENSAL":
                if not periodo_referencia:
                    return "❌ Para tipo='MENSAL', informe o periodo_referencia no formato 'YYYY-MM'."
                try:
                    ano, mes = map(int, periodo_referencia.split("-"))
                    if not (1 <= mes <= 12):
                        raise ValueError
                except ValueError:
                    return f"❌ periodo_referencia inválido: '{periodo_referencia}'. Use o formato 'YYYY-MM'."
                hoje_ref = date.today()
                if (ano, mes) > (hoje_ref.year, hoje_ref.month):
                    return f"❌ Não é possível fechar um mês futuro ({periodo_referencia})."

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                if tipo == "MENSAL":
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id FROM cpm_checkpoints
                            WHERE account_id = %s AND programa_id = %s
                              AND periodo_referencia = %s
                        """, (acc_id, prog_id, periodo_referencia))
                        if cur.fetchone():
                            ano, mes = map(int, (periodo_referencia or "").split("-"))
                            return (
                                f"⛔ {_MESES_PT[mes].capitalize()}/{ano} já foi fechado para "
                                f"{nome_programa} / {acc_nome}. Não é possível duplicar o fechamento."
                            )

                total_milhas, total_custo, _, delta = self._get_cpm_totals(conn, acc_id, prog_id)
                if total_milhas <= 0:
                    return f"❌ Nenhuma transação encontrada para {nome_programa} / {acc_nome}."

                try:
                    self._insert_cpm_checkpoint(
                        conn, acc_id, prog_id, nome_programa,
                        tipo, total_milhas, total_custo, delta,
                        periodo_referencia=periodo_referencia,
                        observacao=observacao,
                    )
                    conn.commit()
                except psycopg.errors.UniqueViolation:
                    conn.rollback()
                    ano_dup, mes_dup = map(int, (periodo_referencia or "").split("-"))
                    return (
                        f"⛔ {_MESES_PT[mes_dup].capitalize()}/{ano_dup} já foi fechado para "
                        f"{nome_programa} / {acc_nome}. Não é possível duplicar o fechamento."
                    )

                cpm = round(total_custo / total_milhas * 1000, 2)
                tag = f"[Fechamento: {periodo_referencia}]" if tipo == "MENSAL" else f"[{tipo}]"
                periodo_txt = ""
                if delta and delta[3] and delta[4]:
                    dt_ini, dt_fim = delta[3], delta[4]
                    periodo_txt = f"\n   Período coberto: {dt_ini.strftime('%d/%m')} a {dt_fim.strftime('%d/%m/%Y')}"

                return (
                    f"✅ Checkpoint de CPM registrado! {tag}\n"
                    f"📊 {nome_programa} / {acc_nome} — {date.today().strftime('%d/%m/%Y')}"
                    f"{periodo_txt}\n"
                    f"   Total acumulado: {total_milhas:,} milhas | R$ {total_custo:,.2f}\n"
                    f"   **CPM confirmado: R$ {cpm:.2f}**\n\n"
                    f"ℹ️ Próximas reconciliações partirão deste ponto."
                )

        except Exception as e:
            return _sanitize_error("confirm_cpm_checkpoint", e)

    @log_tool_call
    def get_cpm_summary(self, nome_conta: str, nome_programa: str) -> str:
        """
        Retorna um resumo compacto do estado atual de CPM para uma conta e programa.
        Parte do último checkpoint (se houver) e mostra o delta de transações novas.
        Sinaliza se há mais de 10 transações sem checkpoint (sugestão de confirmação).
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                total_milhas, total_custo, checkpoint, delta = self._get_cpm_totals(
                    conn, acc_id, prog_id
                )

            if total_milhas <= 0:
                return f"❌ Nenhuma transação encontrada para {nome_programa} / {acc_nome}."

            cpm_atual = round(total_custo / total_milhas * 1000, 2)
            delta_count    = int(delta[0] or 0)
            delta_milhas   = int(delta[1] or 0)
            delta_custo    = float(delta[2] or 0)
            delta_ajustes  = int(delta[5] or 0)

            if checkpoint:
                chk_data = checkpoint["created_at"].strftime("%d/%m/%Y")
                chk_tipo = checkpoint["tipo"]
                chk_cpm  = checkpoint["cpm_snapshot"]
                chk_ref  = f" ({checkpoint['periodo_referencia']})" if checkpoint["periodo_referencia"] else f" ({chk_tipo})"
                chk_line = f"Último checkpoint: {chk_data}{chk_ref} — CPM confirmado: **R$ {chk_cpm:.2f}**"
            else:
                chk_line = "Sem checkpoint anterior — análise de todo o histórico"

            ajuste_line = f"\n  Ajustes de CPM aplicados: {delta_ajustes}" if delta_ajustes > 0 else ""
            aviso_volume = ""
            if delta_count > 10:
                aviso_volume = (
                    f"\n\n📌 Há {delta_count} transações sem checkpoint (limite: 10). "
                    "Se o CPM estiver correto, posso confirmar agora para agilizar futuras reconciliações."
                )

            return (
                f"📊 Resumo CPM — {nome_programa} / {acc_nome}\n"
                f"─────────────────────────────────\n"
                f"{chk_line}\n"
                f"Transações desde então: {delta_count}\n"
                f"  Milhas novas: +{delta_milhas:,}  |  Custo novo: R$ {delta_custo:,.2f}"
                f"{ajuste_line}\n\n"
                f"Posição atual:\n"
                f"  Total acumulado: {total_milhas:,} milhas | R$ {total_custo:,.2f}\n"
                f"  **CPM Médio atual: R$ {cpm_atual:.2f}**"
                f"{aviso_volume}"
            )

        except Exception as e:
            return _sanitize_error("get_cpm_summary", e)

    @log_tool_call
    def calculate_cpm_adjustment(
        self, nome_conta: str, nome_programa: str, cpm_alvo: float
    ) -> str:
        """
        Calcula o ajuste necessário para atingir um CPM-alvo.
        Não cria nada — apenas calcula e retorna as opções.

        cpm_alvo: CPM desejado em R$/milheiro (ex: 18.00).
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                total_milhas, total_custo, _, _ = self._get_cpm_totals(conn, acc_id, prog_id)

            if total_milhas <= 0:
                return f"❌ Nenhuma transação encontrada para {nome_programa} / {acc_nome}."

            cpm_atual = round(total_custo / total_milhas * 1000, 2)

            if abs(cpm_atual - cpm_alvo) < 0.01:
                return (
                    f"✅ O CPM atual de {nome_programa} / {acc_nome} já é **R$ {cpm_atual:.2f}** "
                    "— nenhum ajuste necessário."
                )

            # Opção A: ajuste de custo (milhas não mudam)
            delta_custo = round(cpm_alvo * total_milhas / 1000 - total_custo, 2)

            linhas = [
                f"🎯 Para atingir CPM de **R$ {cpm_alvo:.2f}** (atual: R$ {cpm_atual:.2f}) "
                f"— {nome_programa} / {acc_nome}:\n",
                f"Opção A — Ajuste de custo:",
                f"  {'Reduzir' if delta_custo < 0 else 'Adicionar'} R$ {abs(delta_custo):.2f} no custo registrado",
                f"  (sem alterar milhas)\n",
            ]

            # Opção B: adicionar milhas (só faz sentido se cpm_alvo < cpm_atual)
            if cpm_alvo < cpm_atual:
                delta_milhas = round(total_custo / cpm_alvo * 1000 - total_milhas)
                linhas += [
                    f"Opção B — Crédito de milhas grátis:",
                    f"  Adicionar {delta_milhas:,} milhas sem custo",
                    f"  (dilui o custo existente)\n",
                ]
            else:
                linhas.append("Opção B — indisponível (CPM-alvo acima do atual; não é possível diluir com milhas grátis)\n")

            linhas.append("Qual prefere? (A ou B)")
            return "\n".join(linhas)

        except Exception as e:
            return _sanitize_error("calculate_cpm_adjustment", e)

    @log_tool_call
    def apply_cpm_adjustment(
        self,
        nome_conta: str,
        nome_programa: str,
        tipo_ajuste: str,
        valor: float,
        observacao: Optional[str] = None,
    ) -> str:
        """
        Cria uma transação de ajuste de CPM (AJUSTE_CPM) e registra um checkpoint
        automático. Use somente após confirmação explícita do usuário.

        tipo_ajuste: 'CUSTO' (altera custo sem mudar milhas) ou
                     'MILHAS' (adiciona milhas sem custo).
        valor: delta a aplicar. Para CUSTO: positivo ou negativo.
               Para MILHAS: apenas positivo (inteiro).
        """
        try:
            tipo_ajuste = tipo_ajuste.upper().strip()
            if tipo_ajuste not in ("CUSTO", "MILHAS"):
                return "❌ tipo_ajuste deve ser 'CUSTO' ou 'MILHAS'."
            if valor == 0:
                return "❌ valor não pode ser zero."
            if tipo_ajuste == "MILHAS" and (valor < 0 or not float(valor).is_integer()):
                return "❌ Para tipo_ajuste='MILHAS', valor deve ser inteiro positivo."

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id:
                    return f"❌ Programa '{nome_programa}' não encontrado."

                if tipo_ajuste == "CUSTO":
                    _, total_custo_pre, _, _ = self._get_cpm_totals(conn, acc_id, prog_id)
                    custo_resultante = total_custo_pre + float(valor)
                    if custo_resultante < 0:
                        return (
                            f"❌ Ajuste inválido: o valor informado tornaria o custo total negativo "
                            f"(resultado seria R$ {custo_resultante:,.2f}). "
                            f"Consulte primeiro o cálculo de ajuste para obter o valor correto."
                        )
                    milhas_base = milhas_credit = 0
                    custo = float(valor)
                    descricao_tx = f"Ajuste de CPM: correção de custo ({valor:+.2f})"
                else:
                    milhas_base = milhas_credit = int(valor)
                    custo = 0.0
                    descricao_tx = f"Ajuste de CPM: crédito de {int(valor):,} milhas sem custo"

                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO transactions
                        (account_id, data_registro, data_transacao, modo_aquisicao,
                         origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas,
                         custo_total, cpm_real, descricao, observacao)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, 'AJUSTE_CPM',
                                NULL, %s, %s,
                                %s, 0, %s,
                                %s, 0, %s, %s)
                    """, (
                        acc_id, prog_id, prog_id,
                        milhas_base, milhas_credit,
                        custo, descricao_tx, observacao,
                    ))

                # Checkpoint AUTO criado imediatamente após o ajuste, na mesma transação de banco.
                # Isso garante que reconciliações futuras partam do estado pós-ajuste,
                # sem reprocessar o delta antigo que motivou o ajuste.
                total_milhas, total_custo, _, delta = self._get_cpm_totals(conn, acc_id, prog_id)
                self._insert_cpm_checkpoint(
                    conn, acc_id, prog_id, nome_programa,
                    "AUTO", total_milhas, total_custo, delta,
                    tipo_ajuste=tipo_ajuste, valor_ajuste=float(valor),
                    observacao=observacao,
                )
                conn.commit()

            cpm_novo = round(total_custo / total_milhas * 1000, 2) if total_milhas > 0 else 0.0
            if tipo_ajuste == "CUSTO":
                detalhe = f"custo {'reduzido' if valor < 0 else 'adicionado'} em R$ {abs(valor):.2f}"
            else:
                detalhe = f"{int(valor):,} milhas creditadas sem custo"

            return (
                f"✅ Ajuste de CPM aplicado!\n"
                f"📊 {nome_programa} / {acc_nome}: {detalhe}\n"
                f"💡 **Novo CPM: R$ {cpm_novo:.2f}**\n"
                f"📌 Checkpoint criado automaticamente."
            )

        except Exception as e:
            return _sanitize_error("apply_cpm_adjustment", e)

    @log_tool_call
    def get_client_panorama(self, nome_conta: str) -> str:
        """
        Retorna uma visão geral de todos os programas do cliente com status de CPM
        e saúde de checkpoint. Útil para identificar programas que precisam de atenção.
        """
        try:
            hoje = date.today()
            mes_anterior = f"{hoje.year}-{hoje.month - 1:02d}" if hoje.month > 1 else f"{hoje.year - 1}-12"

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id:
                    return f"❌ Conta '{nome_conta}' não encontrada."

                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT t.companhia_referencia_id, p.nome
                        FROM transactions t
                        JOIN programs p ON p.id = t.companhia_referencia_id
                        WHERE t.account_id = %s
                        ORDER BY p.nome
                    """, (acc_id,))
                    programas = cur.fetchall()

                if not programas:
                    return f"❌ Nenhuma transação encontrada para {acc_nome}."

                linhas = []
                total_geral = 0
                alertas = []

                for prog_id, prog_nome in programas:
                    total_milhas, total_custo, checkpoint, delta = self._get_cpm_totals(
                        conn, acc_id, prog_id
                    )
                    if total_milhas <= 0:
                        continue

                    cpm = round(total_custo / total_milhas * 1000, 2)
                    delta_count = int(delta[0] or 0)

                    # Verifica fechamento mensal do mês anterior
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id FROM cpm_checkpoints
                            WHERE account_id = %s AND programa_id = %s
                              AND periodo_referencia = %s
                        """, (acc_id, prog_id, mes_anterior))
                        tem_mensal = cur.fetchone() is not None

                    # Status de saúde
                    if not checkpoint:
                        status = "🔴 SEM CHECKPOINT"
                        alertas.append(prog_nome)
                    elif not tem_mensal or delta_count > 10:
                        status = "⚠️ ALERTA"
                        alertas.append(prog_nome)
                    else:
                        status = "✅ OK"

                    # Fechamento mais recente
                    if checkpoint and checkpoint["periodo_referencia"]:
                        ano, mes = map(int, checkpoint["periodo_referencia"].split("-"))
                        fech = f"{_MESES_PT[mes].capitalize()[:3]}/{ano}"
                    elif checkpoint:
                        fech = checkpoint["created_at"].strftime("%d/%m") + f" ({checkpoint['tipo']})"
                    else:
                        fech = "—"

                    total_geral += total_milhas
                    linhas.append(
                        f"{prog_nome:<12} {total_milhas:>9,} mi   R$ {cpm:>6.2f}   "
                        f"{fech:<14} {delta_count:>4} tx   {status}"
                    )

            cabecalho = (
                f"📊 Panorama — {acc_nome}\n"
                f"{'─' * 72}\n"
                f"{'Programa':<12} {'Milhas':>12}   {'CPM':>9}   {'Fechamento':<14} {'s/chk':>5}   Status\n"
                f"{'─' * 72}"
            )
            rodape = (
                f"{'─' * 72}\n"
                f"Total: {total_geral:,} milhas em {len(linhas)} programa(s)"
            )
            if alertas:
                rodape += f"\n⚠️ Atenção necessária: {', '.join(alertas)}"

            return "\n".join([cabecalho] + linhas + [rodape])

        except Exception as e:
            return _sanitize_error("get_client_panorama", e)