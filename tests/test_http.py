from datetime import date

import httpx
import pytest

from indicadores.config import SerieSGS
from indicadores.extract import bcb
from indicadores.extract.http import get_com_retentativas


def _client(respostas):
    """Client que devolve as respostas (ou levanta as exceções) na ordem."""
    fila = list(respostas)

    def handler(request):
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_repete_5xx_e_erro_de_transporte_com_espera_crescente():
    esperas = []
    respostas = [
        httpx.Response(502),
        httpx.ConnectTimeout("timeout"),
        httpx.Response(200, json=[]),
    ]
    with _client(respostas) as client:
        resp = get_com_retentativas(client, "https://x/y", espera=esperas.append)
    assert resp.status_code == 200
    assert esperas == [2.0, 4.0]


@pytest.mark.parametrize("status", [400, 404])
def test_nao_repete_4xx(status):
    esperas = []
    with _client([httpx.Response(status)]) as client:
        assert get_com_retentativas(client, "https://x/y", espera=esperas.append).status_code == (
            status
        )
    assert esperas == []


def test_desiste_depois_das_tentativas():
    esperas = []
    with _client([httpx.Response(503)] * 3) as client:
        resp = get_com_retentativas(client, "https://x/y", tentativas=3, espera=esperas.append)
    assert resp.status_code == 503 and esperas == [2.0, 4.0]
    with _client([httpx.ReadTimeout("t")] * 2) as client:
        with pytest.raises(httpx.ReadTimeout):
            get_com_retentativas(client, "https://x/y", tentativas=2, espera=lambda _: None)


def test_extrator_bcb_se_recupera_de_502(monkeypatch):
    monkeypatch.setattr("indicadores.extract.http.time.sleep", lambda _: None)
    ok = httpx.Response(200, json=[{"data": "02/01/2024", "valor": "11.75"}])
    serie = SerieSGS(432, "selic_meta", "% a.a.", "diaria")
    with _client([httpx.Response(502), ok]) as client:
        registros = bcb.extrair_serie(serie, date(2024, 1, 1), date(2024, 1, 31), client=client)
    assert registros == [(date(2024, 1, 2), 11.75)]
