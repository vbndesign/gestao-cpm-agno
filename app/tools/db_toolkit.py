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
        self.register(self.save_complex_transfer)
        self.register(self.get_dashboard)
        self.register(self.register_subscription)
        self.register(self.correct_last_subscription)
        self.register(self.delete_last_transaction)
        self.register(self.process_monthly_credit)
        self.register(self.register_intra_club_transaction)

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

    # --- Ferramentas Públicas (Disponíveis para o Agente) ---
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
            return f"Erro na busca: {str(e)}"

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
            return f"❌ Erro Técnico ao criar conta: {str(e)}"

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
        except Exception as e: return f"Erro ao buscar programas: {str(e)}"

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
        AGORA SUPORTA CÁLCULO DE BÔNUS AUTOMÁTICO.
        
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
                    # ✅ CORREÇÃO: subscription_id explícito como None (NULL)
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
            return f"❌ Erro ao salvar transação: {str(e)}"

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
            # Parse e validação de data de início
            if data_inicio:
                dt_inicio = parse_date_natural(data_inicio, prefer_future=False)
                if not dt_inicio:
                    return f"❌ Erro: Não consegui interpretar a data de início '{data_inicio}'. Use formatos como 'DD/MM/AAAA' ou 'DD de mês de AAAA'."
            else:
                dt_inicio = date.today()
            
            # Parse e validação de data de renovação (com preferência por futuro)
            data_renov_dt = parse_date_natural(data_renovacao, prefer_future=True)
            if not data_renov_dt:
                return f"❌ Erro: Não consegui interpretar a data de renovação '{data_renovacao}'. Use formatos como 'daqui a 1 ano', 'DD/MM/AAAA' ou 'DD de mês de AAAA'."
            
            if data_renov_dt <= dt_inicio:
                return f"❌ Erro: A data de renovação deve ser posterior à data de início. Início: {dt_inicio.strftime('%d/%m/%Y')}, Renovação: {data_renov_dt.strftime('%d/%m/%Y')}."

            # Lógica de Anualização (Cálculo seguro no Python)
            if is_mensal:
                valor_contrato = float(valor_total_ciclo) * 12
                milhas_contrato = int(milhas_garantidas_ciclo) * 12
                tipo_contrato = "MENSAL (Anualizado x12)"
            else:
                valor_contrato = float(valor_total_ciclo)
                milhas_contrato = int(milhas_garantidas_ciclo)
                tipo_contrato = "ANUAL (Valor Cheio)"

            # Validações de entrada
            if valor_contrato <= 0:
                return "❌ Erro: valor_total_ciclo deve ser maior que zero."
            if milhas_contrato <= 0:
                return "❌ Erro: milhas_garantidas_ciclo deve ser maior que zero."

            with self._get_conn() as conn:
                acc_id, acc_nome = self._get_account_id(conn, nome_conta)
                if not acc_id: 
                    return f"❌ Conta '{nome_conta}' não encontrada."
                
                prog_id = self._get_program_id(conn, nome_programa)
                if not prog_id: 
                    return f"❌ Programa '{nome_programa}' não encontrado."
                
                with conn.cursor() as cur:
                    # Inserção com retorno do CPM calculado (usando valores do contrato)
                    # Nota: data_fim é deixada NULL (assinatura ativa). Será preenchida apenas quando o contrato encerrar.
                    cur.execute("""
                        INSERT INTO subscriptions 
                        (account_id, programa_id, valor_total_ciclo, milhas_garantidas_ciclo, data_inicio, data_renovacao, ativo)
                        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                        RETURNING cpm_fixo
                    """, (acc_id, prog_id, valor_contrato, milhas_contrato, dt_inicio, data_renov_dt),
                         prepare=False)
                    
                    result = cur.fetchone()
                    if not result:
                        return "❌ Erro: Não foi possível criar a assinatura."
                    cpm_calculado = result[0]
                
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
            return f"❌ Erro ao registrar assinatura: {str(e)}"
        

    def correct_last_subscription(self, 
                                nome_conta: str, 
                                nome_programa: str, 
                                valor_total_ciclo: float, 
                                milhas_garantidas_ciclo: int, 
                                data_renovacao: str,
                                data_inicio: Optional[str] = None,
                                is_mensal: bool = False) -> str:
        """
        CORREÇÃO: Apaga a última assinatura registrada para esta conta e insere a nova com os dados corrigidos.
        Use ISSO quando o usuário disser 'Errei o valor', 'Corrige a data', etc.
        
        Args:
            valor_total_ciclo: Valor monetário do ciclo (mensal ou anual, dependendo de is_mensal).
            milhas_garantidas_ciclo: Quantidade de milhas do ciclo (mensal ou anual).
            data_renovacao: Data de renovação FUTURA. Aceita linguagem natural.
            data_inicio: Data de início da assinatura (opcional). Pode ser no passado.
            is_mensal: Se True, multiplica os valores por 12 para criar o contrato anual.
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
                data_renovacao,
                data_inicio,
                is_mensal
            )
            
            return f"{resultado_novo} {msg_delecao}"

        except Exception as e:
            return f"❌ Erro ao corrigir: {str(e)}"

    def delete_last_transaction(self,
                               nome_conta: str,
                               nome_programa: Optional[str] = None,
                               confirmar: bool = False) -> str:
        """
        Desfaz (deleta) a ÚLTIMA transação registrada para uma conta.

        ⚠️ REGRA DE SEGURANÇA: Só é seguro apagar a ÚLTIMA transação.
        Transações anteriores já influenciaram o CPM das seguintes.

        Fluxo obrigatório em 2 etapas:
          1. Chame com confirmar=False → mostra o que seria apagado (preview).
          2. Confirme com o usuário na conversa.
          3. Só então chame com confirmar=True → executa a deleção.

        Args:
            nome_conta:    Nome, CPF ou UUID da conta.
            nome_programa: Filtro opcional por programa. Use quando a conta tem
                           múltiplas transações recentes e precisa de precisão.
            confirmar:     False = preview | True = deleta de verdade.
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
                    )

                    if not confirmar:
                        return (
                            f"{resumo}\n\n"
                            f"❓ Confirma a exclusão? Se sim, chame novamente com `confirmar=True`."
                        )

                    # ── Deleção efetiva ──────────────────────────────────────
                    # transaction_batches são removidos automaticamente (ON DELETE CASCADE)
                    cur.execute("DELETE FROM transactions WHERE id = %s", (tx_id,), prepare=False)
                    conn.commit()

                    return (
                        f"🗑️ **Transação deletada com sucesso!**\n"
                        f"{resumo}\n\n"
                        f"✅ O registro foi removido. Você pode lançar novamente com os dados corretos."
                    )

        except Exception as e:
            return f"❌ Erro ao deletar transação: {str(e)}"

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
                                      descricao: str,
                                      bonus_percent: float = 0.0) -> str: # <--- Novo Parâmetro
        """
        Registra transações intra-clube.
        Agora aceita 'bonus_percent' para que o Python faça o cálculo final de milhas.
        """
        try:
            # 1. Cálculo Deterministico (Python)
            milhas_base = int(milhas)
            bonus = float(bonus_percent)
            
            # Fórmula: Base + (Base * (Bonus/100))
            total_milhas = int(milhas_base * (1 + bonus / 100))
            
            # Define Modo
            if custo_total <= 0:
                modo = "ORGANICO" # ModoAquisicao.ORGANICO.value
                custo_final = 0.0
                tag_desc = "(Bônus/Orgânico Clube)"
            else:
                modo = "COMPRA_SIMPLES" # ModoAquisicao.COMPRA_SIMPLES.value
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
                        LIMIT 1
                    """, (acc_id, prog_id))
                    
                    sub = cur.fetchone()
                    if not sub:
                        return f"❌ Operação negada: Cliente sem Clube Ativo na {nome_programa}."
                    sub_id = sub[0]

                    # CPM Real baseado no TOTAL creditado
                    cpm_transacao = (custo_final / total_milhas * 1000) if total_milhas > 0 else 0

                    full_desc = f"{descricao} {tag_desc}"
                    
                    # Insert completo preenchendo as colunas de Base e Bônus separadas
                    cur.execute("""
                        INSERT INTO transactions 
                        (account_id, data_registro, data_transacao, modo_aquisicao, origem_id, destino_id, companhia_referencia_id,
                         milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao, subscription_id)
                        VALUES (%s, CURRENT_DATE, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        acc_id, 
                        modo, 
                        prog_id, prog_id, prog_id,
                        milhas_base,   # Coluna milhas_base
                        bonus,         # Coluna bonus_percent
                        total_milhas,  # Coluna milhas_creditadas (Calculado pelo Python)
                        custo_final, 
                        cpm_transacao, 
                        full_desc, 
                        sub_id
                    ))
                    
                    conn.commit()
                    
                    return (
                        f"✅ **Transação Intra-Clube Registrada!**\n"
                        f"🔢 **Estrutura:** {milhas_base} milhas + {int(bonus)}% bônus\n"
                        f"🛒 **Total Creditado:** {total_milhas} milhas\n"
                        f"💸 **Custo:** R$ {custo_final:.2f}\n"
                        f"📉 **CPM:** R$ {cpm_transacao:.2f}"
                    )

        except Exception as e:
            return f"❌ Erro: {str(e)}"