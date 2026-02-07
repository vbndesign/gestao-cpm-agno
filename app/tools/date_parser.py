"""
Utilitário para parsing de datas em linguagem natural (português brasileiro).
Usa a biblioteca dateparser com auto-detecção de padrões.
"""
import dateparser
from datetime import date, datetime
from typing import Optional


def parse_date_natural(texto: Optional[str], prefer_future: bool = False) -> Optional[date]:
    """
    Interpreta datas em linguagem natural (português brasileiro).
    
    Usa auto-detecção de idioma e formatos. Para expressões que não funcionar,
    o agente é instruído a usar formatos padrão: DD/MM/AAAA ou "DD de mês de AAAA".
    
    Args:
        texto: Expressão de data em linguagem natural
        prefer_future: Se True, interpreta datas ambíguas como futuras (útil para renovações)
    
    Returns:
        Objeto date se interpretado com sucesso, None caso contrário
    """
    if not texto:
        return None
    
    # Deixa dateparser detectar automaticamente
    resultado = dateparser.parse(
        texto,
        languages=['pt'],  # Força interpretação em português brasileiro
        settings={
            'TIMEZONE': 'America/Sao_Paulo',
            'RETURN_AS_TIMEZONE_AWARE': False,
            'PREFER_DATES_FROM': 'future' if prefer_future else 'past',
            'RELATIVE_BASE': datetime.now(),
            'PREFER_LOCALE_DATE_ORDER': True,  # DD/MM/AAAA (padrão BR)
            'DATE_ORDER': 'DMY'  # Dia-Mês-Ano
        }
    )
    
    if resultado:
        return resultado.date()
    
    return None


def format_date_br(data: date) -> str:
    """Formata date como DD/MM/AAAA."""
    return data.strftime("%d/%m/%Y")
