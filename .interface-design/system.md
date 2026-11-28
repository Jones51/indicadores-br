# Sistema de interface — dashboard `indicadores-br`

Decisões já tomadas para `dashboard/index.html`. Próximos agentes: aplique, não reinvente.
Contexto e justificativas: ADR 0005 (página estática) e ADR 0008 (direção "Copom Brief" no tema
"Trading Desk").

## Direção

- **Quem usa:** alguém que acompanha política monetária (analista, jornalista, estudante) e abre a
  página para saber **o que o Copom fez e onde está a inflação em relação à meta**.
- **Sensação:** um relatório de política monetária lido numa mesa de juros: calmo, denso e sério.
  Nada decorativo; a cor só aparece quando comunica série ou status.
- **Foco único:** a manchete gerada por regras, com a régua da meta logo abaixo, no painel `.lead`.
  Todo o resto é subordinado.
- **Ordem da página:** cabeçalho (título + última carga) → painel da manchete (manchete, subtítulo,
  régua, ledger, fita do Copom) → Key Alerts → filtro de período → gráficos (Selic × IPCA, IPCA
  mensal, USD/BRL) → tabela → metodologia → rodapé.
- **Filtro de período:** uma linha logo acima dos gráficos, que são o que ele afeta. Manchete,
  régua, ledger, fita e alertas mostram sempre o dado mais recente.

## Tokens (nomes do domínio)

| Token | Valor | Uso |
| --- | --- | --- |
| `--desk` | `#0e131a` | página |
| `--panel` | `#141a22` | painéis; superfície dos gráficos (validador) |
| `--panel-raised` | `#19202a` | tooltip, fichas da fita, botão ativo, cabeçalho da tabela |
| `--ink` / `--ink-2` / `--ink-3` | `#e7ecf2` / `#a8b3c1` / `#7d8a9b` | texto primário / secundário / mudo (14,7 · 8,2 · 5,0 : 1 no painel) |
| `--rule` / `--rule-2` | `rgba(255,255,255,.07)` / `.12` | ring de 1px dos painéis / divisórias de ênfase |
| `--focus` | `#8fc9ea` | anel de foco (2px, offset 2px) |
| `--selic` / `--ipca` / `--real` | `#3a9fd0` / `#c27f1c` / `#d0507a` | séries; o juro real é sempre tracejado |
| `--band` | `rgba(194,127,28,.18)` | banda de tolerância (o IPCA apagado) |
| `--target` | `rgba(231,236,242,.5)` | linha da meta (1px) |
| `--grid` / `--baseline` | `rgba(255,255,255,.06)` / `.2` | grade e linha do zero |
| `--good` / `--warning` / `--critical` | `#5fd0b5` / `#e6cf5c` / `#ff9b8f` | status, sempre com glifo (✓ / ! / !!) + rótulo |

- **Validação das cores** (`dataviz/scripts/validate_palette.js --mode dark --surface #141a22`):
  - séries `--pairs all`: tudo PASS (pior par real × IPCA, ΔE 11,3 deutan / 17,2 normal);
  - séries + status `--pairs all`: separação PASS contra as séries; good × critical em WARN (ΔE
    6,6 deutan), legal porque o status nunca depende só da cor;
  - o FAIL de "lightness band" nos status é intencional: eles ficam mais claros que as séries para
    não se confundirem com elas.
- **Regras de cor:** uma cor nova passa pelo validador antes de entrar. O texto nunca usa a cor da
  série; a exceção é a ênfase da manchete, que usa a cor de **status** e sempre vem acompanhada das
  palavras que dizem o status.

## Tipografia (escala 1.25 a partir de 14px)

`11 meta · 12 small · 14 body · 18 h4 · 22 h3 · 28 h2 · 35 display`

| Fonte | Onde |
| --- | --- |
| **Newsreader** 500/600 | só a manchete (35px, 26px no celular, tracking −0,015em) e os títulos de seção (22px, 18px no celular; também nos `summary` e em "Key Alerts") |
| **IBM Plex Sans** 400/500/600 | interface e números. Hierarquia por peso + cor: valor 600/`--ink`, rótulo 500/`--ink-2`, metadado 400/`--ink-3` |
| **IBM Plex Mono** 400/500 | só rótulos e metadados pequenos: cabeçalho "Last load", edição, "Chart period", nível do alerta, fita do Copom, cabeçalhos da tabela. 11px, caixa alta, tracking .06em |

- **Algarismos:** proporcionais nos números grandes (ledger, manchete); `tabular-nums` em tabela,
  eixos, tooltip, fita e metadados.
