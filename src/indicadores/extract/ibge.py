"""Extrator da API SIDRA do IBGE — a implementar.

Candidatos iniciais:
- PNAD Contínua: taxa de desocupação (tabela 4099)
- PIB trimestral (tabela 1621)

API: https://apisidra.ibge.gov.br/
"""

from __future__ import annotations


def extrair_tabela(tabela: int, **kwargs) -> list[dict]:
    raise NotImplementedError("Extrator IBGE ainda não implementado")
