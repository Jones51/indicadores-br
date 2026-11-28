# ADR 0007 — Metas de inflação como seed do dbt e status vs. banda no mart

- **Status:** aceito
- **Data:** 2026-11-28

## Contexto

O dashboard passa a mostrar o IPCA 12m contra a meta de inflação (card, faixa no gráfico e
alertas). A meta não vem de nenhuma API que já consumimos: é fixada pelo Conselho Monetário
Nacional (CMN), muda raramente (no máximo uma vez por ano, com anos de antecedência) e tem uma
fonte oficial única, o histórico do BCB.

Fonte conferida em 28/11/2026: <https://www.bcb.gov.br/controleinflacao/historicometas> (a página
é montada por JavaScript; o conteúdo vem de
`https://www.bcb.gov.br/api/paginasite/sitebcb/controleinflacao/historicometas`).

| Anos | Meta | Tolerância | Normas (Resolução CMN) |
| --- | --- | --- | --- |
| 2010–2016 | 4,50% | ± 2,0 p.p. | 3.584, 3.748, 3.880, 3.991, 4.095, 4.237, 4.345 |
| 2017–2018 | 4,50% | ± 1,5 p.p. | 4.419, 4.499 |
| 2019 | 4,25% | ± 1,5 p.p. | 4.582 |
| 2020 | 4,00% | ± 1,5 p.p. | 4.582 |
| 2021 | 3,75% | ± 1,5 p.p. | 4.671 |
| 2022 | 3,50% | ± 1,5 p.p. | 4.724 |
| 2023 | 3,25% | ± 1,5 p.p. | 4.831 |
| 2024 | 3,00% | ± 1,5 p.p. | 4.918 |
| 2025 em diante | 3,00% | ± 1,5 p.p. | 5.141 (meta contínua; revogou as 5.018 e 5.091) |

Duas mudanças de regime importam para a modelagem:

- **Até 2024** a meta valia para o IPCA do **ano-calendário** (verificado em dezembro).
- **Desde 2025** vale a **meta contínua** (Decreto nº 12.079/2024): o alvo é o IPCA acumulado em
  12 meses, verificado **todo mês**, e só é descumprido após **6 meses consecutivos** fora da
  banda. Não tem data de término; uma mudança exige aviso de 36 meses.

## Decisão

1. **Seed `transform/seeds/metas_inflacao.csv`** (`ano, meta, tolerancia, norma`), no schema
   `seeds`, com `column_types` explícitos (`decimal(5,2)` para meta e tolerância, para que
   `meta ± tolerancia` seja exato) e testes: `unique`/`not_null` em `ano`, `not_null` nas
   demais, e o teste singular `assert_metas_inflacao_validas` (faixa plausível, piso positivo e
   anos contíguos). O `dbt build` da CI já carrega seeds antes dos modelos: o workflow não muda.
   - Alternativas descartadas: buscar a meta de uma API (não há série SGS oficial com a banda,
     e seria uma dependência a mais para um dado que muda a cada vários anos); colocar os
     valores no HTML (a regra sairia do dbt, sem teste, e o JSON deixaria de ser a fonte da
     verdade — contra o ADR 0005).
2. **Anos sem linha explícita:** a linha de 2025 representa a meta contínua e **vale para todos
   os anos seguintes**. O mart pega a meta da linha mais recente com `ano <= ano do mês`
   (`arg_max(meta, ano)` sobre o join `metas.ano <= year(mes)`). Assim o seed não precisa de uma
   linha nova a cada virada de ano (o que quebraria o dashboard em 1º de janeiro se alguém
   esquecesse), e uma meta nova do CMN entra como uma linha com o ano de início. O teste de
   contiguidade impede que um buraco no meio repita a meta do ano anterior em silêncio.
3. **No `fct_indicadores_mensais`:** `meta_inflacao`, `meta_inflacao_inferior`,
   `meta_inflacao_superior` (convertidas para `double`, como as outras colunas do JSON),
   `status_meta_inflacao` (`acima`/`dentro`/`abaixo`, limites inclusivos, IPCA arredondado a 2
   casas antes da comparação; nulo sem IPCA) e `meses_seguidos_status_meta` (tamanho da
   sequência atual com o mesmo status, por ilhas com `row_number`). A regra fica no mart, e não
   na página, porque é regra de negócio: testável (`accepted_values`), documentada no catálogo
   do dbt e igual para qualquer consumidor do warehouse.
4. **Leitura antes de 2025:** o status mês a mês aplica a banda do ano a um IPCA 12m que,
   formalmente, só era cobrado em dezembro. Na página e nas descrições ele é tratado como
   referência analítica; o descumprimento formal só é afirmado na meta contínua (alerta de
   6+ meses seguidos fora da banda a partir de 2025).

## Consequências

- Nova meta do CMN = editar o CSV e abrir PR; o `dbt build` recarrega o seed. Não há como a CI
  descobrir sozinha uma mudança de meta: o risco é baixo (aviso mínimo de 36 meses).
- A meta tem `not_null` no mart. Se a ingestão um dia começar antes de 2010 (`--inicio`), o teste
  falha e o seed precisa de linhas para os anos anteriores — falha alta em vez de banda vazia.
- O JSON do dashboard ganha cinco colunas (`exportar.COLUNAS`); o schema `seeds` aparece no
  `prod.duckdb`, sem efeito em `indicadores validar`, que só olha o schema `raw`.
