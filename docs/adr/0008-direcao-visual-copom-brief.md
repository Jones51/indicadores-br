# ADR 0008 — Direção visual "Copom Brief" no tema "Trading Desk", manchete por regras e decisões do Copom

- **Status:** aceito
- **Data:** 2026-11-28

## Contexto

A primeira versão do dashboard (ADR 0005, PR #10) tinha quatro cards iguais, dois gráficos e
vidro/degradê. Faltava um foco: quem abre a página quer saber **o que o Copom fez e onde está a
inflação em relação à meta**, e essa resposta estava espalhada em quatro números do mesmo peso.
O dono comparou duas direções e escolheu a **estrutura da Direção A ("Copom Brief": manchete,
régua da meta, linha de indicadores e fita do Copom)** com o **tema escuro da Direção B ("Trading
Desk": grafite, denso, bordas de 1px)**.

## Decisão

### 1. Estrutura e foco

- **Foco único:** uma manchete gerada por regras a partir dos dados, num painel de destaque,
  com a **régua da meta** (IPCA 12m como ponto sobre a banda do CMN, o valor de 12 meses antes
  como ponto vazado), a **linha de indicadores** (Selic, IPCA 12m, juro real, USD/BRL) e a
  **fita do Copom** (últimas mudanças da meta em bp) logo abaixo.
- Alertas, gráficos (Selic × IPCA com banda, IPCA mensal, USD/BRL), tabela e metodologia
  continuam, com o filtro de período numa linha logo acima dos gráficos, que são o que ele afeta.
- Tokens, escala tipográfica, densidade e padrões de componente ficam em
  `.interface-design/system.md`.

### 2. Tema e cores

- Superfícies grafite num tom só, variando só a luminosidade (`--desk`, `--panel`,
  `--panel-raised`). A profundidade vem só de bordas de 1px (sem sombra de profundidade, vidro,
  blur ou degradê).
- Séries validadas com `validate_palette.js --pairs all --mode dark --surface #141a22`
  (todas PASS): Selic `#3a9fd0`, IPCA `#c27f1c`, juro real `#d0507a` (tracejado). A banda da meta
  é o IPCA com 18% de opacidade.
- Status: good `#5fd0b5`, warning `#e6cf5c`, critical `#ff9b8f`. São mais claros que a faixa de
  luminosidade das séries, de propósito, para não se confundirem com elas. Contra as séries,
  todos os pares passam; entre si, good × critical fica em ΔE 6,6 (deutan, faixa WARN), o que é
  legal porque o status sempre vem com glifo e rótulo próprios (✓ / ! / !!). O âmbar de
  *warning* foi trocado por um amarelo para não ficar vizinho do laranja do IPCA.
- O texto mudo passou de `#6f7b8a` (4,06:1 no painel) para `#7d8a9b` (4,98:1), para cumprir o
  WCAG AA em texto pequeno.

### 3. Tipografia

IBM Plex Sans (interface e números; algarismos proporcionais nos números grandes, `tabular-nums`
em tabela, eixos e tooltip), IBM Plex Mono só em rótulos e metadados pequenos (fita do Copom,
"Last load"), Newsreader só na manchete e nos títulos de seção. As fontes vêm do **Google Fonts**
(`display=swap`). É uma dependência externa nova, além do cdnjs: se falhar, a página cai para
`system-ui`/Georgia sem quebrar.

### 4. `fct_decisoes_copom`

Novo mart com uma linha por **mudança** da meta Selic, derivado da série diária SGS 432 com
`lag()`: `data_vigencia`, `selic_anterior_aa`, `selic_nova_aa`, `variacao_bp`. Testes:
`unique`/`not_null` na chave e `not_null` nas demais.

- **Ressalva:** a data é a da **vigência** na série (primeiro dia com a meta nova), em geral o dia
  útil seguinte à reunião. **Não é a data da reunião.** Manutenções não aparecem, porque a série
  não muda. Para o calendário de reuniões seria preciso outra fonte (atas do Copom), fora do
  escopo.
- A primeira observação ingerida (jan/2010) não tem anterior e não conta como decisão.
- O JSON do dashboard ganha `decisoes_copom` com as **12 últimas** (`exportar.DECISOES_PADRAO`),
  em ordem cronológica. Warehouse sem o modelo → lista vazia, e a página omite a fita.

### 5. Regras da manchete

A manchete junta uma oração sobre o Copom e outra sobre a inflação, em Title Case:

| Caso | Oração |
| --- | --- |
| Última mudança há **mais de 50 dias** da geração do JSON e sequência de *n* ≥ 2 movimentos no mesmo sentido | "Copom Holds the Selic at 13.75% After Five Straight Cuts" |
| Mais de 50 dias, sequência de 1 | "Copom Holds the Selic at 13.75% After a 25 bp Cut in Sep" |
| Até 50 dias, *n* ≥ 2 | "Copom Has Cut Five Times in a Row, to 13.75%" ("Twice" quando *n* = 2; ou "Raised") |
| Até 50 dias, *n* = 1 | "Copom Cuts the Selic by 25 bp to 13.75%" (ou "Raises") |
| IPCA 12m acima do teto | "While Inflation Sits 0.13 pp Above the Ceiling" |
| IPCA 12m abaixo do piso | "While Inflation Sits 0.30 pp Below the Floor" |
| IPCA 12m dentro da banda | "With Inflation Inside the Target Band" |

- **Por que 50 dias:** as reuniões do Copom são a cada ~45 dias. Sem mudança depois desse
  intervalo, ao menos uma reunião manteve a taxa. É uma inferência, não a data da ata.
- A distância ao teto ou ao piso usa o status do mart (`status_meta_inflacao`).
- A inflação é sempre a do **último IPCA divulgado**. Quando o mês mais recente ainda não tem
  IPCA, o subtítulo diz "Nov 2026 IPCA not released yet".
- Sem decisões no JSON, a manchete fica só com a oração da inflação. Sem os dois, vira o título
  genérico.

## Consequências

- O primeiro contato com a página é uma frase que muda sozinha a cada carga. As regras estão
  aqui e em "How Each Number Is Calculated", e a manchete nunca afirma algo que os dados não
  sustentam: "Holds" é uma inferência pelo intervalo, e a página diz isso.
- Mais um mart e mais um bloco no contrato do JSON. Uma regressão no `lag()` aparece como
  `variacao_bp` nula, o que o teste `not_null` acusa.
- A página passa a depender do Google Fonts, além do cdnjs.
