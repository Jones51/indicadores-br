"""Configuração central: caminhos e catálogo de séries."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUCKDB_PATH = Path(os.getenv("DUCKDB_PATH", PROJECT_ROOT / "data" / "warehouse.duckdb"))


@dataclass(frozen=True)
class SerieSGS:
    """Uma série temporal do SGS (Sistema Gerenciador de Séries) do Banco Central."""

    codigo: int
    nome: str
    unidade: str
    periodicidade: str  # "diaria" | "mensal"


# Catálogo inicial. Para adicionar uma série, inclua aqui e ela entra na ingestão.
# Códigos: https://www3.bcb.gov.br/sgspub
SERIES_BCB: tuple[SerieSGS, ...] = (
    SerieSGS(432, "selic_meta", "% a.a.", "diaria"),
    SerieSGS(433, "ipca_mensal", "% a.m.", "mensal"),
    SerieSGS(13522, "ipca_12m", "% 12 meses", "mensal"),
    SerieSGS(1, "dolar_ptax_venda", "R$/US$", "diaria"),
)
