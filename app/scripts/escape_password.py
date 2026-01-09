"""
Script para escapar senhas com caracteres especiais para uso em URLs de conexão PostgreSQL/Supabase.

Uso:
    python -m app.scripts.escape_password

O script irá:
1. Solicitar a senha bruta (com caracteres especiais)
2. Escapar a senha usando urllib.parse.quote_plus
3. Mostrar a senha escapada para uso no .env
4. Gerar a URL completa de exemplo
"""

from urllib.parse import quote_plus

def escape_password_for_db_url(raw_password: str) -> str:
    """
    Escapa caracteres especiais em senhas para uso seguro em URLs de conexão.
    
    Args:
        raw_password: Senha original com caracteres especiais
        
    Returns:
        Senha escapada pronta para uso em DATABASE_URL
        
    Exemplos de caracteres que precisam escape:
        ! @ # $ % ^ & * ( ) + = { } [ ] | \\ : ; " ' < > , . ? /
    """
    return quote_plus(raw_password)

def main():
    print("=" * 60)
    print("🔐 Escapador de Senha para DATABASE_URL")
    print("=" * 60)
    print()
    
    # Solicita a senha
    raw_password = input("Digite a senha do banco: ").strip()
    
    if not raw_password:
        print("❌ Senha vazia. Abortando.")
        return
    
    # Escapa a senha
    escaped_password = escape_password_for_db_url(raw_password)
    
    # Mostra o resultado
    print()
    print("✅ Senha escapada:")
    print("-" * 60)
    print(escaped_password)
    print("-" * 60)

if __name__ == "__main__":
    main()
