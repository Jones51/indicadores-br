"""CLI do pipeline: `uv run indicadores ingest`."""

from __future__ import annotations

import argparse
from datetime import date

from indicadores.config import SERIES_BCB
from indicadores.extract.bcb import extrair_serie
from indicadores.load import carregar_serie, conectar


def cmd_ingest(args: argparse.Namespace) -> None:
    inicio = date.fromisoformat(args.inicio)
    series = [s for s in SERIES_BCB if not args.series or s.nome in args.series]
    con = conectar()
    try:
        for serie in series:
            registros = extrair_serie(serie, inicio)
            n = carregar_serie(con, serie, registros)
            print(f"[ok] {serie.nome:<20} ({serie.codigo:>5}) -> {n} linhas")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="indicadores")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ingest = sub.add_parser("ingest", help="Extrai séries do BCB e carrega em raw.bcb_sgs")
    p_ingest.add_argument("--inicio", default="2010-01-01", help="Data inicial (AAAA-MM-DD)")
    p_ingest.add_argument("--series", nargs="*", help="Nomes das séries (padrão: todas)")
    p_ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
