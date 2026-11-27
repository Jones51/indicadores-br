# ADR 0002 — Migração para dbt v2 com driver DuckDB via dbc

- **Status:** aceito
- **Data:** 2026-11-27
- **Substitui parcialmente:** ADR 0001 (item "Transformação")

## Contexto

O projeto usava dbt Core 1.12 + `dbt-duckdb` 1.11. A dbt v2 é a versão padrão para
novas instalações e traz o dbt Docs v2 (catálogo com linhagem por coluna), validação
mais rígida de YAML/configs e análise estática do SQL.

A v2 não usa adapters Python: conecta via drivers ADBC. O driver DuckDB embutido é da
linha 1.x e não lê o arquivo `data/warehouse.duckdb`, gravado pelo DuckDB 2.0 do loader
Python (`version number 999, but we can only read versions between 64 and 68`).
A v2 procura primeiro um driver instalado no sistema e só depois usa o embutido.

## Decisão

- Trocar `dbt-core`/`dbt-duckdb` pelo pacote `dbt` (v2) no `pyproject.toml`, mantendo o
  versionamento no `uv.lock`.
- Instalar o driver ADBC do DuckDB 2.x com `dbc`, declarado em `dbc.toml`/`dbc.lock`
  (versionados) e instalado com `uvx dbc sync --level user`.
- Fixar `duckdb>=2.0.1,<3` no Python e `duckdb>=2.0.1 <3` no `dbc.toml`: loader, CLI/UI
  e dbt precisam ler o mesmo formato de arquivo.
- `+static_analysis: strict` em todos os modelos.

Alternativa descartada: gravar o warehouse em formato antigo (`STORAGE_VERSION`) para o
driver embutido. Prenderia o projeto a um formato legado e a cada atualização do DuckDB
seria preciso revalidar a compatibilidade.

## Consequências

- Setup tem um passo extra (`uvx dbc sync --level user`); sem ele o dbt cai no driver
  embutido e falha ao abrir o warehouse.
- Ao atualizar `duckdb` no Python, atualizar o driver no `dbc.toml` junto (e vice-versa).
- Linhagem por coluna exige compilar com `--static-analysis strict --generate-info-schema`
  antes de `dbt docs generate --no-compile` (o `docs generate` não aceita a flag).
- A v2 trata configs desconhecidas como erro: `loaded_at_field`/`freshness` da source
  foram movidos para dentro de `config:`.
