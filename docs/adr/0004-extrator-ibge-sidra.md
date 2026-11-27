# ADR 0004 — Extrator IBGE (SIDRA): tabelas, datas de referência e tabela raw

- **Status:** aceito
- **Data:** 2026-11-27

## Contexto

O IBGE é a segunda fonte do pipeline (desemprego e PIB). A API SIDRA
(`https://apisidra.ibge.gov.br/values/...`) difere do SGS do BCB em pontos que afetam o desenho:

- a consulta é por **tabela + variável + classificações**, não por um código único de série;
- a resposta é uma lista JSON cujo **primeiro elemento é o cabeçalho** (rótulos das colunas
  `D1C`, `D2C`, ...); a ordem das dimensões `D1..Dn` depende da tabela e das classificações
  pedidas (no PIB há uma `D4` de "Setores e subsetores" que a desocupação não tem);
- valores são strings e podem ser símbolos: `-` (zero absoluto), `..` (não se aplica),
  `...` (não disponível), `X` (omitido por sigilo);
- períodos são códigos de 6 dígitos com significados diferentes: `AAAATT` no trimestre civil e
  `AAAAMM` no trimestre móvel da PNAD (`202610` = ago-set-out 2026);
- erros de parâmetro voltam como **HTTP 400 com texto puro**;
- o volume é pequeno (dezenas a poucas centenas de linhas por série) e não há limite de janela.

## Decisão

### Séries (catálogo `SERIES_IBGE` em `config.py`, sempre nível Brasil `n1`)

| Nome | Tabela | Variável | Por quê |
| --- | --- | --- | --- |
| `desocupacao` | 4099 | 4099 — taxa de desocupação (%) | trimestre civil, a série "oficial" trimestral da PNAD Contínua |
| `desocupacao_movel` | 6381 | 4099 — taxa de desocupação (%) | trimestre móvel, divulgado todo mês: é o que permite juntar ao mart mensal |
| `pib_indice_sa` | 1621 | 584 — índice encadeado de volume com ajuste sazonal (1995=100), categoria 90707 (PIB a preços de mercado) | nível dessazonalizado: dele se derivam variação contra o trimestre anterior, acumulados e comparações em qualquer janela |
| `pib_var_interanual` | 5932 | 6561 — taxa trimestral contra o mesmo trimestre do ano anterior (%), categoria 90707 | a manchete de crescimento; não depende de ajuste sazonal e não é revisada pelo reajuste do modelo sazonal |

Não foram escolhidos: o PIB em valores correntes (tabela 1846), que mistura volume e preço; e a
variação t/t-1 dessazonalizada (5932/6564), derivável do índice 1621. Os percentuais ficam na
escala 0–100, como a fonte entrega.

### Período → data de referência

`data` = **primeiro dia do último mês do período**:

- trimestral `202601` (1º tri 2026) → `2026-03-01`;
- trimestre móvel `202610` (ago-set-out 2026) → `2026-10-01`.

Motivos: (1) o trimestre móvel já é identificado pelo seu último mês, e o trimestre civil é o
trimestre móvel encerrado em mar/jun/set/dez — com essa regra, as duas séries de desocupação têm
o **mesmo valor na mesma data** (verificado: 59 de 59 trimestres); (2) a informação só existe ao
fim do período, então datar pelo início anteciparia o dado em dois meses numa junção com séries
mensais; (3) é uma data de mês (`dd = 01`), compatível com o `mes_referencia` do mart mensal.

O código e o rótulo originais (`periodo_codigo`, `periodo_nome`) são preservados, então outra
convenção (ex.: início do trimestre) pode ser derivada no dbt sem reingerir.

### Parsing e extração (`extract/ibge.py`)

- Funções puras: `parse_resposta` (descarta o cabeçalho e localiza a coluna de período **pelo
  rótulo** — `Trimestre (Código)`, `Trimestre Móvel (Código)`, `Mês (Código)`), `parse_valor`
  e `periodo_para_data`. O rótulo também determina a periodicidade, que é conferida contra o
  catálogo (falha se a tabela mudar de formato).
- `-` vira `0.0` (é zero absoluto pela convenção do IBGE); `..`, `...`, `X` e vazio são
  descartados, como os vazios do SGS.
- Uma consulta por série com `p/all` e `d/m` (máximo de casas decimais); o corte por
  `--inicio` é feito em Python. HTTP 400 vira `ValueError` com a mensagem do SIDRA.

### Tabela raw `raw.ibge_sidra`

Formato longo, uma linha por (série, período):

| Coluna | Tipo | Observação |
| --- | --- | --- |
| `serie_nome` | varchar | chave da série (nome do catálogo) |
| `tabela`, `variavel` | integer | rastreabilidade da origem |
| `periodo_codigo`, `periodo_nome` | varchar | como o SIDRA entrega |
| `data` | date | regra acima |
| `valor` | double | unidade da fonte |
| `unidade` | varchar | `MN` da resposta (ex.: `%`, `Número-índice`) |
| `extraido_em` | timestamp | default `current_timestamp` |

Tabela separada de `raw.bcb_sgs` (e não uma raw genérica) porque os metadados de origem diferem
e cada fonte mantém sua source/staging própria (`stg_ibge__sidra`). A chave da carga é
`serie_nome`, e não um código numérico, porque uma série SIDRA é a combinação
tabela + variável + classificação. Carga full idempotente por série (delete + insert numa
transação), no mesmo padrão do BCB.

## Consequências

- `indicadores ingest` passa a depender também da API do IBGE responder a partir dos runners do
  GitHub; `--fonte bcb|ibge` permite isolar uma fonte localmente.
- Renomear uma série no catálogo deixa as linhas antigas órfãs na raw (a carga apaga pelo nome
  novo); é preciso apagá-las à mão. Mesmo comportamento do BCB com troca de código.
- As séries do IBGE ainda **não** entram no `fct_indicadores_mensais`; a junção (provavelmente
  via `desocupacao_movel` e PIB trimestral repetido ou só nos meses de fechamento) fica para uma
  segunda etapa, com seu próprio ADR se mudar o grão do mart.
- O PIB é revisado a cada divulgação; a carga full por série garante que a raw reflita a última
  revisão.
