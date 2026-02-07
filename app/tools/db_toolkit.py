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
        self.register(self.register_subscription)
        self.register(self.correct_last_subscription)
        self.register(self.process_monthly_credit)

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

    def register_subscription(self,
                            nome_conta: str, 
                            nome_programa: str, 
                            valor_total_ciclo: float, 
                            milhas_garantidas_ciclo: int, 
                            data_renovacao: str) -> str:
        """
        Registra uma assinatura de Clube (recorrência mensal/anual).
        O CPM é calculado automaticamente pelo banco de dados.
        data_renovacao: Data de renovação em linguagem natural (ex: '15 de janeiro de 2027').
        """
        try:
            # Parse e validação de data
            data_renov_dt = parse_date_natural(data_renovacao)
            if not data_renov_dt:
                return f"❌ Erro: Não consegui interpretar a data '{data_renovacao}'. Use formatos como 'DD/MM/AAAA' ou 'DD de mês de AAAA'."
            
            if data_renov_dt <= date.today():
                return f"❌ Erro: A data de renovação ({data_renovacao}) deve ser no futuro."

            # Validações de entrada
            if valor_total_ciclo <= 0:
                return "❌ Erro: valor_total_ciclo deve ser maior que zero."
            if milhas_garantidas_ciclo <= 0:
                return "❌ Erro: milhas_garantidas_ciclo deve ser maior que zero."

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: 
                    return f"❌ Conta '{nome_conta}' não encontrada."
                
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: 
                    return f"❌ Programa '{nome_programa}' não encontrado."
                
                with conn.cursor() as cur:
                    # Inserção com retorno do CPM calculado
                    cur.execute("""
                        INSERT INTO subscriptions 
                        (account_id, programa_id, valor_total_ciclo, milhas_garantidas_ciclo, data_inicio, data_renovacao)
                        VALUES (%s, %s, %s, %s, CURRENT_DATE, %s)
                        RETURNING cpm_fixo
                    """, (acc_id, prog_id, valor_total_ciclo, milhas_garantidas_ciclo, data_renov_dt),
                         prepare=False)
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a assinatura."
                    cpm_calculado = result[0]
                
                conn.commit()
                return f"✅ Assinatura registrada para {acc_nome}! CPM Fixo: **R$ {cpm_calculado:.2f}** • Renovação: {data_renov_dt.strftime('%d/%m/%Y')}"
                
        except Exception as e:
            return f"❌ Erro ao registrar assinatura: {str(e)}"
        

    def correct_last_subscription(self, 
                                nome_conta: str, 
                                nome_programa: str, 
                                valor_total_ciclo: float, 
                                milhas_garantidas_ciclo: int, 
                                data_renovacao: str) -> str:
        """
        CORREÇÃO: Apaga a última assinatura registrada para esta conta e insere a nova com os dados corrigidos.
        Use ISSO quando o usuário disser 'Errei o valor', 'Corrige a data', etc.
        """
        try:
            # 1. Tratamento da Data (Reutilizando sua função auxiliar)
            # Precisamos importar parse_date_natural ou tê-la disponível aqui
            # data_renov_dt = parse_date_natural(data_renovacao) ... (se não tiver a validação aqui, o register vai fazer)

            with self._get_conn() as conn:
                # --- AQUI ESTÁ A LÓGICA DO NOME ---
                # Usamos o nome para descobrir o ID
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."

                with conn.cursor() as cur:
                    # 2. DELETA A ÚLTIMA ASSINATURA (Limpeza)
                    # Busca a última criada baseada no timestamp para aquele ID
                    cur.execute("""
                        DELETE FROM subscriptions 
                        WHERE id = (
                            SELECT id FROM subscriptions 
                            WHERE account_id = %s 
                            ORDER BY created_at DESC 
                            LIMIT 1
                        )
                        RETURNING id;
                    """, (acc_id,))
                    
                    deleted = cur.fetchone()
                    msg_delecao = "(Anterior apagada 🗑️)" if deleted else "(Nenhuma anterior encontrada para apagar)"
                
                conn.commit() # Confirma a exclusão antes de tentar inserir a nova
            
            # 3. CHAMA A FUNÇÃO DE REGISTRO NORMAL
            # Agora chamamos a função 'irmã' para recriar o registro limpo
            resultado_novo = self.register_subscription(
                nome_conta, 
                nome_programa, 
                valor_total_ciclo, 
                milhas_garantidas_ciclo, 
                data_renovacao
            )
            
            return f"{resultado_novo} {msg_delecao}"

        except Exception as e:
            return f"❌ Erro ao corrigir: {str(e)}"
        
    def process_monthly_credit(self, nome_conta: str, nome_programa: str, milhas_do_mes: int = 0) -> str:
        """
        Registra a entrada mensal (Recorrência) com TRAVA DE SEGURANÇA.
        Não permite creditar mais milhas do que o total contratado na assinatura.
        """
        try:
            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: return f"❌ Programa '{nome_programa}' não encontrado."

                with conn.cursor() as cur:
                    # 1. Busca os dados do CONTRATO
                    cur.execute("""
                        SELECT id, cpm_fixo, milhas_garantidas_ciclo, valor_total_ciclo 
                        FROM subscriptions
                        WHERE account_id = %s AND programa_id = %s AND ativo = TRUE
                        LIMIT 1
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

                    # --- 🛡️ TRAVA DE SEGURANÇA ---
                    cur.execute("""
                        SELECT COALESCE(SUM(milhas_creditadas), 0) 
                        FROM transactions 
                        WHERE subscription_id = %s
                    """, (sub_id,))
                    
                    # Correção: O fetchone retorna uma tupla, pegamos o índice [0]
                    result = cur.fetchone()
                    total_ja_creditado = result[0] if result else 0
                    
                    saldo_restante = milhas_totais_contrato - total_ja_creditado

                    # Validação Matemática (Dentro do process_monthly_credit)
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

                    # 3. Cálculos
                    custo_contabil = (qtd_inserir / 1000) * float(cpm_fixo)
                    
                    # AQUI A CORREÇÃO PRINCIPAL:
                    # Usamos o CPM do contrato direto (sem recalcular) e o Modo CLUBE
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, subscription_id)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s)
                    """, (
                        acc_id, 
                        ModoAquisicao.CLUBE.value, # <--- CORRIGIDO: Era ORGANICO, agora é CLUBE ('CLUBE_ASSINATURA')
                        prog_id, prog_id, prog_id, # Origem/Destino/Ref = Programa (Internalização)
                        qtd_inserir, # milhas_base
                        qtd_inserir, # milhas_creditadas
                        custo_contabil,
                        cpm_fixo, # <--- CORRIGIDO: Usa o valor fixo direto do banco para evitar dízimas
                        f'Crédito Mensal Clube - {nome_programa}', 
                        sub_id
                    ), prepare=False) # Mantive o prepare=False pois parece ser necessário no seu driver
                    
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
            return f"❌ Erro ao processar: {str(e)}"
        

    def register_intra_club_transaction(self, 
                                      nome_conta: str, 
                                      nome_programa: str, 
                                      milhas: int, 
                                      custo_total: float,
                                      descricao: str) -> str:
        """
        Registra transações AVULSAS (Não-Recorrentes) feitas DENTRO do ambiente do Clube.
        Exemplos: 
        1. Compra de pontos com desconto de assinante (Custo > 0).
        2. Bônus orgânico/aniversário do clube (Custo = 0).
        
        DIFERENÇA: Esta função VINCULA a transação ao ID da Assinatura (subscription_id),
        permitindo rastrear que o benefício veio do Clube.
        """
        try:
            # 1. Define o Modo e a Tag de Descrição baseada no Custo
            if custo_total <= 0:
                modo = "ORGANICO" # Ou ModoAquisicao.ORGANICO.value
                custo_final = 0.0
                tag_desc = "(Bônus/Orgânico Clube)"
            else:
                modo = "COMPRA_SIMPLES" # Ou ModoAquisicao.COMPRA_SIMPLES.value
                custo_final = float(custo_total)
                tag_desc = "(Compra Promocional Clube)"

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: return f"❌ Conta '{nome_conta}' não encontrada."

                prog_id = self._get_program_id(conn, nome_programa) # Usando seu helper corrigido
                if not prog_id: return f"❌ Programa '{nome_programa}' não encontrado."

                with conn.cursor() as cur:
                    # 2. Busca a Assinatura ATIVA (Obrigatório ter clube para usar essa função)
                    cur.execute("""
                        SELECT id FROM subscriptions
                        WHERE account_id = %s AND programa_id = %s AND ativo = TRUE
                        LIMIT 1
                    """, (acc_id, prog_id))
                    
                    sub = cur.fetchone()
                    if not sub:
                        return f"❌ Operação negada: O cliente {acc_nome} não tem Clube Ativo na {nome_programa} para realizar operações vinculadas."
                    
                    sub_id = sub[0]

                    # 3. Calcula CPM Real dessa operação específica
                    cpm_transacao = (custo_final / milhas * 1000) if milhas > 0 else 0

                    # 4. Insert VINCULADO (subscription_id preenchido)
                    full_desc = f"{descricao} {tag_desc}"
                    
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, subscription_id)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s, %s)
                    """, (
                        acc_id, 
                        modo, 
                        prog_id, prog_id, prog_id,
                        milhas, 
                        milhas, 
                        custo_final, 
                        cpm_transacao, 
                        full_desc, 
                        sub_id # <--- O Grande Diferencial: Vinculado ao Clube
                    ))
                    
                    conn.commit()
                    
                    return (
                        f"✅ Transação Intra-Clube registrada!\n"
                        f"🎯 Contexto: {tag_desc}\n"
                        f"📊 +{milhas} milhas\n"
                        f"💰 Custo: R$ {custo_final:.2f} (CPM R$ {cpm_transacao:.2f})"
                    )

        except Exception as e:
            return f"❌ Erro ao registrar intra-clube: {str(e)}"