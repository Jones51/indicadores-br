"""Fonte simulada (BCB SGS + IBGE SIDRA) servida por `httpx.MockTransport`, sem rede.

A fonte responde como as APIs reais nos pontos que a ingestão incremental usa: o SGS filtra
por `dataInicial`/`dataFinal` e devolve 404 para janela sem dados; o SIDRA aceita `p/all` ou a
faixa `p/AAAAPP-AAAAPP` e devolve o cabeçalho como primeiro item.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx
import pytest

from indicadores.config import SerieSGS, SerieSIDRA
from indicadores.extract.ibge import data_para_periodo

SELIC = SerieSGS(432, "selic_meta", "% a.a.", "diaria")
IPCA = SerieSGS(433, "ipca_mensal", "% a.m.", "mensal")
DESOC_MOVEL = SerieSIDRA("desocupacao_movel", 6381, 4099, "%", "trimestral_movel")
PIB = SerieSIDRA("pib_indice_sa", 1621, 584, "índice", "trimestral", ((11255, 90707),))
SERIES_BCB_TESTE = (SELIC, IPCA)
SERIES_IBGE_TESTE = (DESOC_MOVEL, PIB)

ROTULO = {"trimestral": "Trimestre", "trimestral_movel": "Trimestre Móvel"}


def _meses(inicio: date, fim: date, passo: int = 1):
    d = inicio
    while d <= fim:
        yield d
        total = d.year * 12 + d.month - 1 + passo
        d = date(total // 12, total % 12 + 1, 1)


class FonteFalsa:
    """Estado mutável das duas APIs. `publicar_ate(fim)` simula a passagem do tempo."""

    def __init__(self) -> None:
        self.bcb: dict[int, dict[date, float]] = {s.codigo: {} for s in SERIES_BCB_TESTE}
        self.ibge: dict[str, dict[date, float]] = {s.nome: {} for s in SERIES_IBGE_TESTE}
        self.requisicoes: list[httpx.Request] = []

    def publicar_ate(self, fim: date) -> None:
        """Preenche as séries de 2023-01-01 até `fim` com valores determinísticos."""
        d = date(2023, 1, 1)
        while d <= fim:
            self.bcb[SELIC.codigo].setdefault(d, 10 + d.toordinal() % 7 / 4)
            d += timedelta(days=1)
        for i, m in enumerate(_meses(date(2023, 1, 1), fim)):
            self.bcb[IPCA.codigo].setdefault(m, round(0.1 * (i % 9), 2))
            self.ibge[DESOC_MOVEL.nome].setdefault(m, 7 + (i % 5) / 10)
        for i, m in enumerate(_meses(date(2023, 3, 1), fim, 3)):
            self.ibge[PIB.nome].setdefault(m, 190 + i)

    # ---- HTTP ----
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requisicoes.append(request)
        if request.url.host == "api.bcb.gov.br":
            return self._sgs(request)
        return self._sidra(request)

    def _sgs(self, request: httpx.Request) -> httpx.Response:
        codigo = int(request.url.path.split("bcdata.sgs.")[1].split("/")[0])
        ini = datetime.strptime(request.url.params["dataInicial"], "%d/%m/%Y").date()
        fim = datetime.strptime(request.url.params["dataFinal"], "%d/%m/%Y").date()
        dados = sorted((d, v) for d, v in self.bcb[codigo].items() if ini <= d <= fim)
        if not dados:
            return httpx.Response(404)
        return httpx.Response(
            200, json=[{"data": d.strftime("%d/%m/%Y"), "valor": str(v)} for d, v in dados]
        )

    def _sidra(self, request: httpx.Request) -> httpx.Response:
        partes = request.url.path.strip("/").split("/")
        tabela, periodos = int(partes[partes.index("t") + 1]), partes[partes.index("p") + 1]
        serie = next(s for s in SERIES_IBGE_TESTE if s.tabela == tabela)
        codigos = {
            data_para_periodo(d, serie.periodicidade): v for d, v in self.ibge[serie.nome].items()
        }
        if periodos != "all":
            ini, fim = periodos.split("-")
            if ini > fim:
                return httpx.Response(400, text="Parâmetro P (Período) mal especificado")
            codigos = {c: v for c, v in codigos.items() if ini <= c <= fim}
        rotulo = ROTULO[serie.periodicidade]
        cabecalho = {
            "MN": "Unidade de Medida",
            "V": "Valor",
            "D3C": f"{rotulo} (Código)",
            "D3N": rotulo,
        }
        linhas = [
            {"MN": serie.unidade, "V": str(v), "D3C": c, "D3N": f"período {c}"}
            for c, v in sorted(codigos.items())
        ]
        return httpx.Response(200, json=[cabecalho, *linhas])

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fonte() -> FonteFalsa:
    return FonteFalsa()
