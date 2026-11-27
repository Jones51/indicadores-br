# ADR 0003 — CI pública: warehouse em release e dbt Docs no GitHub Pages

- **Status:** aceito
- **Data:** 2026-11-27

## Contexto

Queremos o mesmo padrão do projeto `dbt-duckdb-pipeline`: dados e documentação acessíveis a
qualquer pessoa, sem clonar nem rodar nada, e o pipeline rodando sem depender de máquina local.

## Decisão

- **GitHub Actions** (`.github/workflows/dbt_build.yml`) roda lint, testes, ingestão e
  `dbt build` em todo PR, push na `main`, toda segunda-feira e sob demanda.
- **Ambientes:** `dev` local (`transform/profiles.yml` → `data/warehouse.duckdb`) e `prod` na CI
  (`ci/profiles.yml` → `data/prod.duckdb`).
- **Warehouse:** `prod.duckdb` publicado como asset da release `warehouse` (sobrescrito a cada
  execução), consultável via `ATTACH` por HTTP.
- **Docs:** dbt Docs v2 publicado no GitHub Pages **por Actions** (`upload-pages-artifact` +
  `deploy-pages`), gerado numa pasta `site/` separada do `target/`.
- PRs só validam; publicação apenas na `main`.

Diferença em relação ao projeto de referência: lá o site é commitado em `docs/` e servido pelo
modo "branch". Aqui `docs/` já guarda os ADRs, e commitar artefatos gerados (~300 arquivos a
cada build) polui o histórico e gera conflitos entre branches. O deploy por Actions publica o
artefato sem passar pelo git.

## Consequências

- Os dados publicados têm no máximo ~1 semana de defasagem (agendamento semanal), compatível
  com o `freshness` de 8 dias da source.
- A ingestão na CI depende da API do BCB responder a partir dos runners do GitHub.
- O arquivo publicado usa o formato do DuckDB 2.x: quem consulta precisa de DuckDB ≥ 2.0.
- O `site/` exporta só o site (sem SQL compilado nem falhas de teste armazenadas).
