# ADR 0001 — Stack inicial: Python + DuckDB + dbt

- **Status:** aceito
- **Data:** 2026-11-27

## Contexto

Precisamos de um pipeline local, reproduzível e barato para ingerir indicadores
públicos (BCB, IBGE), transformá-los e servi-los para análise e dashboards.
O volume é pequeno (milhares a centenas de milhares de linhas).

## Decisão

- **Ingestão:** Python (`httpx`) com um módulo por fonte em `src/indicadores/extract/`.
- **Warehouse:** DuckDB em arquivo (`data/warehouse.duckdb`), schema `raw` para dados brutos.
- **Transformação:** dbt (`dbt-duckdb`), camadas `staging` (views) → `marts` (tabelas).
  *Atualizado pelo ADR 0002: dbt v2 com driver ADBC do DuckDB.*
- **Gerenciamento de ambiente:** `uv`.

## Consequências

- Zero infraestrutura: tudo roda na máquina local e em CI.
- Migração futura para um warehouse em nuvem (BigQuery/Snowflake/MotherDuck) exige
  trocar só o adapter dbt e o loader; os modelos SQL ficam quase intactos.
- DuckDB tem um único escritor por vez: não rodar ingestão e dbt simultaneamente.
