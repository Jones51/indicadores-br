# indicadores-br

Pipeline de indicadores econômicos do Brasil: **BCB (SGS)** e, em breve, **IBGE (SIDRA)**,
carregados em **DuckDB** e transformados com **dbt**.

```
API BCB ──► src/indicadores (Python) ──► raw.bcb_sgs ──► dbt staging ──► dbt marts
                                          (DuckDB)                     fct_indicadores_mensais
```

## Como rodar

```powershell
uv sync                                   # cria .venv e instala dependências
uvx dbc sync --level user                 # driver DuckDB 2.x usado pelo dbt v2 (uma vez por máquina)
uv run indicadores ingest                 # extrai do BCB e carrega em raw
cd transform
uv run dbt build --profiles-dir .         # roda modelos + testes
```

Documentação dbt (Docs v2, com linhagem por coluna):

```powershell
cd transform
uv run dbt compile --profiles-dir . --static-analysis strict --generate-info-schema
uv run dbt docs generate --profiles-dir . --no-compile
uv run dbt docs serve --profiles-dir . --port 8080
```

Consultar o resultado:

```powershell
uv run python -c "import duckdb; print(duckdb.connect('data/warehouse.duckdb').sql('select * from marts.fct_indicadores_mensais order by 1 desc limit 12'))"
```

## Séries

| Nome | Código SGS | Unidade | Periodicidade |
|---|---|---|---|
| selic_meta | 432 | % a.a. | diária |
| ipca_mensal | 433 | % a.m. | mensal |
| ipca_12m | 13522 | % 12 meses | mensal |
| dolar_ptax_venda | 1 | R$/US$ | diária |

## Roadmap

- [x] Esqueleto: ingestão BCB, staging, mart mensal, testes
- [ ] Extrator IBGE (desemprego PNAD, PIB)
- [ ] Ingestão incremental (só baixa o que falta)
- [ ] Análise: correlação Selic × IPCA com defasagem
- [ ] Dashboard HTML interativo
- [ ] CI (GitHub Actions) + agendamento semanal
