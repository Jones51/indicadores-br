"""Carga dos dados extraídos na camada raw do DuckDB."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from indicadores.config import DUCKDB_PATH, SerieSGS, SerieSIDRA
from indicadores.extract.ibge import RegistroSIDRA

# `extraido_em` é timestamptz: guarda o instante absoluto da carga, sem depender do fuso
# da sessão que gravou nem do fuso que o dbt assume ao calcular o freshness.
DDL_RAW = """
create schema if not exists raw;
create table if not exists raw.bcb_sgs (
    serie_codigo  integer     not null,
    serie_nome    varchar     not null,
    data          date        not null,
    valor         double      not null,
    extraido_em   timestamptz not null default current_timestamp
);
"""

# IBGE/SIDRA: uma linha por (série, período). A série é identificada pelo nome do catálogo,
# pois (tabela, variável, classificação) não cabe num código único como no SGS.
DDL_RAW_IBGE = """
create schema if not exists raw;
create table if not exists raw.ibge_sidra (
    serie_nome      varchar   not null,
    tabela          integer   not null,
    variavel        integer   not null,
    periodo_codigo  varchar   not null,
    periodo_nome    varchar   not null,
    data            date      not null,
    valor           double    not null,
    unidade         varchar   not null,
    extraido_em     timestamptz not null default current_timestamp
);
"""

# Tabelas raw com `extraido_em`: todas passam pela migração para timestamptz em `conectar()`.
TABELAS_RAW = ("bcb_sgs", "ibge_sidra")


def _migrar_extraido_em(con: duckdb.DuckDBPyConnection, tabela: str = "bcb_sgs") -> bool:
    """Converte `extraido_em` de `timestamp` para `timestamptz` em bancos antigos.

    `create table if not exists` não altera tabelas existentes, então bancos criados antes
    da mudança ainda têm a coluna sem fuso. O valor antigo era `current_timestamp` (que é
    timestamptz) convertido para `timestamp`, ou seja, a hora de parede no fuso da sessão
    que gravou. O cast `timestamp -> timestamptz` do DuckDB interpreta o valor no fuso da
    sessão atual (`TimeZone`), o que reconstrói o instante correto quando a migração roda
    no mesmo fuso em que os dados foram gravados (caso normal: mesma máquina). Default e
    `not null` são preservados pelo `alter ... type`.

    Retorna True se migrou.
    """
    if tabela not in TABELAS_RAW:
        raise ValueError(f"tabela raw desconhecida: {tabela}")
    tipo = con.execute(
        "select data_type from duckdb_columns() "
        "where schema_name = 'raw' and table_name = ? and column_name = 'extraido_em'",
        [tabela],
    ).fetchone()
    if tipo is None or tipo[0] != "TIMESTAMP":
        return False
    con.execute(f"alter table raw.{tabela} alter extraido_em type timestamptz")
    return True


def conectar(path: Path = DUCKDB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(DDL_RAW)
    con.execute(DDL_RAW_IBGE)
    for tabela in TABELAS_RAW:
        _migrar_extraido_em(con, tabela)
    return con


def carregar_serie(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSGS,
    registros: list[tuple[date, float]],
) -> int:
    """Substitui todos os registros da série (carga full idempotente). Retorna nº de linhas."""
    con.execute("begin")
    try:
        con.execute("delete from raw.bcb_sgs where serie_codigo = ?", [serie.codigo])
        if registros:
            con.executemany(
                "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) "
                "values (?, ?, ?, ?)",
                [(serie.codigo, serie.nome, d, v) for d, v in registros],
            )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    return len(registros)


def carregar_serie_ibge(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSIDRA,
    registros: list[RegistroSIDRA],
) -> int:
    """Substitui todos os registros da série IBGE (carga full idempotente). Retorna nº de linhas."""
    con.execute("begin")
    try:
        con.execute("delete from raw.ibge_sidra where serie_nome = ?", [serie.nome])
        if registros:
            con.executemany(
                "insert into raw.ibge_sidra (serie_nome, tabela, variavel, periodo_codigo, "
                "periodo_nome, data, valor, unidade) values (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        serie.nome,
                        serie.tabela,
                        serie.variavel,
                        r.periodo_codigo,
                        r.periodo_nome,
                        r.data,
                        r.valor,
                        r.unidade,
                    )
                    for r in registros
                ],
            )
        con.execute("commit")
    except Exception:
        con.execute("rollback")
        raise
    return len(registros)
