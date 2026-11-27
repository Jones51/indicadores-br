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


@dataclass(frozen=True)
class SerieSIDRA:
    """Uma variável de uma tabela do SIDRA (IBGE), sempre no nível Brasil (n1)."""

    nome: str
    tabela: int
    variavel: int
    unidade: str
    periodicidade: str  # "trimestral" | "trimestral_movel" | "mensal"
    classificacoes: tuple[tuple[int, int], ...] = ()  # (classificação, categoria)


# Catálogo IBGE. Para adicionar uma série, inclua aqui e ela entra na ingestão.
# Tabelas e variáveis: https://sidra.ibge.gov.br (metadados em
# https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/metadados). Escolhas no ADR 0004.
PIB_PRECOS_MERCADO = (11255, 90707)  # classificação "Setores e subsetores" -> PIB total

SERIES_IBGE: tuple[SerieSIDRA, ...] = (
    SerieSIDRA("desocupacao", 4099, 4099, "%", "trimestral"),
    SerieSIDRA("desocupacao_movel", 6381, 4099, "%", "trimestral_movel"),
    SerieSIDRA(
        "pib_indice_sa", 1621, 584, "índice (1995=100)", "trimestral", (PIB_PRECOS_MERCADO,)
    ),
    SerieSIDRA(
        "pib_var_interanual",
        5932,
        6561,
        "% s/ mesmo tri do ano anterior",
        "trimestral",
        (PIB_PRECOS_MERCADO,),
    ),
)
