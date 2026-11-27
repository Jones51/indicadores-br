"""Validação do estado herdado (o `prod.duckdb` da release) antes de usá-lo como base incremental.

Um estado inválido não é consertado: a CI descarta o arquivo e faz carga full (ADR 0006). Por
isso a validação só **lê** o arquivo (`read_only`) e devolve a lista de problemas encontrados.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from indicadores.load import DDLS, TABELAS_CONTROLE, TABELAS_RAW

# Chave de unicidade por tabela de dados: duplicata aqui faria a carga incremental divergir.
CHAVES = {"bcb_sgs": ("serie_codigo", "data"), "ibge_sidra": ("serie_nome", "data")}

SQL_COLUNAS = (
    "select table_name, column_name, data_type, is_nullable from duckdb_columns() "
    "where schema_name = 'raw' order by table_name, column_index"
)


def _colunas(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[str, str, bool]]]:
    tabelas: dict[str, list[tuple[str, str, bool]]] = {}
    for tabela, coluna, tipo, nulavel in con.execute(SQL_COLUNAS).fetchall():
        tabelas.setdefault(tabela, []).append((coluna, tipo, nulavel))
    return tabelas


def esquema_esperado() -> dict[str, list[tuple[str, str, bool]]]:
    """Schema raw que o código atual cria (derivado dos próprios DDLs, sem duplicar a definição)."""
    con = duckdb.connect()
    try:
        for ddl in DDLS:
            con.execute(ddl)
        return _colunas(con)
    finally:
        con.close()


def validar_estado(path: Path | str) -> list[str]:
    """Retorna os problemas do warehouse em `path`; lista vazia = pode servir de base incremental.

    Verifica: o arquivo existe e abre no DuckDB; as tabelas de dados (`TABELAS_RAW`) existem
    com o schema esperado; as de controle (`TABELAS_CONTROLE`), se existirem, também (bancos
    anteriores à auditoria não as têm, e `conectar()` as cria); e não há duplicatas na chave.
    """
    path = Path(path)
    if not path.exists():
        return [f"arquivo não existe: {path}"]
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as erro:
        return [f"não abre no DuckDB: {erro}"]
    try:
        esperado, real = esquema_esperado(), _colunas(con)
        problemas = []
        for tabela in (*TABELAS_RAW, *TABELAS_CONTROLE):
            if tabela not in real:
                if tabela in TABELAS_RAW:
                    problemas.append(f"tabela raw.{tabela} ausente")
                continue
            if real[tabela] != esperado[tabela]:
                problemas.append(
                    f"raw.{tabela} com schema diferente do esperado: "
                    f"{real[tabela]} (esperado {esperado[tabela]})"
                )
        if problemas:
            return problemas
        for tabela, chave in CHAVES.items():
            colunas = ", ".join(chave)
            (duplicadas,) = con.execute(
                f"select count(*) from (select {colunas} from raw.{tabela} "
                f"group by {colunas} having count(*) > 1)"
            ).fetchone()
            if duplicadas:
                problemas.append(f"raw.{tabela}: {duplicadas} chaves ({colunas}) duplicadas")
        return problemas
    finally:
        con.close()
