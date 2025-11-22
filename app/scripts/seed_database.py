import sqlite3
import uuid
import random
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("storage/milhas.db")

def get_conn():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Banco não encontrado em {DB_PATH}. Rode o sistema primeiro.")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def clean_db(conn):
    """Limpa transações e contas para garantir um teste limpo."""
    print("🧹 Limpando dados antigos para evitar duplicações...")
    tables = ["transaction_batches", "transactions", "issuances", "cpf_slots", "accounts"]
    for t in tables:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()

def seed_full():
    conn = get_conn()
    clean_db(conn) # Começar do zero para este teste
    cursor = conn.cursor()

    # --- 1. RECUPERAR PROGRAMAS ---
    progs = {}
    rows = cursor.execute("SELECT nome, id FROM programs").fetchall()
    for nome, pid in rows:
        progs[nome] = pid
    
    # IDs úteis
    livelo = progs.get("Livelo")
    azul = progs.get("Azul Fidelidade")
    latam = progs.get("LATAM Pass")
    esfera = progs.get("Esfera")
    smiles = progs.get("Smiles")

    print(f"🚀 Iniciando Geração de Histórico Realista...")

    # --- 2. CRIAR PERFIS (CONTAS) ---
    
    # PERFIL A: GESTÃO DE CPF (Estoque para Venda)
    # Nome: Ana Paula (Gerenciada pelo William)
    ana_id = str(uuid.uuid4())
    cursor.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (?, ?, ?, ?)", 
                   (ana_id, "111.222.333-44", "Ana Paula (Gestão)", "PROPRIA"))

    # PERFIL B: CLIENTE PREMIUM
    # Nome: Dr. Roberto (Médico, alta renda, acumula para uso próprio)
    roberto_id = str(uuid.uuid4())
    cursor.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (?, ?, ?, ?)", 
                   (roberto_id, "999.888.777-66", "Dr. Roberto Premium", "CLIENTE"))

    # PERFIL C: CLIENTE AVULSO (Venda Direta)
    # Apenas emissão, mas precisamos da conta de origem (William usa a dele mesmo ou da Ana)
    # Vamos criar a conta do William também
    william_id = str(uuid.uuid4())
    cursor.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (?, ?, ?, ?)", 
                   (william_id, "000.000.000-01", "William Assis", "PROPRIA"))


    # --- 3. GERAR TRANSAÇÕES (HISTÓRICO DE 6 MESES) ---

    # === HISTÓRIA DA ANA PAULA (Foco: Fabricar milhas Latam baratas) ===
    print("   -> Gerando histórico da Ana Paula (Estoque)...")
    
    # Mês -4: Compra de Pontos Esfera com 50% de desconto (Custo R$ 35,00)
    tx1 = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
        VALUES (?, ?, DATE('now', '-120 days'), 'COMPRA_BANCO', ?, ?, ?, 200000, 0, 200000, 7000.00, 35.00, 'Compra Esfera 50% OFF')
    """, (tx1, ana_id, esfera, esfera, esfera))
    cursor.execute("INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (?, ?, 'PAGO', 200000, 35.00, 7000.00)", (str(uuid.uuid4()), tx1))

    # Mês -3: Transferência Bumerangue para Latam (30% Bônus + 10% volta) - Simulação simplificada de Bônus 40%
    # Transferiu 100k Esfera -> Latam
    tx2 = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
        VALUES (?, ?, DATE('now', '-90 days'), 'TRANSFERENCIA_BANCO_CIA', ?, ?, ?, 100000, 40.0, 140000, 3500.00, 25.00, 'Transf. Esfera->Latam Promo')
    """, (tx2, ana_id, esfera, latam, latam))
    
    # Batch da transferência (Origem foi o lote pago de 35,00)
    cursor.execute("INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (?, ?, 'PAGO', 100000, 35.00, 3500.00)", (str(uuid.uuid4()), tx2))

    # === HISTÓRIA DO DR. ROBERTO (Foco: Orgânico massivo + Transferência Bonificada) ===
    print("   -> Gerando histórico do Dr. Roberto (Premium)...")

    # Acúmulo Orgânico Mensal (Cartão Visa Infinite) - Últimos 3 meses
    for i in range(3):
        days_ago = (3 - i) * 30
        cursor.execute("""
            INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, milhas_creditadas, custo_total, cpm_real, descricao)
            VALUES (?, ?, DATE('now', ?), 'ORGANICO', NULL, ?, ?, 25000, 25000, 0, 0, 'Fatura Mensal Visa Infinite')
        """, (str(uuid.uuid4()), roberto_id, f'-{days_ago} days', livelo, livelo))

    # Assinatura Clube Livelo Top (Anual)
    tx_clube = str(uuid.uuid4())
    cursor.execute("""
        INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
        VALUES (?, ?, DATE('now', '-60 days'), 'CLUBE_ASSINATURA', ?, ?, ?, 240000, 0, 240000, 4800.00, 20.00, 'Clube Livelo Top Anual')
    """, (tx_clube, roberto_id, livelo, livelo, livelo))
    # Batch Clube
    cursor.execute("INSERT INTO transaction_batches (id, transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (?, ?, 'PAGO', 240000, 20.00, 4800.00)", (str(uuid.uuid4()), tx_clube))


    # --- 4. GERAR EMISSÕES (VENDAS PARA AGÊNCIAS/CLIENTES) ---
    print("   -> Gerando Emissões (Vendas)...")

    # CENÁRIO 1: Agência comprando do estoque da Ana Paula
    # Agência "Viaja Rápido" pediu 4 passagens Latam (GRU-MIA)
    # Custo Médio da Ana na Latam (Transação tx2) = R$ 25,00
    # Preço de Venda para Agência = R$ 28,00 (Lucro de R$ 3,00/milheiro no volume)
    
    for i in range(2): # 2 Emissões grandes
        cursor.execute("""
            INSERT INTO issuances (id, account_id, programa_id, data_emissao, passageiro_nome, localizador, milhas_utilizadas, cpm_medio_momento, custo_venda, valor_venda, status)
            VALUES (?, ?, ?, DATE('now', '-10 days'), ?, ?, 50000, 25.00, 1250.00, 1400.00, 'EMITIDA')
        """, (str(uuid.uuid4()), ana_id, latam, f"Cliente Agência {i+1}", f"LOC{random.randint(100,999)}"))

    # CENÁRIO 2: Cliente Avulso comprando do William (Margem Alta)
    # Venda direta: Passagem de emergência, margem alta.
    # Estoque do William (vamos simular que ele tinha milhas a R$ 17,00)
    cursor.execute("""
        INSERT INTO issuances (id, account_id, programa_id, data_emissao, passageiro_nome, localizador, milhas_utilizadas, cpm_medio_momento, custo_venda, valor_venda, status)
        VALUES (?, ?, ?, DATE('now', '-2 days'), 'Cliente Avulso Urgente', 'URG999', 30000, 17.00, 510.00, 900.00, 'EMITIDA')
    """, (str(uuid.uuid4()), william_id, smiles))

    conn.commit()
    conn.close()
    print("\n✅ Banco de dados populado com sucesso!")
    print("   - 3 Contas Criadas (Gestão, Premium, Própria)")
    print("   - Histórico de Orgânicos, Compras e Transferências")
    print("   - Emissões para Agências registradas")

if __name__ == "__main__":
    seed_full()