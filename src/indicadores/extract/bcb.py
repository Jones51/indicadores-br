"""Extrator da API SGS do Banco Central.

Endpoint: https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
A API limita consultas de séries diárias a janelas de 10 anos, então a extração
é feita em blocos.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime

import httpx

from indicadores.config import SerieSGS
from indicadores.extract.http import get_com_retentativas

BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
JANELA_ANOS = 10


def janelas(inicio: date, fim: date, anos: int = JANELA_ANOS) -> Iterator[tuple[date, date]]:
    """Divide [inicio, fim] em janelas consecutivas de no máximo `anos` anos."""
    atual = inicio
    while atual <= fim:
        try:
            limite = atual.replace(year=atual.year + anos)
        except ValueError:  # 29/02
            limite = atual.replace(year=atual.year + anos, day=28)
        proximo_fim = min(fim, date.fromordinal(limite.toordinal() - 1))
        yield atual, proximo_fim
        atual = date.fromordinal(proximo_fim.toordinal() + 1)


def parse_registros(payload: list[dict]) -> list[tuple[date, float]]:
    """Converte o JSON do SGS ([{"data": "dd/mm/aaaa", "valor": "1.23"}]) em tuplas."""
    registros = []
    for item in payload:
        valor = item.get("valor")
        if valor in (None, ""):
            continue
        registros.append((datetime.strptime(item["data"], "%d/%m/%Y").date(), float(valor)))
    return registros


def extrair_serie(
    serie: SerieSGS,
    inicio: date,
    fim: date | None = None,
    client: httpx.Client | None = None,
) -> list[tuple[date, float]]:
    """Baixa uma série SGS entre `inicio` e `fim` (inclusive)."""
    fim = fim or date.today()
    proprio_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        registros: list[tuple[date, float]] = []
        for ini, fi in janelas(inicio, fim):
            resp = get_com_retentativas(
                client,
                BASE_URL.format(codigo=serie.codigo),
                params={
                    "formato": "json",
                    "dataInicial": ini.strftime("%d/%m/%Y"),
                    "dataFinal": fi.strftime("%d/%m/%Y"),
                },
            )
            if resp.status_code == 404:  # janela sem dados
                continue
            resp.raise_for_status()
            registros.extend(parse_registros(resp.json()))
        return registros
    finally:
        if proprio_client:
            client.close()
