from datetime import date

import duckdb
import pytest
from conftest import IPCA, SELIC, SERIES_BCB_TESTE, SERIES_IBGE_TESTE

from indicadores.ingestao import ingerir
from indicadores.load import conectar
from indicadores.reconciliar import Comparacao, classificar, reconciliar

INICIO = date(2023, 1, 1)
T0, T1 = date(2024, 6, 30), date(2024, 9, 30)
CATALOGO = [s.nome for s in (*SERIES_BCB_TESTE, *SERIES_IBGE_TESTE)]


def _ingerir(caminho, fonte, hoje, execucao_id, **kwargs):
    con = conectar(caminho)
    try:
        with fonte.client() as client:
            ingerir(
                con,
                SERIES_BCB_TESTE,
                SERIES_IBGE_TESTE,
                inicio_padrao=INICIO,
                hoje=hoje,
                execucao_id=execucao_id,
                client_bcb=client,
                client_ibge=client,
                **kwargs,
            )
    finally:
        con.close()


@pytest.fixture
def bancos(fonte, tmp_path):
    """Incremental (full em T0 + incremental em T1) e full direto em T1, mesma fonte."""
    base, full = tmp_path / "prod.duckdb", tmp_path / "full.duckdb"
    fonte.publicar_ate(T0)
    _ingerir(base, fonte, T0, "run-1")
    fonte.publicar_ate(T1)
    return fonte, base, full


def _full(fonte, full):
    _ingerir(full, fonte, T1, "run-2", forcar_full=True, motivo_full="reconciliacao")


def _incremental(fonte, base):
    _ingerir(base, fonte, T1, "run-2")


def test_sem_revisao_fora_da_margem_nao_ha_divergencia(bancos):
    fonte, base, full = bancos
    _incremental(fonte, base)
    _full(fonte, full)
    comparacoes, relatorio = reconciliar(base, full, CATALOGO)
    assert {c.situacao for c in comparacoes} == {"igual"}
    assert "idênticos" in relatorio


def test_revisao_fora_da_margem_e_detectada_e_o_full_vence(bancos):
    fonte, base, full = bancos
    fonte.bcb[IPCA.codigo][date(2023, 2, 1)] = 7.77  # muito antes da margem de 2 meses
    _incremental(fonte, base)
    _full(fonte, full)

    comparacoes, relatorio = reconciliar(base, full, CATALOGO)

    por_serie = {c.serie_nome: c for c in comparacoes}
    ipca = por_serie["ipca_mensal"]
    assert ipca.situacao == "revisao"
    assert ipca.valores_diferentes == 1 and ipca.so_full == 0 and ipca.so_incremental == 0
    assert por_serie["selic_meta"].situacao == "igual"
    assert "| bcb | `ipca_mensal` | 2023-02-01 |" in relatorio  # exemplo linha a linha
    # o full (que segue para o build) tem o valor revisado; o incremental não
    con = duckdb.connect(str(full), read_only=True)
    try:
        valor_full = con.execute(
            "select valor from raw.bcb_sgs where serie_codigo = 433 and data = '2023-02-01'"
        ).fetchone()
        # auditoria: divergência registrada e histórico de cargas herdado do incremental
        rec = con.execute(
            "select situacao, valores_diferentes from raw.reconciliacoes "
            "where execucao_id = 'run-2' and serie_nome = 'ipca_mensal'"
        ).fetchone()
        execucoes = con.execute(
            "select execucao_id, modo, count(*) from raw.cargas group by all order by all"
        ).fetchall()
    finally:
        con.close()
    assert valor_full == (7.77,)
    assert rec == ("revisao", 1)
    assert execucoes == [("run-1", "full", 4), ("run-2", "full", 4), ("run-2", "incremental", 4)]


def test_reconciliar_duas_vezes_nao_duplica_auditoria(bancos):
    fonte, base, full = bancos
    _incremental(fonte, base)
    _full(fonte, full)
    reconciliar(base, full, CATALOGO)
    reconciliar(base, full, CATALOGO)
    con = duckdb.connect(str(full), read_only=True)
    try:
        assert con.execute("select count(*) from raw.cargas").fetchone() == (12,)
        assert con.execute("select count(*) from raw.reconciliacoes").fetchone() == (4,)
    finally:
        con.close()


def test_serie_que_sumiu_no_full_e_estrutural(bancos):
    fonte, base, full = bancos
    _incremental(fonte, base)
    _full(fonte, full)
    con = duckdb.connect(str(full))
    con.execute("delete from raw.bcb_sgs where serie_codigo = ?", [SELIC.codigo])
    con.close()
    comparacoes, relatorio = reconciliar(base, full, CATALOGO)
    selic = next(c for c in comparacoes if c.serie_nome == "selic_meta")
    assert (selic.situacao, selic.detalhe) == ("estrutural", "série sumiu no full")
    assert "Divergência estrutural" in relatorio


def _comparacao(**kwargs) -> Comparacao:
    padrao = dict(
        fonte="bcb",
        serie_nome="selic_meta",
        linhas_incremental=1000,
        linhas_full=1000,
        data_min_incremental=date(2010, 1, 1),
        data_min_full=date(2010, 1, 1),
        data_max_incremental=date(2026, 11, 27),
        data_max_full=date(2026, 11, 27),
        soma_incremental=1.0,
        soma_full=1.0,
        so_incremental=0,
        so_full=0,
        valores_diferentes=0,
        maior_diferenca=0.0,
    )
    return Comparacao(**{**padrao, **kwargs})


@pytest.mark.parametrize(
    ("kwargs", "situacao", "trecho"),
    [
        ({}, "igual", "sem diferenças"),
        ({"valores_diferentes": 3, "maior_diferenca": 0.25}, "revisao", "3 valores revisados"),
        ({"linhas_full": 1002, "so_full": 2}, "revisao", "2 linhas só no full"),
        ({"linhas_full": 995, "so_incremental": 5}, "revisao", "5 linhas só no incremental"),
        ({"linhas_full": 980, "so_incremental": 20}, "estrutural", "contagem caiu 2.0%"),
        ({"linhas_full": 0, "data_max_full": None}, "estrutural", "série sumiu no full"),
        ({"data_max_full": date(2026, 11, 20)}, "estrutural", "data máxima regrediu"),
        ({"serie_nome": "antiga", "linhas_full": 0}, "fora_do_catalogo", "fora do catálogo"),
    ],
)
def test_classificar(kwargs, situacao, trecho):
    obtida, detalhe = classificar(_comparacao(**kwargs), ["selic_meta"])
    assert obtida == situacao
    assert trecho in detalhe


def test_base_e_full_precisam_ser_diferentes(tmp_path):
    caminho = tmp_path / "x.duckdb"
    conectar(caminho).close()
    with pytest.raises(ValueError):
        reconciliar(caminho, caminho, CATALOGO)
