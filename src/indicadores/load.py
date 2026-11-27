"""Carga dos dados extraídos na camada raw do DuckDB.

A carga **substitui** um intervalo da série numa transação: a série inteira (full) ou só as
datas a partir de `desde` (incremental, ADR 0006). Nos dois casos é idempotente: repetir a
mesma carga produz o mesmo `raw`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass, fields
from datetime import date
from pathlib import Path
from typing import NamedTuple

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

# Auditoria da ingestão (ADR 0006): uma linha por série por execução de `indicadores ingest`.
DDL_RAW_CARGAS = """
create schema if not exists raw;
create table if not exists raw.cargas (
    execucao_id         varchar     not null,
    fonte               varchar     not null,
    serie_nome          varchar     not null,
    modo                varchar     not null,
    motivo              varchar     not null,
    inicio_pedido       date        not null,
    ultima_data_antes   date,
    ultima_data_depois  date,
    linhas_recebidas    integer     not null,
    linhas_removidas    integer     not null,
    linhas_inseridas    integer     not null,
    duracao_s           double      not null,
    executado_em        timestamptz not null default current_timestamp
);
"""

# Resultado da reconciliação incremental x full (ADR 0006): uma linha por série por execução.
DDL_RAW_RECONCILIACOES = """
create schema if not exists raw;
create table if not exists raw.reconciliacoes (
    execucao_id           varchar     not null,
    fonte                 varchar     not null,
    serie_nome            varchar     not null,
    linhas_incremental    integer     not null,
    linhas_full           integer     not null,
    data_min_incremental  date,
    data_min_full         date,
    data_max_incremental  date,
    data_max_full         date,
    soma_incremental      double,
    soma_full             double,
    so_incremental        integer     not null,
    so_full               integer     not null,
    valores_diferentes    integer     not null,
    maior_diferenca       double,
    situacao              varchar     not null,
    detalhe               varchar     not null,
    executado_em          timestamptz not null default current_timestamp
);
"""

DDLS = (DDL_RAW, DDL_RAW_IBGE, DDL_RAW_CARGAS, DDL_RAW_RECONCILIACOES)

# Tabelas raw com `extraido_em`: todas passam pela migração para timestamptz em `conectar()`.
TABELAS_RAW = ("bcb_sgs", "ibge_sidra")
# Tabelas raw de controle (auditoria): nasceram com `timestamptz`, não precisam de migração.
TABELAS_CONTROLE = ("cargas", "reconciliacoes")


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
    for ddl in DDLS:
        con.execute(ddl)
    for tabela in TABELAS_RAW:
        _migrar_extraido_em(con, tabela)
    return con


@contextmanager
def transacao(con: duckdb.DuckDBPyConnection) -> Iterator[None]:
    """`begin` ... `commit`, com `rollback` (e a exceção repassada) em qualquer erro."""
    con.execute("begin")
    try:
        yield
    except BaseException:
        con.execute("rollback")
        raise
    con.execute("commit")


class Substituicao(NamedTuple):
    removidas: int
    inseridas: int


class JanelaVaziaError(RuntimeError):
    """A fonte não devolveu nada para um intervalo que já tem dados: nada é apagado."""


def ultima_data_bcb(con: duckdb.DuckDBPyConnection, serie: SerieSGS) -> date | None:
    (ultima,) = con.execute(
        "select max(data) from raw.bcb_sgs where serie_codigo = ?", [serie.codigo]
    ).fetchone()
    return ultima


def ultima_data_ibge(con: duckdb.DuckDBPyConnection, serie: SerieSIDRA) -> date | None:
    (ultima,) = con.execute(
        "select max(data) from raw.ibge_sidra where serie_nome = ?", [serie.nome]
    ).fetchone()
    return ultima


def _remover(
    con: duckdb.DuckDBPyConnection,
    tabela: str,
    chave: str,
    valor: int | str,
    desde: date | None,
    recebidas: int,
    exigir_dados: bool,
) -> int:
    """Apaga a série (ou só `data >= desde`) e retorna quantas linhas saíram.

    Com `exigir_dados`, recusa apagar um intervalo com dados quando a fonte não devolveu nada:
    uma resposta vazia por instabilidade da API não pode virar perda de dados.
    """
    filtro, params = f"{chave} = ?", [valor]
    if desde is not None:
        filtro, params = f"{filtro} and data >= ?", [valor, desde]
    if exigir_dados and recebidas == 0:
        (existentes,) = con.execute(
            f"select count(*) from raw.{tabela} where {filtro}", params
        ).fetchone()
        if existentes:
            raise JanelaVaziaError(
                f"raw.{tabela} {chave}={valor!r}: a fonte não devolveu linhas para um intervalo "
                f"(desde {desde or 'o início'}) que tem {existentes}; nada foi apagado"
            )
    (removidas,) = con.execute(f"delete from raw.{tabela} where {filtro}", params).fetchone()
    return removidas


def substituir_bcb(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSGS,
    registros: list[tuple[date, float]],
    desde: date | None = None,
    exigir_dados: bool = False,
) -> Substituicao:
    """Substitui a série (ou o intervalo `data >= desde`). Não abre transação: use `transacao`."""
    removidas = _remover(
        con, "bcb_sgs", "serie_codigo", serie.codigo, desde, len(registros), exigir_dados
    )
    if registros:
        con.executemany(
            "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) values (?, ?, ?, ?)",
            [(serie.codigo, serie.nome, d, v) for d, v in registros],
        )
    return Substituicao(removidas, len(registros))


def substituir_ibge(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSIDRA,
    registros: list[RegistroSIDRA],
    desde: date | None = None,
    exigir_dados: bool = False,
) -> Substituicao:
    """Substitui a série IBGE (ou o intervalo `data >= desde`). Não abre transação."""
    removidas = _remover(
        con, "ibge_sidra", "serie_nome", serie.nome, desde, len(registros), exigir_dados
    )
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
    return Substituicao(removidas, len(registros))


def carregar_serie(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSGS,
    registros: list[tuple[date, float]],
    desde: date | None = None,
) -> int:
    """Substitui a série (ou `data >= desde`) numa transação. Retorna nº de linhas inseridas."""
    with transacao(con):
        return substituir_bcb(con, serie, registros, desde).inseridas


def carregar_serie_ibge(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSIDRA,
    registros: list[RegistroSIDRA],
    desde: date | None = None,
) -> int:
    """Substitui a série IBGE (ou `data >= desde`) numa transação. Retorna nº de inseridas."""
    with transacao(con):
        return substituir_ibge(con, serie, registros, desde).inseridas


@dataclass(frozen=True)
class Carga:
    """Uma linha de `raw.cargas` (`executado_em` vem do default da tabela)."""

    execucao_id: str
    fonte: str
    serie_nome: str
    modo: str
    motivo: str
    inicio_pedido: date
    ultima_data_antes: date | None
    ultima_data_depois: date | None
    linhas_recebidas: int
    linhas_removidas: int
    linhas_inseridas: int
    duracao_s: float


COLUNAS_CARGA = tuple(f.name for f in fields(Carga))


def registrar_carga(con: duckdb.DuckDBPyConnection, carga: Carga) -> None:
    marcadores = ", ".join("?" for _ in COLUNAS_CARGA)
    con.execute(
        f"insert into raw.cargas ({', '.join(COLUNAS_CARGA)}) values ({marcadores})",
        list(astuple(carga)),
    )
