"""Orquestração da ingestão: decide a janela de cada série, extrai, substitui e audita.

Cada série é uma unidade atômica: a substituição em `raw.bcb_sgs`/`raw.ibge_sidra` e a linha
de auditoria em `raw.cargas` entram na mesma transação. Ou a série é carregada e auditada, ou
nada muda.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Iterable
from datetime import UTC, date, datetime

import duckdb
import httpx

from indicadores.config import SerieSGS, SerieSIDRA
from indicadores.extract import bcb, ibge
from indicadores.incremental import calcular_janela
from indicadores.load import (
    Carga,
    registrar_carga,
    substituir_bcb,
    substituir_ibge,
    transacao,
    ultima_data_bcb,
    ultima_data_ibge,
)


def execucao_id_atual() -> str:
    """Identificador da execução: `GITHUB_RUN_ID[-tentativa]` na CI, senão um id local único."""
    run_id = os.getenv("GITHUB_RUN_ID")
    if run_id:
        tentativa = os.getenv("GITHUB_RUN_ATTEMPT")
        return f"{run_id}-{tentativa}" if tentativa else run_id
    agora = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"local-{agora}-{secrets.token_hex(3)}"


def ingerir_serie_bcb(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSGS,
    *,
    inicio_padrao: date,
    hoje: date,
    execucao_id: str,
    forcar_full: bool = False,
    motivo_full: str = "forcado",
    client: httpx.Client | None = None,
) -> Carga:
    t0 = time.perf_counter()
    antes = ultima_data_bcb(con, serie)
    janela = calcular_janela(
        antes, serie.periodicidade, inicio_padrao, hoje, forcar_full, motivo_full
    )
    registros = bcb.extrair_serie(serie, janela.inicio, hoje, client=client)
    desde = janela.inicio if janela.modo == "incremental" else None
    with transacao(con):
        sub = substituir_bcb(con, serie, registros, desde, exigir_dados=True)
        carga = Carga(
            execucao_id=execucao_id,
            fonte="bcb",
            serie_nome=serie.nome,
            modo=janela.modo,
            motivo=janela.motivo,
            inicio_pedido=janela.inicio,
            ultima_data_antes=antes,
            ultima_data_depois=ultima_data_bcb(con, serie),
            linhas_recebidas=len(registros),
            linhas_removidas=sub.removidas,
            linhas_inseridas=sub.inseridas,
            duracao_s=round(time.perf_counter() - t0, 3),
        )
        registrar_carga(con, carga)
    return carga


def ingerir_serie_ibge(
    con: duckdb.DuckDBPyConnection,
    serie: SerieSIDRA,
    *,
    inicio_padrao: date,
    hoje: date,
    execucao_id: str,
    forcar_full: bool = False,
    motivo_full: str = "forcado",
    client: httpx.Client | None = None,
) -> Carga:
    t0 = time.perf_counter()
    antes = ultima_data_ibge(con, serie)
    janela = calcular_janela(
        antes, serie.periodicidade, inicio_padrao, hoje, forcar_full, motivo_full
    )
    incremental = janela.modo == "incremental"
    registros = ibge.extrair_serie(
        serie, janela.inicio, client=client, ate=hoje if incremental else None
    )
    with transacao(con):
        sub = substituir_ibge(
            con, serie, registros, janela.inicio if incremental else None, exigir_dados=True
        )
        carga = Carga(
            execucao_id=execucao_id,
            fonte="ibge",
            serie_nome=serie.nome,
            modo=janela.modo,
            motivo=janela.motivo,
            inicio_pedido=janela.inicio,
            ultima_data_antes=antes,
            ultima_data_depois=ultima_data_ibge(con, serie),
            linhas_recebidas=len(registros),
            linhas_removidas=sub.removidas,
            linhas_inseridas=sub.inseridas,
            duracao_s=round(time.perf_counter() - t0, 3),
        )
        registrar_carga(con, carga)
    return carga


def ingerir(
    con: duckdb.DuckDBPyConnection,
    series_bcb: Iterable[SerieSGS],
    series_ibge: Iterable[SerieSIDRA],
    *,
    inicio_padrao: date,
    hoje: date | None = None,
    execucao_id: str | None = None,
    forcar_full: bool = False,
    motivo_full: str = "forcado",
    client_bcb: httpx.Client | None = None,
    client_ibge: httpx.Client | None = None,
    ao_carregar=None,
) -> list[Carga]:
    """Ingere as séries pedidas. `ao_carregar(carga)` é chamado após cada série (ex.: log)."""
    hoje = hoje or date.today()
    execucao_id = execucao_id or execucao_id_atual()
    comum = dict(
        inicio_padrao=inicio_padrao,
        hoje=hoje,
        execucao_id=execucao_id,
        forcar_full=forcar_full,
        motivo_full=motivo_full,
    )
    cargas = []
    for serie in series_bcb:
        cargas.append(ingerir_serie_bcb(con, serie, client=client_bcb, **comum))
        if ao_carregar:
            ao_carregar(cargas[-1])
    for serie in series_ibge:
        cargas.append(ingerir_serie_ibge(con, serie, client=client_ibge, **comum))
        if ao_carregar:
            ao_carregar(cargas[-1])
    return cargas


def _fmt_data(d: date | None) -> str:
    return d.isoformat() if d else "—"


def formatar_carga(carga: Carga) -> str:
    """Linha de log de uma carga."""
    return (
        f"[ok] {carga.fonte}/{carga.serie_nome:<20} {carga.modo:<11} desde "
        f"{carga.inicio_pedido}: {carga.linhas_recebidas} recebidas, "
        f"-{carga.linhas_removidas}/+{carga.linhas_inseridas}, última "
        f"{_fmt_data(carga.ultima_data_antes)} -> {_fmt_data(carga.ultima_data_depois)} "
        f"({carga.duracao_s:.1f}s)"
    )


def resumo_markdown(con: duckdb.DuckDBPyConnection, execucao_id: str | None = None) -> str:
    """Tabela markdown das cargas de uma execução (padrão: a mais recente em `raw.cargas`)."""
    if execucao_id is None:
        linha = con.execute(
            "select execucao_id from raw.cargas order by executado_em desc limit 1"
        ).fetchone()
        if linha is None:
            return "_Nenhuma carga registrada em `raw.cargas`._\n"
        (execucao_id,) = linha
    linhas = con.execute(
        "select fonte, serie_nome, modo, motivo, inicio_pedido, ultima_data_antes, "
        "ultima_data_depois, linhas_recebidas, linhas_removidas, linhas_inseridas, duracao_s "
        "from raw.cargas where execucao_id = ? order by executado_em, fonte, serie_nome",
        [execucao_id],
    ).fetchall()
    saida = [
        f"### Ingestão — execução `{execucao_id}`",
        "",
        "| Fonte | Série | Modo | Motivo | Desde | Última data (antes → depois) "
        "| Recebidas | Removidas | Inseridas | Duração |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for fonte, nome, modo, motivo, inicio, antes, depois, rec, rem, ins, dur in linhas:
        saida.append(
            f"| {fonte} | `{nome}` | {modo} | {motivo} | {inicio} | "
            f"{_fmt_data(antes)} → {_fmt_data(depois)} | {rec} | {rem} | {ins} | {dur:.1f}s |"
        )
    if not linhas:
        saida.append("| — | — | — | — | — | — | 0 | 0 | 0 | — |")
    return "\n".join(saida) + "\n"
