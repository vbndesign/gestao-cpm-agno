# app/core/enums.py
"""Enums centralizados para tipos de transações e lotes."""
from enum import Enum

class TipoLote(str, Enum):
    ORGANICO = "ORGANICO"
    PAGO = "PAGO"

class ModoAquisicao(str, Enum):
    COMPRA_SIMPLES = "COMPRA_SIMPLES"
    ORGANICO = "ORGANICO"
    TRANSFERENCIA = "TRANSFERENCIA_BANCO_CIA"
    CLUBE = "CLUBE_ASSINATURA"
    AJUSTE_CPM = "AJUSTE_CPM"