import psycopg
import uuid
import os
import random
from datetime import date, timedelta
from dotenv import load_dotenv

# Carrega a URL do Supabase do .env
load_dotenv()
DB_URL = os.getenv("DATABASE_URL")

if not DB_URL:
    print("❌ ERRO: DATABASE_URL não encontrada no .env")
    exit()

def get_conn():
    if not DB_URL:
        raise ValueError("DATABASE_URL não configurada")
    return psycopg.connect(DB_URL)

def clean_db(conn):
    """Limpa dados antigos (Ordem correta para respeitar Foreign Keys)."""
    print("🧹 Limpando dados antigos no Supabase...")
    with conn.cursor() as cur:
        # Apagar na ordem inversa das dependências
        tables = ["transaction_batches", "transactions", "accounts"]
        for t in tables:
            cur.execute(f"TRUNCATE TABLE {t} CASCADE")
    conn.commit()

def seed_full():
    print(f"🚀 Conectando ao Supabase...")
    conn = get_conn()
    clean_db(conn)
    
    with conn.cursor() as cur:
        # --- 1. RECUPERAR PROGRAMAS ---
        # (Assumindo que você já inseriu os programas via SQL ou manualmente. 
        # Se a tabela programs estiver vazia, precisamos inserir aqui).
        cur.execute("SELECT count(*) FROM programs")
        result = cur.fetchone()
        if result and result[0] == 0:
            print("⚠️ Tabela programs vazia. Inserindo programas padrão...")
            progs = [
                ("Livelo", "BANCO"), ("Esfera", "BANCO"),
                ("LATAM Pass", "CIA_AEREA"), ("Smiles", "CIA_AEREA"),
                ("Azul Fidelidade", "CIA_AEREA"), ("TAP Miles&Go", "CIA_AEREA")
            ]
            for p in progs:
                cur.execute(
                    "INSERT INTO programs (nome, tipo) VALUES (%s, %s)",
                    p
                )
        
        # Mapear IDs
        prog_map = {}
        cur.execute("SELECT nome, id FROM programs")
        for nome, pid in cur.fetchall():
            prog_map[nome] = pid
            
        livelo = prog_map.get("Livelo")
        azul = prog_map.get("Azul Fidelidade")
        latam = prog_map.get("LATAM Pass")
        esfera = prog_map.get("Esfera")
        smiles = prog_map.get("Smiles")

        print(f"📋 Programas carregados.")

        # --- 2. CRIAR PERFIS (CONTAS) ---
        
        # PERFIL A: GESTÃO DE CPF (Ana Paula)
        ana_id = str(uuid.uuid4())
        cur.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (%s, %s, %s, %s)", 
                   (ana_id, "111.222.333-44", "Ana Paula (Gestão)", "PROPRIA"))

        # PERFIL B: CLIENTE PREMIUM (Dr. Roberto)
        roberto_id = str(uuid.uuid4())
        cur.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (%s, %s, %s, %s)", 
                   (roberto_id, "999.888.777-66", "Dr. Roberto Premium", "CLIENTE"))

        # PERFIL C: WILLIAM (Própria)
        william_id = str(uuid.uuid4())
        cur.execute("INSERT INTO accounts (id, cpf, nome, tipo_gestao) VALUES (%s, %s, %s, %s)", 
                   (william_id, "000.000.000-01", "William Assis", "PROPRIA"))


        # --- 3. GERAR TRANSAÇÕES ---

        # === HISTÓRIA DA ANA PAULA (Compra Esfera + Transf Latam) ===
        print("   -> Gerando histórico da Ana Paula...")
        
        # Compra Esfera
        tx1 = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
            VALUES (%s, %s, CURRENT_DATE - 120, 'COMPRA_BANCO', %s, %s, %s, 200000, 0, 200000, 7000.00, 35.00, 'Compra Esfera 50%% OFF')
        """, (tx1, ana_id, esfera, esfera, esfera))
        
        cur.execute("INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (%s, 'PAGO', 200000, 35.00, 7000.00)", (tx1,))

        # Transferência Bumerangue Latam
        tx2 = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
            VALUES (%s, %s, CURRENT_DATE - 90, 'TRANSFERENCIA_BANCO_CIA', %s, %s, %s, 100000, 40.0, 140000, 3500.00, 25.00, 'Transf. Esfera->Latam Promo')
        """, (tx2, ana_id, esfera, latam, latam))
        
        cur.execute("INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (%s, 'PAGO', 100000, 35.00, 3500.00)", (tx2,))


        # === HISTÓRIA DO DR. ROBERTO (Orgânico + Clube) ===
        print("   -> Gerando histórico do Dr. Roberto...")

        # Orgânico Mensal
        for i in range(3):
            days_ago = (3 - i) * 30
            cur.execute("""
                INSERT INTO transactions (account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, milhas_creditadas, custo_total, cpm_real, descricao)
                VALUES (%s, CURRENT_DATE - %s, 'ORGANICO', NULL, %s, %s, 25000, 25000, 0, 0, 'Fatura Mensal Visa Infinite')
            """, (roberto_id, days_ago, livelo, livelo))

        # Clube Livelo
        tx_clube = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO transactions (id, account_id, data_registro, modo_aquisicao, origem_id, destino_id, companhia_referencia_id, milhas_base, bonus_percent, milhas_creditadas, custo_total, cpm_real, descricao)
            VALUES (%s, %s, CURRENT_DATE - 60, 'CLUBE_ASSINATURA', %s, %s, %s, 240000, 0, 240000, 4800.00, 20.00, 'Clube Livelo Top Anual')
        """, (tx_clube, roberto_id, livelo, livelo, livelo))
        
        cur.execute("INSERT INTO transaction_batches (transaction_id, tipo, milhas_qtd, cpm_origem, custo_parcial) VALUES (%s, 'PAGO', 240000, 20.00, 4800.00)", (tx_clube,))

    conn.commit()
    conn.close()
    print("\n✅ Banco Supabase populado com sucesso!")

if __name__ == "__main__":
    seed_full()