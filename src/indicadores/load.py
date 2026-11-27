"""Carga dos dados extraídos na camada raw do DuckDB."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from indicadores.config import DUCKDB_PATH, SerieSGS

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


def _migrar_extraido_em(con: duckdb.DuckDBPyConnection) -> bool:
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
    tipo = con.execute(
        "select data_type from duckdb_columns() "
        "where schema_name = 'raw' and table_name = 'bcb_sgs' and column_name = 'extraido_em'"
    ).fetchone()
    if tipo is None or tipo[0] != "TIMESTAMP":
        return False
    con.execute("alter table raw.bcb_sgs alter extraido_em type timestamptz")
    return True


def conectar(path: Path = DUCKDB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(DDL_RAW)
    _migrar_extraido_em(con)
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
