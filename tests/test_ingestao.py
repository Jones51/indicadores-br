from dataclasses import asdict
from datetime import date, timedelta

import pytest
from conftest import DESOC_MOVEL, IPCA, PIB, SELIC, SERIES_BCB_TESTE, SERIES_IBGE_TESTE

from indicadores.ingestao import execucao_id_atual, ingerir, resumo_markdown
from indicadores.load import COLUNAS_CARGA, JanelaVaziaError, conectar

INICIO = date(2023, 1, 1)
T0 = date(2024, 6, 30)  # primeira carga
T1 = date(2024, 9, 30)  # três meses depois: dados novos + revisões

SQL_RAW = {
    "bcb_sgs": "select serie_codigo, serie_nome, data, valor from raw.bcb_sgs order by all",
    "ibge_sidra": (
        "select serie_nome, tabela, variavel, periodo_codigo, periodo_nome, data, valor, unidade "
        "from raw.ibge_sidra order by all"
    ),
}


def _rodar(con, fonte, hoje, **kwargs):
    with fonte.client() as client:
        return ingerir(
            con,
            SERIES_BCB_TESTE,
            SERIES_IBGE_TESTE,
            inicio_padrao=INICIO,
            hoje=hoje,
            execucao_id=f"teste-{hoje}-{kwargs.get('forcar_full', False)}",
            client_bcb=client,
            client_ibge=client,
            **kwargs,
        )


def _raw(con) -> dict[str, list[tuple]]:
    return {tabela: con.execute(sql).fetchall() for tabela, sql in SQL_RAW.items()}


def _revisar_dentro_da_margem(fonte):
    fonte.bcb[SELIC.codigo][T0 - timedelta(days=30)] = 99.0  # diária: margem de 90 dias
    fonte.bcb[IPCA.codigo][date(2024, 5, 1)] = 9.9  # mensal: 2 meses antes do último (jun)
    fonte.ibge[DESOC_MOVEL.nome][date(2024, 5, 1)] = 9.9
    fonte.ibge[PIB.nome][date(2024, 3, 1)] = 999.0  # trimestral: 1º tri, 1 antes do último


@pytest.fixture
def con(tmp_path):
    con = conectar(tmp_path / "incremental.duckdb")
    yield con
    con.close()


def test_incremental_equivale_ao_full_com_dados_novos_e_revisao_na_margem(fonte, con, tmp_path):
    fonte.publicar_ate(T0)
    primeira = _rodar(con, fonte, T0)
    assert {c.modo for c in primeira} == {"full"}
    assert {c.motivo for c in primeira} == {"sem_dados"}

    fonte.publicar_ate(T1)
    _revisar_dentro_da_margem(fonte)
    segunda = _rodar(con, fonte, T1)
    assert {c.modo for c in segunda} == {"incremental"}

    direto = conectar(tmp_path / "full.duckdb")
    try:
        _rodar(direto, fonte, T1, forcar_full=True)
        assert _raw(con) == _raw(direto)
    finally:
        direto.close()
    # e as revisões de fato entraram
    assert (99.0,) in con.execute("select valor from raw.bcb_sgs").fetchall()


def test_incremental_pede_so_a_janela(fonte, con):
    fonte.publicar_ate(T0)
    _rodar(con, fonte, T0)
    fonte.requisicoes.clear()
    fonte.publicar_ate(T1)
    cargas = {c.serie_nome: c for c in _rodar(con, fonte, T1)}

    assert cargas["selic_meta"].inicio_pedido == T0 - timedelta(days=90)
    assert cargas["ipca_mensal"].inicio_pedido == date(2024, 4, 1)
    assert cargas["pib_indice_sa"].inicio_pedido == date(2023, 12, 1)
    urls = [str(r.url) for r in fonte.requisicoes]
    sgs_selic = next(u for u in urls if "bcdata.sgs.432" in u)
    assert "dataInicial=01%2F04%2F2024" in sgs_selic and "dataFinal=30%2F09%2F2024" in sgs_selic
    assert any("/t/1621/" in u and "/p/202304-202403/" in u for u in urls)  # dez/23 a set/24
    assert any("/t/6381/" in u and "/p/202404-202409/" in u for u in urls)
    assert not any("/p/all/" in u for u in urls)
    # janela sobreposta: o que já existia no intervalo é removido e reinserido
    assert cargas["selic_meta"].linhas_removidas == 91
    assert cargas["selic_meta"].linhas_recebidas == 91 + 92


