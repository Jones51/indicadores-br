from datetime import date

import httpx
import pytest

from indicadores.config import SERIES_IBGE, SerieSIDRA
from indicadores.extract.ibge import (
    RegistroSIDRA,
    extrair_serie,
    montar_url,
    parse_resposta,
    parse_valor,
    periodo_para_data,
)

# Recortes reais da API (valores e rótulos), reduzidos ao necessário.
PAYLOAD_TRIMESTRAL = [
    {
        "NC": "Nível Territorial (Código)",
        "MN": "Unidade de Medida",
        "V": "Valor",
        "D1C": "Brasil (Código)",
        "D2C": "Variável (Código)",
        "D3C": "Trimestre (Código)",
        "D3N": "Trimestre",
        "D4C": "Setores e subsetores (Código)",
        "D4N": "Setores e subsetores",
    },
    {
        "NC": "1",
        "MN": "Número-índice",
        "V": "197.2900",
        "D1C": "1",
        "D2C": "584",
        "D3C": "202601",
        "D3N": "1º trimestre 2026",
        "D4C": "90707",
        "D4N": "PIB a preços de mercado",
    },
    {
        "NC": "1",
        "MN": "Número-índice",
        "V": "...",
        "D1C": "1",
        "D2C": "584",
        "D3C": "202602",
        "D3N": "2º trimestre 2026",
        "D4C": "90707",
        "D4N": "PIB a preços de mercado",
    },
]

PAYLOAD_MOVEL = [
    {
        "MN": "Unidade de Medida",
        "V": "Valor",
        "D1C": "Brasil (Código)",
        "D2C": "Variável (Código)",
        "D3C": "Trimestre Móvel (Código)",
        "D3N": "Trimestre Móvel",
    },
    {"MN": "%", "V": "5.1", "D1C": "1", "D2C": "4099", "D3C": "202610", "D3N": "ago-set-out 2026"},
    {"MN": "%", "V": "-", "D1C": "1", "D2C": "4099", "D3C": "202609", "D3N": "jul-ago-set 2026"},
]


@pytest.mark.parametrize(
    ("codigo", "periodicidade", "esperado"),
    [
        ("202601", "trimestral", date(2026, 3, 1)),
        ("202604", "trimestral", date(2026, 12, 1)),
        ("202610", "trimestral_movel", date(2026, 10, 1)),
        ("201203", "trimestral_movel", date(2012, 3, 1)),
        ("202401", "mensal", date(2024, 1, 1)),
    ],
)
def test_periodo_para_data_usa_ultimo_mes_do_periodo(codigo, periodicidade, esperado):
    assert periodo_para_data(codigo, periodicidade) == esperado


def test_trimestre_civil_coincide_com_trimestre_movel_do_mesmo_fim():
    assert periodo_para_data("202602", "trimestral") == periodo_para_data(
        "202606", "trimestral_movel"
    )


@pytest.mark.parametrize(
    ("codigo", "periodicidade"),
    [
        ("202605", "trimestral"),
        ("202613", "trimestral_movel"),
        ("2026", "trimestral"),
        ("2026T1", "trimestral"),
        ("202601", "anual"),
    ],
)
def test_periodo_para_data_rejeita_codigos_invalidos(codigo, periodicidade):
    with pytest.raises(ValueError):
        periodo_para_data(codigo, periodicidade)


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("5.1", 5.1),
        ("-0.6", -0.6),
        ("-", 0.0),
        ("..", None),
        ("...", None),
        ("X", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_valor_trata_simbolos_especiais(bruto, esperado):
    assert parse_valor(bruto) == esperado


def test_parse_resposta_trimestral_localiza_periodo_pelo_cabecalho():
    periodicidade, registros = parse_resposta(PAYLOAD_TRIMESTRAL)
    assert periodicidade == "trimestral"
    assert registros == [
        RegistroSIDRA("202601", "1º trimestre 2026", date(2026, 3, 1), 197.29, "Número-índice")
    ]


def test_parse_resposta_movel_converte_zero_absoluto():
    periodicidade, registros = parse_resposta(PAYLOAD_MOVEL)
    assert periodicidade == "trimestral_movel"
    assert [(r.data, r.valor) for r in registros] == [
        (date(2026, 10, 1), 5.1),
        (date(2026, 9, 1), 0.0),
    ]


def test_parse_resposta_sem_coluna_de_periodo_falha():
    with pytest.raises(ValueError):
        parse_resposta([{"V": "Valor", "D1C": "Brasil (Código)"}])


def test_parse_resposta_so_cabecalho_retorna_vazio():
    assert parse_resposta(PAYLOAD_MOVEL[:1]) == ("trimestral_movel", [])


def test_montar_url_inclui_classificacao():
    serie = SerieSIDRA("pib", 1621, 584, "índice", "trimestral", ((11255, 90707),))
    assert montar_url(serie) == (
        "https://apisidra.ibge.gov.br/values/t/1621/n1/all/v/584/p/all/c11255/90707/d/m"
    )


def test_catalogo_tem_nomes_unicos():
    nomes = [s.nome for s in SERIES_IBGE]
    assert len(nomes) == len(set(nomes))


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_extrair_serie_filtra_por_inicio_e_valida_periodicidade():
    serie = SerieSIDRA("desocupacao_movel", 6381, 4099, "%", "trimestral_movel")
    with _client(lambda req: httpx.Response(200, json=PAYLOAD_MOVEL)) as client:
        registros = extrair_serie(serie, date(2026, 10, 1), client=client)
    assert [r.periodo_codigo for r in registros] == ["202610"]

    errada = SerieSIDRA("x", 6381, 4099, "%", "trimestral")
    with _client(lambda req: httpx.Response(200, json=PAYLOAD_MOVEL)) as client:
        with pytest.raises(ValueError, match="periodicidade"):
            extrair_serie(errada, date(2010, 1, 1), client=client)


def test_extrair_serie_propaga_mensagem_de_erro_400():
    serie = SerieSIDRA("x", 4099, 9999, "%", "trimestral")
    resposta = httpx.Response(400, text="Parâmetro V (Variável) com código 9999 inexistente")
    with _client(lambda req: resposta) as client:
        with pytest.raises(ValueError, match="9999 inexistente"):
            extrair_serie(serie, date(2010, 1, 1), client=client)
