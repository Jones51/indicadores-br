from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from indicadores.config import SerieSGS
from indicadores.load import (
    DDL_RAW,
    TABELAS_CONTROLE,
    TABELAS_RAW,
    JanelaVaziaError,
    Substituicao,
    _migrar_extraido_em,
    carregar_serie,
    carregar_serie_ibge,
    conectar,
    substituir_bcb,
    substituir_ibge,
    transacao,
)

SELIC = SerieSGS(432, "selic_meta", "% a.a.", "diaria")
IPCA = SerieSGS(433, "ipca_mensal", "% a.m.", "mensal")


@pytest.fixture
def con(tmp_path):
    con = conectar(tmp_path / "warehouse.duckdb")
    yield con
    con.close()


def _tipo_extraido_em(con, tabela: str = "bcb_sgs") -> str:
    return con.execute(
        "select data_type from duckdb_columns() "
        "where schema_name = 'raw' and table_name = ? and column_name = 'extraido_em'",
        [tabela],
    ).fetchone()[0]


def _linhas(con, serie: SerieSGS) -> list[tuple[date, float]]:
    return con.execute(
        "select data, valor from raw.bcb_sgs where serie_codigo = ? order by data",
        [serie.codigo],
    ).fetchall()


def test_conectar_cria_schema_e_tabela(tmp_path):
    path = tmp_path / "sub" / "warehouse.duckdb"
    con = conectar(path)
    try:
        assert path.exists()
        colunas = con.execute(
            "select column_name, data_type, is_nullable from duckdb_columns() "
            "where schema_name = 'raw' and table_name = 'bcb_sgs' order by column_index"
        ).fetchall()
    finally:
        con.close()
    assert colunas == [
        ("serie_codigo", "INTEGER", False),
        ("serie_nome", "VARCHAR", False),
        ("data", "DATE", False),
        ("valor", "DOUBLE", False),
        ("extraido_em", "TIMESTAMP WITH TIME ZONE", False),
    ]


def test_conectar_eh_idempotente(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    con = conectar(path)
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75)])
    con.close()
    con = conectar(path)
    try:
        assert _linhas(con, SELIC) == [(date(2024, 1, 1), 11.75)]
    finally:
        con.close()


def test_carregar_serie_preenche_extraido_em_com_instante_atual(con):
    antes = datetime.now(UTC)
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75)])
    depois = datetime.now(UTC)
    # compara em epoch para não depender do tzdata do Python ao materializar timestamptz
    (epoch,) = con.execute("select epoch(extraido_em) from raw.bcb_sgs").fetchone()
    assert antes.timestamp() <= epoch <= depois.timestamp()


def test_carregar_serie_duas_vezes_nao_duplica(con):
    registros = [(date(2024, 1, 1), 11.75), (date(2024, 1, 2), 11.75)]
    assert carregar_serie(con, SELIC, registros) == 2
    assert carregar_serie(con, SELIC, registros) == 2
    assert _linhas(con, SELIC) == registros


def test_carregar_serie_substitui_so_a_serie_alvo(con):
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75)])
    carregar_serie(con, IPCA, [(date(2024, 1, 1), 0.42)])

    carregar_serie(con, SELIC, [(date(2024, 2, 1), 11.25)])

    assert _linhas(con, SELIC) == [(date(2024, 2, 1), 11.25)]
    assert _linhas(con, IPCA) == [(date(2024, 1, 1), 0.42)]


def test_carregar_serie_vazia_remove_registros_da_serie(con):
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75)])
    assert carregar_serie(con, SELIC, []) == 0
    assert _linhas(con, SELIC) == []


def test_carregar_serie_faz_rollback_em_erro(con):
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75)])

    # valor nulo viola o `not null` no meio do insert, depois do delete já executado
    with pytest.raises(duckdb.ConstraintException):
        carregar_serie(con, SELIC, [(date(2024, 2, 1), 11.25), (date(2024, 2, 2), None)])

    assert _linhas(con, SELIC) == [(date(2024, 1, 1), 11.75)]
    # a conexão continua utilizável (sem transação pendurada)
    assert carregar_serie(con, SELIC, [(date(2024, 3, 1), 10.75)]) == 1


DDL_ANTIGO = """
create schema raw;
create table raw.bcb_sgs (
    serie_codigo  integer   not null,
    serie_nome    varchar   not null,
    data          date      not null,
    valor         double    not null,
    extraido_em   timestamp not null default current_timestamp
);
"""