- **Title Case:** em títulos e cabeçalhos (manchete, seções, `summary`). Rótulos curtos e texto
  corrido ficam em sentence case.

## Densidade e espaçamento

- Base de **4px**.
- Painéis: 20px de padding (16px abaixo de 760px); o painel da manchete tem 24px.
- Espaço entre painéis: 16px.
- Dentro do painel da manchete, blocos separados por 20px, com divisória de 1px (`--rule-2` acima
  do ledger, `--rule` acima da fita).
- Raios: 8px nos painéis, 6px no grupo de período e no tooltip, 4px nas fichas e botões internos.

## Profundidade

**Só bordas.** Ring de 1px (`box-shadow: 0 0 0 1px var(--rule)`) e três níveis de superfície no
mesmo tom (`--desk` → `--panel` → `--panel-raised`). Sem sombra de profundidade, vidro, blur ou
degradê.

## Componentes

- **Manchete** (`.manchete`, h2)
  - Uma oração sobre o Copom + uma sobre a inflação. As regras estão no ADR 0008 e em "How Each
    Number Is Calculated".
  - A ênfase (`<em>`, cor de status) fica só no trecho de posição ("0.13 pp Above the Ceiling").
  - Largura máxima de 34ch, `text-wrap: balance`.
  - O subtítulo (`.dek`, 14px `--ink-2`) diz o mês de referência e se o IPCA do mês mais recente
    ainda não saiu.
- **Régua da meta** (`#regua`, SVG de 88px de altura)
  - Trilha de 4px (`--rule-2`), banda de 18px (`--band`).
  - Traços de piso e teto: 1px `--ink-3`, ±9px. Traço da meta: 1,5px `--ink-2`, ±12px.
  - Pontos: 12 meses antes, vazado (r 5, contorno `--ink-3` 1,5px); atual, cheio (r 7, `--ipca`,
    anel de 2px `--panel`).
  - Rótulo do valor atual (14px/600) acima do ponto, preso às bordas.
  - Rótulos de piso, meta e teto em duas linhas (valor 12px `--ink-2` + nome em Mono 11px),
    32–48px abaixo da trilha, mais os extremos da escala.
  - Colisão: a meta tem prioridade, depois piso e teto, depois os extremos. Um rótulo que encosta
    em outro é removido.
  - Legenda (`figcaption`) com os dois pontos e a banda.
- **Ledger** (`.ledger`)
  - 4 colunas (2×2 abaixo de 760px), separadas por 1px `--rule`, com `--rule-2` no topo.
  - Por célula: rótulo 12px/500/`--ink-2` → valor 28px/600 (22px no celular) com unidade 12px
    `--ink-3` → status do IPCA (glifo de 16px + 12px/500) → metadado 12px `--ink-3` ("Oct 2026 ·
    −0.05 pp in 12 months") → sparkline de 28px.
  - **Sparklines ficam:** sem eixos, linha `--spark` de 1,5px, último ponto na cor da série; no IPCA
    a banda aparece atrás. Dão a tendência de 24 meses com pouca tinta e sem caixas.
  - Variações sem cor: se um movimento é bom ou ruim depende do leitor.
- **Fita do Copom** (`.fita`)
  - Rótulo "COPOM" (Mono, `--ink-3`), depois as 6 últimas mudanças como fichas: `--panel-raised`,
    ring `--rule`, 2px 8px, raio 4px, Mono 11px.
  - O mês vem em `--ink-2` e os bp em 500/`--ink`. O ano só aparece na primeira ficha e quando muda.
  - Fecha com "→ 13.75%" sem ficha, seguido da nota de 11px sobre a data de vigência.
- **Alerta** (`.alertas li`): glifo de status de 16px, nível em Mono 11px, texto 14px `--ink`,
  data 12px `--ink-3`. Sem alerta, glifo neutro e "No alerts — …".
- **Filtro de período**
  - Grupo segmentado `--panel` com ring.
  - Botão de 36px de altura, 13px. Ativo: `--panel-raised` + ring `--rule-2` + `--ink`.
  - Hover muda só a cor; `:active` faz `scale(.97)`.
- **Gráficos**
  - Linhas de 2px, Selic em degraus, juro real tracejado 6/4.
  - Banda e meta atrás das linhas; grade hairline sólida; rótulos diretos no fim das linhas
    (12px/500).
  - Tooltip `--panel-raised` com ring `--rule-2`: o valor vem em 600/`--ink`, o nome em `--ink-3`,
    e a chave é um traço curto da cor da série.
  - Barras: no máximo 24px, gap de 2px, ponta de 4px arredondada. A coluna do mês inteira é o
    alvo de hover; a barra ativa clareia.
