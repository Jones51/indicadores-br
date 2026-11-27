# ADR 0005 — Dashboard estático no GitHub Pages, alimentado por JSON exportado na CI

- **Status:** aceito
- **Data:** 2026-11-27

## Contexto

Queremos um dashboard público (KPIs e gráficos de Selic, IPCA, juro real e dólar) sem servidor,
hospedado junto com o dbt Docs no GitHub Pages (ADR 0003), em
`https://jones51.github.io/indicadores-br/dashboard/`. Os dados já ficam publicados de duas
formas: o `prod.duckdb` na release `warehouse` e o mart dentro do próprio build da CI.

A alternativa mais "elegante" seria a página abrir o `prod.duckdb` da release direto no navegador
com DuckDB-WASM, sem nenhuma etapa extra. Testamos se isso é viável.

### O que verificamos nos downloads de release (27/11/2026)

`curl -I` / `curl -X OPTIONS` com `Origin: https://jones51.github.io` em
`https://github.com/Jones51/indicadores-br/releases/download/warehouse/prod.duckdb`:

| Requisição | Resposta | `Access-Control-Allow-Origin` |
| --- | --- | --- |
| `HEAD` / `GET` em `github.com/.../releases/download/...` | `302 Found` → `release-assets.githubusercontent.com/...?<assinatura temporária>` | ausente |
| Preflight `OPTIONS` (pedindo o header `Range`) em `github.com` | `404 Not Found` | ausente |
| `GET` com `Range: bytes=0-15` no destino do redirect | `206 Partial Content` (aceita Range; arquivo de ~780 KB) | ausente |
| Preflight `OPTIONS` no destino do redirect | `405 Method Not Allowed` | ausente |

Ou seja: o navegador bloqueia já no primeiro salto. O `302` de `github.com` não tem
`Access-Control-Allow-Origin`, então um `fetch()` vindo de `jones51.github.io` falha mesmo
sendo um GET simples. O DuckDB-WASM lê arquivos remotos com `Range`, o que exige preflight, e o
preflight falha nos dois hosts. Além disso, a URL final é assinada e expira, então não dá para
fixá-la na página. Funcionaria só passando por um proxy CORS de terceiros, o que adiciona uma
dependência externa e um ponto de falha a um projeto que hoje não tem nenhum.

## Decisão

1. **A CI exporta um JSON** com o mart mensal (`uv run indicadores exportar --saida
   site/dashboard/dados.json`) logo depois do `dbt docs generate`. O JSON e a página são
   publicados no **mesmo artefato do Pages**, ou seja, na mesma origem. Não há CORS envolvido.
2. **A página é um HTML estático autocontido** (`dashboard/index.html`, copiado para
   `site/dashboard/`) que faz `fetch('dados.json')`.
3. **Gráficos com D3 v7** (`7.9.0`, do cdnjs, com versão exata e hash SRI):
   - dá controle fino de tudo o que a identidade visual pede (degradês, brilho, eixos discretos,
     guia de hover e dicas próprias) sem lutar contra os padrões de uma biblioteca de gráficos;
   - é uma única dependência de ~280 KB, sem build, coerente com o painel de referência do
     mesmo dono (`claude-data-dashboard`), que também usa D3;
   - `d3.formatLocale` resolve a formatação pt-BR (vírgula decimal, `R$`, sinal de menos real).
   - Alternativas descartadas: Chart.js/ECharts (mais prontos, mas mais pesados e menos
     flexíveis no visual) e Observable Plot (ótimo, mas depende do D3 de qualquer jeito e
     esconde o controle da camada de hover).
4. **O passo roda em PRs também**: exportar e montar `site/dashboard/` valida o contrato do
   JSON a cada PR; só a publicação (upload do artefato + deploy) continua restrita à `main`.

### Estrutura do JSON

```json
{
  "gerado_em": "2026-11-27T17:28:29+00:00",
  "fonte": "BCB SGS",
  "meses": [
    {
      "mes_referencia": "2010-01-01",
      "selic_meta_aa": 8.75,
      "ipca_mensal": 0.75,
      "ipca_12m": 4.59,
      "juro_real_ex_post_aa": 3.9774,
      "dolar_ptax_medio": 1.7798,
      "dolar_ptax_fim_mes": 1.8748
    }
  ]
}
```

- Uma linha por mês, em ordem cronológica, com **as mesmas colunas e unidades do mart**
  (percentuais em escala 0–100). O dashboard não recalcula nenhuma regra de negócio, só formata.
  A fonte da verdade continua sendo o dbt.
- Colunas **explícitas** em `indicadores.exportar.COLUNAS` (e não `select *`). Assim uma coluna
  nova no mart não muda o JSON sem querer, e uma coluna removida quebra a exportação na CI, não
  o navegador.
- Valores **nulos viram `null`** (e não são removidos). O mês corrente pode chegar com IPCA e
  juro real nulos, porque o IPCA sai no mês seguinte. A página usa o último valor não nulo de
  cada série nos KPIs e abre lacunas nas linhas (`line.defined`).
- Floats arredondados a 4 casas e JSON sem espaços. Hoje são ~35 KB para 202 meses.
- `gerado_em` em UTC (ISO 8601). A página exibe no horário de Brasília.

## Consequências

- O dashboard tem a mesma defasagem dos dados publicados (rebuild semanal + push na `main`).
- Uma etapa a mais na CI e um contrato a manter (`COLUNAS`). Coluna nova no dashboard =
  adicionar em `COLUNAS` e no HTML.
- Aberto direto do disco (`file://`), o `fetch` é bloqueado pelo navegador. Para ver localmente é
  preciso um servidor estático (`uv run python -m http.server -d dashboard`). A página mostra
  essa instrução se não conseguir ler o JSON.
- A página depende do cdnjs para carregar o D3. Se o CDN falhar, ela mostra um aviso em vez de
  quebrar em silêncio.
- Se no futuro quisermos consultas ad hoc no navegador (DuckDB-WASM), o caminho é publicar o
  `.duckdb` (ou Parquet) **dentro do artefato do Pages**, na mesma origem, e não ler da release.
