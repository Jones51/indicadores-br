"""CLI do pipeline: `uv run indicadores ingest`."""

from __future__ import annotations

import argparse
from datetime import date

from indicadores.config import SERIES_BCB, SERIES_IBGE
from indicadores.extract import ibge
from indicadores.extract.bcb import extrair_serie
from indicadores.load import carregar_serie, carregar_serie_ibge, conectar

FONTES = ("bcb", "ibge")


def cmd_ingest(args: argparse.Namespace) -> None:
    inicio = date.fromisoformat(args.inicio)
    fontes = args.fonte or FONTES
    series_bcb = [s for s in SERIES_BCB if not args.series or s.nome in args.series]
    series_ibge = [s for s in SERIES_IBGE if not args.series or s.nome in args.series]
    desconhecidas = set(args.series or ()) - {s.nome for s in (*SERIES_BCB, *SERIES_IBGE)}
    if desconhecidas:
        raise SystemExit(f"Séries desconhecidas: {', '.join(sorted(desconhecidas))}")
    con = conectar()
    try:
        if "bcb" in fontes:
            for serie in series_bcb:
                registros = extrair_serie(serie, inicio)
                n = carregar_serie(con, serie, registros)
                print(f"[ok] {serie.nome:<20} ({serie.codigo:>5}) -> {n} linhas")
        if "ibge" in fontes:
            for serie in series_ibge:
                registros = ibge.extrair_serie(serie, inicio)
                n = carregar_serie_ibge(con, serie, registros)
                print(f"[ok] {serie.nome:<20} (t{serie.tabela:>4}) -> {n} linhas")
    finally:
        con.close()


def cmd_exportar(args: argparse.Namespace) -> None:
    # Import local: o subcomando fica isolado e não mexe no bloco de imports do `ingest`.
    from indicadores.exportar import exportar

    n = exportar(args.saida)
    print(f"[ok] {n} meses -> {args.saida}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="indicadores")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ingest = sub.add_parser(
        "ingest", help="Extrai séries do BCB e do IBGE e carrega em raw.bcb_sgs / raw.ibge_sidra"
    )
    p_ingest.add_argument("--inicio", default="2010-01-01", help="Data inicial (AAAA-MM-DD)")
    p_ingest.add_argument("--series", nargs="*", help="Nomes das séries (padrão: todas)")
    p_ingest.add_argument(
        "--fonte", nargs="*", choices=FONTES, help="Fontes a ingerir (padrão: todas)"
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_exportar = sub.add_parser("exportar", help="Exporta o mart para o JSON do dashboard")
    p_exportar.add_argument("--saida", default="dashboard/dados.json", help="Arquivo JSON de saída")
    p_exportar.set_defaults(func=cmd_exportar)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