def test_rodar_de_novo_e_idempotente(fonte, con):
    fonte.publicar_ate(T0)
    _rodar(con, fonte, T0)
    antes = _raw(con)
    _rodar(con, fonte, T0)
    assert _raw(con) == antes


def test_auditoria_grava_uma_linha_por_serie_com_os_campos(fonte, con):
    fonte.publicar_ate(T0)
    _rodar(con, fonte, T0)
    fonte.publicar_ate(T1)
    cargas = _rodar(con, fonte, T1)

    linhas = con.execute(
        f"select {', '.join(COLUNAS_CARGA)}, epoch(executado_em) from raw.cargas "
        "where execucao_id = ? order by fonte, serie_nome",
        [cargas[0].execucao_id],
    ).fetchall()
    assert len(linhas) == len(SERIES_BCB_TESTE) + len(SERIES_IBGE_TESTE)
    gravadas = {linha[2]: dict(zip(COLUNAS_CARGA, linha, strict=False)) for linha in linhas}
    selic = next(c for c in cargas if c.serie_nome == "selic_meta")
    esperado = asdict(selic)
    obtido = gravadas["selic_meta"]
    assert {k: v for k, v in obtido.items() if k != "duracao_s"} == {
        k: v for k, v in esperado.items() if k != "duracao_s"
    }
    assert obtido["fonte"] == "bcb" and obtido["modo"] == "incremental"
    assert obtido["ultima_data_antes"] == T0 and obtido["ultima_data_depois"] == T1
    assert obtido["linhas_inseridas"] == obtido["linhas_recebidas"]
    assert all(linha[-1] is not None for linha in linhas)  # executado_em preenchido
    assert gravadas["pib_indice_sa"]["fonte"] == "ibge"

    resumo = resumo_markdown(con)
    assert "| bcb | `selic_meta` | incremental | margem |" in resumo
    assert f"{T0} → {T1}" in resumo


def test_fonte_vazia_na_janela_nao_apaga_e_nao_audita(fonte, con):
    fonte.publicar_ate(T0)
    _rodar(con, fonte, T0)
    antes = _raw(con)
    (n_cargas,) = con.execute("select count(*) from raw.cargas").fetchone()
    fonte.bcb[SELIC.codigo].clear()  # API "fora do ar": 404 em tudo

    with pytest.raises(JanelaVaziaError):
        _rodar(con, fonte, T1)

    assert _raw(con) == antes
    assert con.execute("select count(*) from raw.cargas").fetchone() == (n_cargas,)


def test_serie_com_data_no_futuro_vira_full(fonte, con):
    fonte.publicar_ate(T0)
    _rodar(con, fonte, T0)
    con.execute(
        "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) "
        "values (432, 'selic_meta', date '2030-01-01', 1.0)"
    )
    cargas = {c.serie_nome: c for c in _rodar(con, fonte, T0)}
    assert (cargas["selic_meta"].modo, cargas["selic_meta"].motivo) == ("full", "estado_invalido")
    assert cargas["ipca_mensal"].modo == "incremental"
    assert con.execute("select max(data) from raw.bcb_sgs where serie_codigo = 432").fetchone() == (
        T0,
    )


def test_execucao_id_usa_github_run_id(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    assert execucao_id_atual() == "123-2"
    monkeypatch.delenv("GITHUB_RUN_ID")
    assert execucao_id_atual().startswith("local-")
    assert execucao_id_atual() != execucao_id_atual()
