# CLAUDE.md — indicadores-br

Contexto para o agente. Lido automaticamente em toda sessão neste diretório.

## O projeto

Pipeline de indicadores econômicos do Brasil (BCB SGS; IBGE SIDRA planejado).
Projeto de aprendizado de desenvolvimento agêntico. O dono é engenheiro/analista de dados:
explique decisões de engenharia de software quando relevantes, mas não conceitos básicos de dados.

## Stack

- Python 3.12 gerenciado por **uv** (nunca usar `pip install` direto)
- **DuckDB** em `data/warehouse.duckdb` (gitignored)
- **dbt v2** (pacote `dbt`) em `transform/`, com `profiles.yml` local (não usar `~/.dbt`)
- Driver ADBC do DuckDB 2.x instalado via **dbc** (`dbc.toml`); o driver embutido da v2 não lê o warehouse (ADR 0002)
- Ambiente: Windows + PowerShell

## Comandos

```powershell
uv sync                                        # instalar dependências
uvx dbc sync --level user                      # instalar driver DuckDB do dbt (uma vez por máquina)
uv run pytest                                  # testes Python
uv run ruff check . ; uv run ruff format .     # lint e formatação
uv run indicadores ingest                      # ingestão (todas as séries, desde 2010)
uv run indicadores ingest --series selic_meta  # uma série
cd transform; uv run dbt build --profiles-dir .   # modelos + testes dbt
uv run dbt compile --profiles-dir . --static-analysis strict --generate-info-schema
uv run dbt docs generate --profiles-dir . --no-compile ; uv run dbt docs serve --profiles-dir . --port 8080
```

## Estrutura

- `src/indicadores/config.py` — caminhos e **catálogo de séries** (`SERIES_BCB`). Nova série = nova entrada aqui.
- `src/indicadores/extract/` — um módulo por fonte; funções puras de parsing separadas do I/O HTTP.
- `src/indicadores/load.py` — carga na camada `raw` (full refresh idempotente por série).
- `transform/models/staging/` — `stg_<fonte>__<entidade>`, views, só tipagem/renomeação.
- `transform/models/marts/` — `fct_`/`dim_`, tabelas, regras de negócio.
- `docs/adr/` — decisões de arquitetura numeradas (`NNNN-titulo.md`).
- `ci/profiles.yml` — target `prod` usado pela CI (`data/prod.duckdb`).
- `.github/workflows/dbt_build.yml` — CI: valida PRs; na `main` publica `prod.duckdb` na release
  `warehouse` e o dbt Docs no GitHub Pages (ADR 0003).

## Convenções

- Nomes de domínio em **português** (colunas, modelos, funções); termos técnicos podem ficar em inglês.
- SQL: minúsculas, CTEs nomeadas, uma CTE por fonte/etapa, `select *` só na CTE de fonte.
- Toda coluna nova de mart ganha `description` no YAML; chaves ganham `unique` + `not_null`.
- Funções de parsing têm teste unitário em `tests/` (sem rede — mockar HTTP).
- Unidades: percentuais ficam em escala 0–100 (ex.: `11.75` = 11,75%), como a fonte entrega.

## Particularidades das fontes

- API SGS exige `dataInicial`/`dataFinal` e limita séries diárias a **10 anos por consulta** (ver `janelas()`).
- SGS retorna datas `dd/mm/aaaa` e valores como string; 404 = janela sem dados.
- DuckDB aceita um só escritor: não rodar ingestão e dbt em paralelo.
- Versão do `duckdb` (Python) e do driver em `dbc.toml` andam juntas: mesma linha major.

## Fluxo de trabalho

- Commits pequenos, mensagens em português no imperativo (`adiciona extrator IBGE`).
- Antes de commitar: `uv run pytest`, `uv run ruff check .` e `dbt build` passando.
- Decisões de arquitetura relevantes viram ADR em `docs/adr/`.