def test_migracao_converte_timestamp_antigo_preservando_o_instante():
    con = duckdb.connect()
    con.execute("set TimeZone = 'America/Sao_Paulo'")
    con.execute(DDL_ANTIGO)
    # bancos antigos gravavam a hora de parede local (UTC-3) sem fuso
    con.execute(
        "insert into raw.bcb_sgs values (432, 'selic_meta', date '2024-01-01', 11.75, "
        "timestamp '2026-11-27 10:00:00')"
    )

    assert _migrar_extraido_em(con) is True

    assert _tipo_extraido_em(con) == "TIMESTAMP WITH TIME ZONE"
    (epoch,) = con.execute("select epoch(extraido_em) from raw.bcb_sgs").fetchone()
    assert epoch == datetime(2026, 11, 27, 13, 0, tzinfo=UTC).timestamp()
    # default e not null sobrevivem ao alter
    con.execute(
        "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) "
        "values (1, 'dolar_ptax_venda', date '2024-01-02', 4.9)"
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute("insert into raw.bcb_sgs values (1, 'x', date '2024-01-03', 4.9, null)")
    con.close()


def test_migracao_nao_faz_nada_em_tabela_nova():
    con = duckdb.connect()
    con.execute(DDL_RAW)
    assert _migrar_extraido_em(con) is False
    assert _tipo_extraido_em(con) == "TIMESTAMP WITH TIME ZONE"
    con.close()


def test_conectar_migra_banco_existente(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    antigo = duckdb.connect(str(path))
    antigo.execute(DDL_ANTIGO)
    antigo.execute(
        "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) "
        "values (432, 'selic_meta', date '2024-01-01', 11.75)"
    )
    antigo.close()

    con = conectar(path)
    try:
        assert _tipo_extraido_em(con) == "TIMESTAMP WITH TIME ZONE"
        assert _linhas(con, SELIC) == [(date(2024, 1, 1), 11.75)]
    finally:
        con.close()


@pytest.mark.parametrize("tabela", TABELAS_RAW)
def test_toda_tabela_raw_nasce_com_extraido_em_timestamptz(tabela):
    # Trava o padrão para tabelas raw novas: o freshness do dbt v2 assume UTC em `timestamp`.
    con = conectar(Path(":memory:"))
    assert _tipo_extraido_em(con, tabela) == "TIMESTAMP WITH TIME ZONE"
    con.close()


def test_conectar_migra_tabela_ibge_antiga(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    antigo = duckdb.connect(str(path))
    antigo.execute(
        "create schema raw; create table raw.ibge_sidra (serie_nome varchar, "
        "extraido_em timestamp not null default current_timestamp)"
    )
    antigo.close()

    con = conectar(path)
    try:
        assert _tipo_extraido_em(con, "ibge_sidra") == "TIMESTAMP WITH TIME ZONE"
    finally:
        con.close()


def test_toda_coluna_de_tempo_do_schema_raw_tem_fuso():
    # Inclui as tabelas de controle (raw.cargas, raw.reconciliacoes): nenhuma `timestamp` sem fuso.
    con = conectar(Path(":memory:"))
    tipos = con.execute(
        "select table_name, column_name, data_type from duckdb_columns() "
        "where schema_name = 'raw' and data_type like 'TIMESTAMP%'"
    ).fetchall()
    con.close()
    tabelas = {t for t, _, _ in tipos}
    assert tabelas == set(TABELAS_RAW) | set(TABELAS_CONTROLE)
    assert {tipo for _, _, tipo in tipos} == {"TIMESTAMP WITH TIME ZONE"}


def test_carregar_serie_com_desde_substitui_so_a_janela(con):
    carregar_serie(con, SELIC, [(date(2024, 1, d), 11.75) for d in range(1, 11)])

    # janela a partir do dia 8: dias 8-10 saem, 8-12 entram (dia 9 revisado)
    novos = [(date(2024, 1, 8), 11.75), (date(2024, 1, 9), 11.5)]
    novos += [(date(2024, 1, d), 11.25) for d in (10, 11, 12)]
    with transacao(con):
        sub = substituir_bcb(con, SELIC, novos, desde=date(2024, 1, 8))

    assert sub == Substituicao(removidas=3, inseridas=5)
    linhas = _linhas(con, SELIC)
    assert len(linhas) == 12
    assert linhas[:7] == [(date(2024, 1, d), 11.75) for d in range(1, 8)]
    assert linhas[8] == (date(2024, 1, 9), 11.5)


def test_exigir_dados_impede_apagar_janela_com_resposta_vazia(con):
    carregar_serie(con, SELIC, [(date(2024, 1, 1), 11.75), (date(2024, 1, 2), 11.75)])
    with pytest.raises(JanelaVaziaError):
        with transacao(con):
            substituir_bcb(con, SELIC, [], desde=date(2024, 1, 2), exigir_dados=True)
    assert len(_linhas(con, SELIC)) == 2
    # janela realmente sem dados (nada a apagar) é aceita
    with transacao(con):
        assert substituir_bcb(con, SELIC, [], desde=date(2025, 1, 1), exigir_dados=True) == (0, 0)


def test_substituir_ibge_com_desde(con):
    from indicadores.config import SerieSIDRA
    from indicadores.extract.ibge import RegistroSIDRA

    pib = SerieSIDRA("pib", 1621, 584, "índice", "trimestral")
    regs = [
        RegistroSIDRA(f"2024{t:02d}", f"{t}º tri", date(2024, 3 * t, 1), t, "i") for t in (1, 2)
    ]
    carregar_serie_ibge(con, pib, regs)
    revisado = [RegistroSIDRA("202402", "2º tri", date(2024, 6, 1), 2.5, "i")]
    with transacao(con):
        assert substituir_ibge(con, pib, revisado, desde=date(2024, 6, 1)) == (1, 1)
    assert con.execute("select data, valor from raw.ibge_sidra order by data").fetchall() == [
        (date(2024, 3, 1), 1.0),
        (date(2024, 6, 1), 2.5),
    ]
