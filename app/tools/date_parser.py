"""
Utilitário para parsing de datas em linguagem natural (português).
"""
import re
from datetime import date, timedelta
from typing import Optional


def parse_date_natural(texto: Optional[str]) -> Optional[date]:
    """
    Interpreta datas em linguagem natural (português) e retorna objeto date.
    
    Formatos suportados:
    - 'hoje', 'ontem', 'anteontem'
    - 'há X dias' / 'ha X dias'
    - 'DD/MM/AAAA' ou 'DD/MM/AA'
    - 'DD de mês de AAAA' (ex: '17 de março de 2026')
    - 'DD de mês' (assume ano atual)
    
    Retorna None se não conseguir interpretar.
    """
    if not texto:
        return None
    
    texto = texto.strip().lower()
    hoje = date.today()
    
    # Caso 1: Relativos simples
    if texto == "hoje":
        return hoje
    if texto == "ontem":
        return hoje - timedelta(days=1)
    if texto == "anteontem":
        return hoje - timedelta(days=2)
    
    # Caso 2: "há X dias" / "ha X dias"
    match_ha = re.match(r"h[aá]\s+(\d+)\s+dias?", texto)
    if match_ha:
        dias = int(match_ha.group(1))
        return hoje - timedelta(days=dias)
    
    # Caso 3: DD/MM/AAAA ou DD/MM/AA
    match_barra = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", texto)
    if match_barra:
        dia = int(match_barra.group(1))
        mes = int(match_barra.group(2))
        ano = int(match_barra.group(3))
        
        # Ajusta ano de 2 dígitos
        if ano < 100:
            ano += 2000 if ano < 50 else 1900
        
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    
    # Caso 4: "DD de mês de AAAA" ou "DD de mês"
    meses = {
        "janeiro": 1, "jan": 1,
        "fevereiro": 2, "fev": 2,
        "março": 3, "marco": 3, "mar": 3,
        "abril": 4, "abr": 4,
        "maio": 5, "mai": 5,
        "junho": 6, "jun": 6,
        "julho": 7, "jul": 7,
        "agosto": 8, "ago": 8,
        "setembro": 9, "set": 9,
        "outubro": 10, "out": 10,
        "novembro": 11, "nov": 11,
        "dezembro": 12, "dez": 12
    }
    
    # Com ano: "17 de março de 2026"
    match_extenso_ano = re.match(
        r"(\d{1,2})\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4}))?", 
        texto
    )
    if match_extenso_ano:
        dia = int(match_extenso_ano.group(1))
        mes_nome = match_extenso_ano.group(2)
        ano_str = match_extenso_ano.group(3)
        
        mes = meses.get(mes_nome)
        if not mes:
            return None
        
        ano = int(ano_str) if ano_str else hoje.year
        
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
    
    return None


def format_date_br(data: date) -> str:
    """Formata date como DD/MM/AAAA."""
    return data.strftime("%d/%m/%Y")
