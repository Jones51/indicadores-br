"""Cálculo da janela de ingestão incremental (funções puras, sem I/O).

Regra (ADR 0006): a carga incremental recomeça um pouco **antes** da última data carregada e
substitui esse intervalo inteiro, para absorver revisões recentes da fonte.

- séries diárias: `inicio = ultima - 90 dias`;
- séries mensais, trimestrais e de trimestre móvel: `inicio = ultima` recuada 2 períodos
  (o último período carregado e os 2 anteriores são recarregados).

A carga é **full** quando a série não tem dados, quando o estado dela é inválido (última data no
futuro) ou quando o full é pedido explicitamente.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

MARGEM_DIAS_DIARIA = 90
MARGEM_PERIODOS = 2

# Tamanho de um período em meses, por periodicidade do catálogo (BCB e IBGE).
MESES_POR_PERIODO: dict[str, int] = {
    "mensal": 1,
    "trimestral_movel": 1,  # um trimestre móvel por mês
    "trimestral": 3,
}

# Valores de `raw.cargas.modo` e `raw.cargas.motivo` (também testados no dbt).
MODOS = ("full", "incremental")
MOTIVOS_FULL = ("sem_dados", "forcado", "estado_invalido", "reconciliacao")
MOTIVO_INCREMENTAL = "margem"


class Janela(NamedTuple):
    modo: str  # "full" | "incremental"
    motivo: str  # um de MOTIVOS_FULL ou MOTIVO_INCREMENTAL
    inicio: date  # primeira data pedida à fonte (e, no incremental, início da substituição)


def recuar_meses(d: date, meses: int) -> date:
    """Primeiro dia do mês que fica `meses` meses antes do mês de `d`."""
    total = d.year * 12 + (d.month - 1) - meses
    return date(total // 12, total % 12 + 1, 1)


def inicio_com_margem(ultima: date, periodicidade: str) -> date:
    """Data a partir da qual a série é recarregada, dada a última data já carregada."""
    if periodicidade == "diaria":
        return ultima - timedelta(days=MARGEM_DIAS_DIARIA)
    if periodicidade in MESES_POR_PERIODO:
        return recuar_meses(ultima, MARGEM_PERIODOS * MESES_POR_PERIODO[periodicidade])
    raise ValueError(f"Periodicidade desconhecida: {periodicidade!r}")


def calcular_janela(
    ultima: date | None,
    periodicidade: str,
    inicio_padrao: date,
    hoje: date,
    forcar_full: bool = False,
    motivo_full: str = "forcado",
) -> Janela:
    """Decide modo e data inicial da carga de uma série.

    `inicio_padrao` é o início do histórico (`--inicio`): o full parte dele e o incremental
    nunca começa antes dele.
    """
    if forcar_full:
        if motivo_full not in MOTIVOS_FULL:
            raise ValueError(f"Motivo de full desconhecido: {motivo_full!r}")
        return Janela("full", motivo_full, inicio_padrao)
    if ultima is None:
        return Janela("full", "sem_dados", inicio_padrao)
    if ultima > hoje:  # dado "do futuro": estado corrompido, não dá para confiar na margem
        return Janela("full", "estado_invalido", inicio_padrao)
    inicio = max(inicio_padrao, inicio_com_margem(ultima, periodicidade))
    return Janela("incremental", MOTIVO_INCREMENTAL, inicio)
