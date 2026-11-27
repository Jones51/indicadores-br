"""Exporta o mart mensal para o JSON consumido pelo dashboard estático (`dashboard/`)."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from indicadores.config import DUCKDB_PATH, PROJECT_ROOT

SAIDA_PADRAO = PROJECT_ROOT / "dashboard" / "dados.json"

# Contrato com o dashboard: colunas explícitas (e não `select *`) para que uma coluna nova no
# mart não mude o JSON sem querer, e uma coluna removida falhe aqui, na CI, e não no navegador.
COLUNAS = (
    "mes_referencia",
    "selic_meta_aa",
    "ipca_mensal",
    "ipca_12m",
    "juro_real_ex_post_aa",
    "dolar_ptax_medio",
    "dolar_ptax_fim_mes",
)

CASAS_DECIMAIS = 4  # suficiente para % com 2 casas e PTAX com 4; corta o ruído de float das médias


def _valor_json(valor: Any) -> Any:
    """Converte um valor do DuckDB para JSON: datas em ISO, floats arredondados, NaN vira null."""
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, float):
        return None if math.isnan(valor) else round(valor, CASAS_DECIMAIS)
    return valor


def linhas_para_meses(linhas: list[tuple]) -> list[dict[str, Any]]:
    """Transforma as linhas do mart (na ordem de `COLUNAS`) em registros prontos para JSON."""
    return [
        {col: _valor_json(v) for col, v in zip(COLUNAS, linha, strict=True)} for linha in linhas
    ]


def ler_meses(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    sql = f"select {', '.join(COLUNAS)} from marts.fct_indicadores_mensais order by mes_referencia"
    return linhas_para_meses(con.execute(sql).fetchall())


def montar_payload(meses: list[dict[str, Any]], gerado_em: datetime) -> dict[str, Any]:
    return {
        "gerado_em": gerado_em.astimezone(UTC).isoformat(timespec="seconds"),
        "fonte": "BCB SGS",
        "meses": meses,
    }


def exportar(saida: Path | str = SAIDA_PADRAO, db_path: Path | str = DUCKDB_PATH) -> int:
    """Lê o mart de `db_path` (somente leitura) e grava o JSON em `saida`. Retorna nº de meses."""
    saida, db_path = Path(saida), Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"warehouse não encontrado: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        meses = ler_meses(con)
    finally:
        con.close()
    payload = montar_payload(meses, datetime.now(UTC))
    saida.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    saida.write_text(texto, encoding="utf-8")
    return len(meses)
