"""CLI do pipeline: `uv run indicadores ingest | validar | reconciliar | resumo | exportar`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from indicadores.config import DUCKDB_PATH, SERIES_BCB, SERIES_IBGE
from indicadores.incremental import MOTIVOS_FULL

FONTES = ("bcb", "ibge")
# Motivos que fazem sentido pedir pela linha de comando (`sem_dados` é detectado sozinho).
MOTIVOS_CLI = tuple(m for m in MOTIVOS_FULL if m != "sem_dados")


def _forcar_utf8() -> None:
    # Saída redirecionada no Windows (cp1252) quebraria em "→" e acentos do relatório.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")


def cmd_ingest(args: argparse.Namespace) -> None:
    from indicadores.ingestao import formatar_carga, ingerir
    from indicadores.load import conectar

    inicio = date.fromisoformat(args.inicio)
    fontes = args.fonte or FONTES
    desconhecidas = set(args.series or ()) - {s.nome for s in (*SERIES_BCB, *SERIES_IBGE)}
    if desconhecidas:
        raise SystemExit(f"Séries desconhecidas: {', '.join(sorted(desconhecidas))}")
    series_bcb = [
        s for s in SERIES_BCB if "bcb" in fontes and (not args.series or s.nome in args.series)
    ]
    series_ibge = [
        s for s in SERIES_IBGE if "ibge" in fontes and (not args.series or s.nome in args.series)
    ]
    con = conectar(DUCKDB_PATH)
    try:
        ingerir(
            con,
            series_bcb,
            series_ibge,
            inicio_padrao=inicio,
            forcar_full=args.full,
            motivo_full=args.motivo,
            ao_carregar=lambda carga: print(formatar_carga(carga), flush=True),
        )
    finally:
        con.close()


# Códigos de saída de `validar`, distintos de 1 (exceção do Python) e 2 (erro do argparse) para
# que a CI nunca confunda uma falha inesperada com um diagnóstico.
SAIDA_INVALIDO = 3  # abre no DuckDB, mas não serve de base incremental: ainda vale como backup
SAIDA_CORROMPIDO = 4  # não existe ou não abre no DuckDB: nem base, nem backup


def cmd_validar(args: argparse.Namespace) -> None:
    from indicadores.estado import diagnosticar_estado

    diagnostico = diagnosticar_estado(args.db)
    if diagnostico.valido:
        print(f"[ok] estado válido: {args.db}")
        return
    rotulo = "inválido" if diagnostico.abre else "corrompido"
    for problema in diagnostico.problemas:
        print(f"[{rotulo}] {problema}")
    raise SystemExit(SAIDA_INVALIDO if diagnostico.abre else SAIDA_CORROMPIDO)


def cmd_herdar_auditoria(args: argparse.Namespace) -> None:
    from indicadores.auditoria import herdar_auditoria_de_arquivo

    for mensagem in herdar_auditoria_de_arquivo(args.origem, args.db):
        print(f"[auditoria] {mensagem}")


def cmd_reconciliar(args: argparse.Namespace) -> None:
    from indicadores.reconciliar import reconciliar

    catalogo = [s.nome for s in (*SERIES_BCB, *SERIES_IBGE)]
    comparacoes, relatorio = reconciliar(args.base, args.full, catalogo, args.execucao_id)
    print(relatorio)
    if args.relatorio:
        Path(args.relatorio).write_text(relatorio, encoding="utf-8")
    if any(c.situacao == "estrutural" for c in comparacoes):
        raise SystemExit(2)


def cmd_resumo(args: argparse.Namespace) -> None:
    import duckdb

    from indicadores.ingestao import resumo_markdown

    execucao_id = args.execucao_id
    if execucao_id is None and os.getenv("GITHUB_RUN_ID"):
        from indicadores.ingestao import execucao_id_atual

        execucao_id = execucao_id_atual()
    con = duckdb.connect(str(args.db), read_only=True)
    try:
        print(resumo_markdown(con, execucao_id))
    finally:
        con.close()


def cmd_exportar(args: argparse.Namespace) -> None:
    # Import local: o subcomando fica isolado e não mexe no bloco de imports do `ingest`.
    from indicadores.exportar import exportar

    n = exportar(args.saida)
    print(f"[ok] {n} meses -> {args.saida}")


def main() -> None:
    _forcar_utf8()
    parser = argparse.ArgumentParser(prog="indicadores")
    sub = parser.add_subparsers(dest="comando", required=True)
    db_padrao = str(DUCKDB_PATH)  # respeita a variável DUCKDB_PATH (config.py)

    p_ingest = sub.add_parser(
        "ingest",
        help="Extrai as séries do BCB e do IBGE para a raw (incremental por padrão; ADR 0006)",
    )
    p_ingest.add_argument("--inicio", default="2010-01-01", help="Início do histórico (AAAA-MM-DD)")
    p_ingest.add_argument("--series", nargs="*", help="Nomes das séries (padrão: todas)")
    p_ingest.add_argument(
        "--fonte", nargs="*", choices=FONTES, help="Fontes a ingerir (padrão: todas)"
    )
    p_ingest.add_argument(
        "--full", action="store_true", help="Recarga completa desde --inicio (ignora a margem)"
    )
    p_ingest.add_argument(
        "--motivo",
        default="forcado",
        choices=MOTIVOS_CLI,
        help="Motivo do --full registrado em raw.cargas (padrão: forcado)",
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_validar = sub.add_parser(
        "validar",
        help=(
            f"Valida um warehouse como estado inicial (0 = válido, {SAIDA_INVALIDO} = abre mas "
            f"é inválido, {SAIDA_CORROMPIDO} = não abre)"
        ),
    )
    p_validar.add_argument("--db", default=db_padrao, help="Warehouse a validar")
    p_validar.set_defaults(func=cmd_validar)

    p_herdar = sub.add_parser(
        "herdar-auditoria",
        help="Copia o histórico de raw.cargas/raw.reconciliacoes de outro warehouse (tolerante)",
    )
    p_herdar.add_argument("--origem", required=True, help="Warehouse de onde copiar (só leitura)")
    p_herdar.add_argument("--db", default=db_padrao, help="Warehouse que recebe o histórico")
    p_herdar.set_defaults(func=cmd_herdar_auditoria)

    p_rec = sub.add_parser(
        "reconciliar",
        help="Compara incremental x full e grava a auditoria no full (sai com 2 se estrutural)",
    )
    p_rec.add_argument("--base", required=True, help="Warehouse incremental (só leitura)")
    p_rec.add_argument("--full", required=True, help="Warehouse da carga full (recebe auditoria)")
    p_rec.add_argument("--relatorio", help="Grava o relatório markdown neste arquivo")
    p_rec.add_argument("--execucao-id", help="Id da execução (padrão: a última carga do full)")
    p_rec.set_defaults(func=cmd_reconciliar)

    p_resumo = sub.add_parser("resumo", help="Tabela markdown das cargas de uma execução")
    p_resumo.add_argument("--db", default=db_padrao, help="Warehouse a consultar")
    p_resumo.add_argument(
        "--execucao-id", help="Id da execução (padrão: a do run na CI, senão a mais recente)"
    )
    p_resumo.set_defaults(func=cmd_resumo)

    p_exportar = sub.add_parser("exportar", help="Exporta o mart para o JSON do dashboard")
    p_exportar.add_argument("--saida", default="dashboard/dados.json", help="Arquivo JSON de saída")
    p_exportar.set_defaults(func=cmd_exportar)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
