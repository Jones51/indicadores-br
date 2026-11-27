import json
from datetime import UTC, date, datetime

import duckdb
import pytest

from indicadores.exportar import COLUNAS, exportar, linhas_para_meses, montar_payload

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
    coluna_extra         varchar  -- coluna fora do contrato: não deve ir para o JSON
);
"""


@pytest.fixture
def warehouse(tmp_path):
    caminho = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(caminho))
    con.execute(DDL_MART)
    con.executemany(
        "insert into marts.fct_indicadores_mensais values (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            # fora de ordem de propósito: a exportação ordena por mês
            (date(2024, 2, 1), 11.25, None, None, None, 4.9712345678, 4.98, "x"),
            (date(2024, 1, 1), 11.75, 0.42, 4.51, 6.9286, 4.9, 4.95, "x"),
        ],
    )
    con.close()
    return caminho


def test_linhas_para_meses_converte_datas_arredonda_e_trata_nulos():
    linhas = [(date(2024, 1, 1), 11.75, None, 4.5, float("nan"), 4.9712345678, 5)]
    assert linhas_para_meses(linhas) == [
        {
            "mes_referencia": "2024-01-01",
            "selic_meta_aa": 11.75,
            "ipca_mensal": None,
            "ipca_12m": 4.5,
            "juro_real_ex_post_aa": None,
            "dolar_ptax_medio": 4.9712,
            "dolar_ptax_fim_mes": 5,
        }
    ]


def test_linhas_para_meses_rejeita_linha_com_colunas_a_menos():
    with pytest.raises(ValueError):
        linhas_para_meses([(date(2024, 1, 1), 11.75)])


def test_montar_payload_normaliza_gerado_em_para_utc():
    payload = montar_payload([], datetime(2026, 11, 27, 12, 30, 15, 999, tzinfo=UTC))
    assert payload == {"gerado_em": "2026-11-27T12:30:15+00:00", "fonte": "BCB SGS", "meses": []}


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
    assert meses[1]["dolar_ptax_medio"] == 4.9712


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
