"""Herança do histórico de auditoria (`raw.cargas`, `raw.reconciliacoes`) entre warehouses.

O histórico vive no warehouse publicado. Quando um banco novo o substitui (o full que vence a
reconciliação, ou o full feito porque o estado foi descartado por schema), o banco novo herda o
histórico do anterior (ADR 0006).

A cópia é **tolerante**: usa só as colunas em comum entre origem e destino (uma tabela de
controle de schema antigo ainda é aproveitada) e nunca levanta exceção. Quando não dá para
copiar uma tabela, o motivo volta na lista de mensagens. Perder histórico de auditoria não pode
derrubar a publicação dos dados. Cada tabela é copiada na sua própria transação, porque um erro
dentro de uma transação do DuckDB a invalida inteira.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from indicadores.load import conectar, transacao

ALIAS_ORIGEM = "origem_auditoria"

# Chave de deduplicação por tabela: torna a cópia idempotente.
CHAVES_AUDITORIA: dict[str, tuple[str, ...]] = {
    "cargas": ("execucao_id", "serie_nome", "modo"),
    "reconciliacoes": ("execucao_id", "serie_nome"),
}


def _colunas(con: duckdb.DuckDBPyConnection, banco: str, tabela: str) -> list[str]:
    return [
        c
        for (c,) in con.execute(
            "select column_name from duckdb_columns() where database_name = ? "
            "and schema_name = 'raw' and table_name = ? order by column_index",
            [banco, tabela],
        ).fetchall()
    ]


def herdar_auditoria(con: duckdb.DuckDBPyConnection, origem: str) -> list[str]:
    """Copia para o banco principal de `con` o histórico do banco anexado como `origem`.

    Copia só as linhas cuja chave o destino ainda não tem. Retorna uma mensagem por tabela.
    """
    (destino,) = con.execute("select current_database()").fetchone()
    mensagens = []
    for tabela, chave in CHAVES_AUDITORIA.items():
        de, para = _colunas(con, origem, tabela), _colunas(con, destino, tabela)
        if not de:
            mensagens.append(f"raw.{tabela}: ausente na origem, nada a copiar")
            continue
        comuns = [c for c in para if c in de]
        sem_chave = [c for c in chave if c not in comuns]
        if sem_chave:
            mensagens.append(
                f"raw.{tabela}: não copiado, a origem não tem a chave {', '.join(sem_chave)}"
            )
            continue
        lista = ", ".join(comuns)
        igualdade = " and ".join(f"o.{c} = d.{c}" for c in chave)
        try:
            with transacao(con):
                (copiadas,) = con.execute(
                    f"insert into raw.{tabela} ({lista}) "
                    f"select {', '.join(f'o.{c}' for c in comuns)} "
                    f"from {origem}.raw.{tabela} as o "
                    f"where not exists (select 1 from raw.{tabela} as d where {igualdade})"
                ).fetchone()
        except duckdb.Error as erro:
            mensagens.append(f"raw.{tabela}: não copiado ({type(erro).__name__}: {erro})")
            continue
        detalhes = []
        if ignoradas := [c for c in de if c not in para]:
            detalhes.append(f"colunas só na origem ignoradas: {', '.join(ignoradas)}")
        if faltantes := [c for c in para if c not in de]:
            detalhes.append(f"colunas ausentes na origem: {', '.join(faltantes)}")
        sufixo = f" ({'; '.join(detalhes)})" if detalhes else ""
        mensagens.append(f"raw.{tabela}: {copiadas} linhas copiadas{sufixo}")
    return mensagens


def herdar_auditoria_de_arquivo(origem: Path | str, destino: Path | str) -> list[str]:
    """Abre `destino` (cria as tabelas se preciso), anexa `origem` só leitura e herda o histórico.

    Não levanta exceção por problema na origem: devolve o motivo como mensagem.
    """
    origem, destino = Path(origem), Path(destino)
    if origem.resolve() == destino.resolve():
        return ["origem e destino são o mesmo arquivo: nada a copiar"]
    con = conectar(destino)
    try:
        caminho = origem.as_posix().replace("'", "''")  # literal SQL: aspas escapadas
        try:
            con.execute(f"attach '{caminho}' as {ALIAS_ORIGEM} (read_only)")
        except duckdb.Error as erro:
            return [f"origem não abre, auditoria não herdada: {erro}"]
        try:
            return herdar_auditoria(con, ALIAS_ORIGEM)
        finally:
            con.execute(f"detach {ALIAS_ORIGEM}")
    finally:
        con.close()
