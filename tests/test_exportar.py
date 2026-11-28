import json
from datetime import UTC, date, datetime, timedelta, timezone

import duckdb
import pytest

from indicadores.exportar import (
    COLUNAS,
    exportar,
    ler_ultimas_cargas,
    linhas_para_meses,
    montar_payload,
)
from indicadores.load import DDL_RAW_CARGAS

DDL_MART = """
create schema marts;
create table marts.fct_indicadores_mensais (
    mes_referencia       date,
    selic_meta_aa        double,
    ipca_mensal          double,
    ipca_12m             double,
    juro_real_ex_post_aa double,
    dolar_ptax_medio     double,
    dolar_ptax_fim_mes   double,
    meta_inflacao        double,
    meta_inflacao_inferior double,
    meta_inflacao_superior double,
    status_meta_inflacao varchar,
    meses_seguidos_status_meta bigint,
    coluna_extra         varchar  -- coluna fora do contrato: não deve ir para o JSON
);
"""


@pytest.fixture
def warehouse(tmp_path):
    caminho = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(caminho))
    con.execute(DDL_MART)
    con.executemany(
        "insert into marts.fct_indicadores_mensais values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # fora de ordem de propósito: a exportação ordena por mês
            # mês corrente: sem IPCA, mas com meta (o status e a sequência ficam nulos)
            (date(2024, 2, 1), 11.25, None, None, None, 4.9712345678, 4.98, 3.0, 1.5, 4.5)
            + (None, None, "x"),
            (date(2024, 1, 1), 11.75, 0.42, 4.51, 6.9286, 4.9, 4.95, 3.0, 1.5, 4.5)
            + ("acima", 4, "x"),
        ],
    )
    con.close()
    return caminho


def test_linhas_para_meses_converte_datas_arredonda_e_trata_nulos():
    linhas = [
        (date(2024, 1, 1), 11.75, None, 4.5, float("nan"), 4.9712345678, 5)
        + (3.0, 1.5, 4.5, "dentro", 12)
    ]
    assert linhas_para_meses(linhas) == [
        {
            "mes_referencia": "2024-01-01",
            "selic_meta_aa": 11.75,
            "ipca_mensal": None,
            "ipca_12m": 4.5,
            "juro_real_ex_post_aa": None,
            "dolar_ptax_medio": 4.9712,
            "dolar_ptax_fim_mes": 5,
            "meta_inflacao": 3.0,
            "meta_inflacao_inferior": 1.5,
            "meta_inflacao_superior": 4.5,
            "status_meta_inflacao": "dentro",
            "meses_seguidos_status_meta": 12,
        }
    ]


def test_linhas_para_meses_rejeita_linha_com_colunas_a_menos():
    with pytest.raises(ValueError):
        linhas_para_meses([(date(2024, 1, 1), 11.75)])


def test_montar_payload_normaliza_gerado_em_para_utc():
    payload = montar_payload([], datetime(2026, 11, 27, 12, 30, 15, 999, tzinfo=UTC))
    assert payload == {
        "gerado_em": "2026-11-27T12:30:15+00:00",
        "fonte": "BCB SGS",
        "ultimas_cargas": {},
        "meses": [],
    }


def test_montar_payload_inclui_ultimas_cargas_em_utc():
    brt = timezone(timedelta(hours=-3))
    payload = montar_payload(
        [],
        datetime(2026, 11, 27, tzinfo=UTC),
        {
            "ibge": datetime(2026, 11, 27, 6, 20, tzinfo=brt),
            "bcb": datetime(2026, 11, 27, 9, 0, tzinfo=UTC),
        },
    )
    assert list(payload["ultimas_cargas"]) == ["bcb", "ibge"]
    assert payload["ultimas_cargas"]["ibge"] == "2026-11-27T09:20:00+00:00"


def test_ler_ultimas_cargas_sem_tabela_retorna_vazio():
    con = duckdb.connect()
    assert ler_ultimas_cargas(con) == {}
    con.close()


def _registrar_cargas(caminho):
    con = duckdb.connect(str(caminho))
    con.execute(DDL_RAW_CARGAS)
    linhas = [
        ("r1", "bcb", "selic_meta", "2026-11-20 09:00:00+00"),
        ("r2", "bcb", "selic_meta", "2026-11-27 09:17:00+00"),
        ("r2", "ibge", "desocupacao", "2026-11-27 09:18:30+00"),
    ]
    for execucao, fonte, serie, quando in linhas:
        con.execute(
            "insert into raw.cargas values (?, ?, ?, 'incremental', 'margem', date '2026-08-01', "
            "null, null, 1, 1, 1, 0.1, ?::timestamptz)",
            [execucao, fonte, serie, quando],
        )
    con.close()


def test_exportar_grava_json_compacto_ordenado(warehouse, tmp_path):
    saida = tmp_path / "site" / "dashboard" / "dados.json"
    assert exportar(saida, warehouse) == 2

    texto = saida.read_text(encoding="utf-8")
    assert ": " not in texto and ", " not in texto  # separadores compactos
    payload = json.loads(texto)
    assert datetime.fromisoformat(payload["gerado_em"]).tzinfo is not None
    meses = payload["meses"]
    assert [m["mes_referencia"] for m in meses] == ["2024-01-01", "2024-02-01"]
    assert all(tuple(m) == COLUNAS for m in meses)
    assert meses[1]["ipca_12m"] is None
    assert meses[1]["meta_inflacao_superior"] == 4.5  # meta existe mesmo sem IPCA
    assert meses[1]["status_meta_inflacao"] is None
    assert meses[0]["status_meta_inflacao"] == "acima"
    assert meses[0]["meses_seguidos_status_meta"] == 4
    assert meses[1]["dolar_ptax_medio"] == 4.9712
    assert payload["ultimas_cargas"] == {}  # warehouse sem raw.cargas


def test_exportar_inclui_ultima_carga_por_fonte(warehouse, tmp_path):
    _registrar_cargas(warehouse)
    saida = tmp_path / "dados.json"
    exportar(saida, warehouse)
    payload = json.loads(saida.read_text(encoding="utf-8"))
    assert payload["ultimas_cargas"] == {
        "bcb": "2026-11-27T09:17:00+00:00",
        "ibge": "2026-11-27T09:18:30+00:00",
    }
    assert len(payload["meses"]) == 2  # formato existente preservado


def test_exportar_abre_warehouse_somente_leitura(warehouse, tmp_path):
    # Outra conexão de leitura aberta ao mesmo tempo não pode impedir a exportação.
    leitor = duckdb.connect(str(warehouse), read_only=True)
    try:
        assert exportar(tmp_path / "dados.json", warehouse) == 2
    finally:
        leitor.close()


def test_exportar_falha_sem_warehouse(tmp_path):
    with pytest.raises(FileNotFoundError):
        exportar(tmp_path / "dados.json", tmp_path / "nao_existe.duckdb")
