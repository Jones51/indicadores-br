# CLAUDE.md — indicadores-br

Contexto para o agente. Lido automaticamente em toda sessão neste diretório.

## O projeto

Pipeline de indicadores econômicos do Brasil (BCB SGS e IBGE SIDRA).
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
uv run indicadores ingest                      # ingestão INCREMENTAL (todas as séries; banco vazio = full)
uv run indicadores ingest --full               # recarga completa desde 2010 (--inicio muda)
uv run indicadores ingest --series selic_meta  # uma série
uv run indicadores ingest --fonte ibge         # uma fonte (bcb | ibge)
uv run indicadores validar --db <arquivo>      # estado: 0 válido, 3 abre mas inválido, 4 corrompido
uv run indicadores herdar-auditoria --origem <antigo.duckdb>   # copia raw.cargas/reconciliacoes
uv run indicadores reconciliar --base <inc.duckdb> --full <full.duckdb>   # full vence (sai 2 se estrutural)
uv run indicadores resumo                      # tabela markdown da última execução em raw.cargas
cd transform; uv run dbt build --profiles-dir .   # modelos + testes dbt
uv run dbt source freshness --profiles-dir .      # freshness das sources (portão da CI)
uv run dbt compile --profiles-dir . --static-analysis strict --generate-info-schema
uv run dbt docs generate --profiles-dir . --no-compile ; uv run dbt docs serve --profiles-dir . --port 8080
```

## Estrutura

- `src/indicadores/config.py` — caminhos e **catálogo de séries** (`SERIES_BCB`, `SERIES_IBGE`). Nova série = nova entrada aqui.
- `src/indicadores/extract/` — um módulo por fonte; funções puras de parsing separadas do I/O HTTP.
- `src/indicadores/incremental.py` — janela incremental (funções puras): margem de 90 dias nas
  diárias e 2 períodos nas mensais/trimestrais; full se não há dados, estado inválido ou `--full`.
- `src/indicadores/ingestao.py` — orquestra janela → extração → substituição + auditoria por série.
- `src/indicadores/load.py` — carga na camada `raw`, **incremental por padrão**: substitui só
  `data >= início da janela` (delete + insert numa transação, idempotente); full apaga a série
  inteira. Recusa apagar uma janela com dados quando a fonte devolve vazio. Toda carga grava uma
  linha em `raw.cargas` na mesma transação (ADR 0006).
- `src/indicadores/estado.py` / `reconciliar.py` — validação do warehouse herdado e
  reconciliação incremental × full (ADR 0006).
- `src/indicadores/exportar.py` — exporta o mart para `dados.json` do dashboard (`indicadores exportar`).
- `dashboard/` — página estática (D3) publicada em `/dashboard/` no Pages (ADR 0005).
- `transform/models/staging/` — `stg_<fonte>__<entidade>`, views, só tipagem/renomeação.
- `transform/models/marts/` — `fct_`/`dim_`, tabelas, regras de negócio.
- `docs/adr/` — decisões de arquitetura numeradas (`NNNN-titulo.md`).
- `ci/profiles.yml` — target `prod` usado pela CI (`data/prod.duckdb`).
- `.github/workflows/dbt_build.yml` — CI: valida PRs; na `main` publica `prod.duckdb` na release
  `warehouse` e o dbt Docs no GitHub Pages (ADR 0003). A CI tem estado: parte do `prod.duckdb`
  publicado (validado), reconcilia com um full às segundas e em PRs, e faz backup em
  `prod.anterior.duckdb` antes de publicar (ADR 0006).

## Convenções

- Nomes de domínio em **português** (colunas, modelos, funções); termos técnicos podem ficar em inglês.
- Idioma por artefato: **inglês** no `README.md`, nos textos do dashboard, nas notas da release e
  na descrição do repositório (padrão do portfólio, como o `dbt-duckdb-pipeline`); **português**
  nos identificadores, comentários, docstrings, YAML do dbt, ADRs, `CLAUDE.md`, commits e PRs.
- SQL: minúsculas, CTEs nomeadas, uma CTE por fonte/etapa, `select *` só na CTE de fonte.
- Toda coluna nova de mart ganha `description` no YAML; chaves ganham `unique` + `not_null`.
- Funções de parsing têm teste unitário em `tests/` (sem rede — mockar HTTP).
- Unidades: percentuais ficam em escala 0–100 (ex.: `11.75` = 11,75%), como a fonte entrega.

## Particularidades das fontes

- API SGS exige `dataInicial`/`dataFinal` e limita séries diárias a **10 anos por consulta** (ver `janelas()`).
- SGS retorna datas `dd/mm/aaaa` e valores como string; 404 = janela sem dados.
- SIDRA (`apisidra.ibge.gov.br/values/t/.../n1/all/v/.../p/all[/cX/Y]/d/m`): 1º item da lista
  JSON é o **cabeçalho**; localizar a coluna de período pelo rótulo (`Trimestre (Código)`,
  `Trimestre Móvel (Código)`), não pela posição `D3C`/`D4C`.
- SIDRA: valores string com símbolos — `-` = zero absoluto (vira 0), `..`/`...`/`X` = sem dado
  (descartar). Erro de parâmetro = HTTP 400 com texto puro.
- SIDRA: período `AAAATT` (trimestre) ou `AAAAMM` (trimestre móvel, identificado pelo último mês);
  `data` = 1º dia do último mês do período (ADR 0004). Série = tabela + variável + classificação,
  identificada por `serie_nome` em `raw.ibge_sidra`.
- As duas APIs dão 5xx/timeout esporádicos (ex.: 502 do SGS na janela de 10 anos da Selic):
  todo GET passa por `extract/http.py:get_com_retentativas` (4 tentativas, 2s/4s/8s; 4xx não repete).
- SIDRA incremental: faixa `p/AAAAPP-AAAAPP` (pode terminar num período não divulgado; faixa sem
  dados = só cabeçalho; faixa invertida = 400). O full usa `p/all`.
- Mudar o schema de uma tabela raw (DDL em `load.py`) torna o `prod.duckdb` publicado "inválido
  como base" para `indicadores validar` (saída 3, o arquivo abre): o próximo run da CI faz full,
  herda o histórico de auditoria (colunas em comum) e **faz o backup** dele em
  `prod.anterior.duckdb`. Só arquivo corrompido/ausente (saída 4) fica sem backup.
- A página de ajuda do SIDRA fica atrás de desafio JS (Cloudflare); para metadados use
  `servicodados.ibge.gov.br/api/v3/agregados/{tabela}/metadados`.
- DuckDB aceita um só escritor: não rodar ingestão e dbt em paralelo.
- Depois de um `git pull` que traga tabelas raw novas, rode `uv run indicadores ingest` antes do
  `dbt build`: é o `conectar()` que cria as tabelas (senão os testes de source falham com
  "Table ... does not exist").
- Versão do `duckdb` (Python) e do driver em `dbc.toml` andam juntas: mesma linha major.

## Fluxo de trabalho

- Commits pequenos, mensagens em português no imperativo (`adiciona extrator IBGE`).
- Antes de commitar: `uv run pytest`, `uv run ruff check .` e `dbt build` passando.
- Decisões de arquitetura relevantes viram ADR em `docs/adr/`.
- Nada vai direto para a `main`: branch → PR → CI verde → revisão do dono → merge.
- Leitura de `timestamptz` no Python depende do pacote `tzdata` (já é dependência; no Windows
  não há base de fusos do sistema). Toda coluna `extraido_em` é `timestamptz`.

## Desenvolvimento com agentes em paralelo

Processo validado na 1ª onda (PRs #2–#4). Quem orquestra é a sessão principal; cada subagente
trabalha isolado.

**Preparação (orquestrador)**
- Dividir as tarefas por **área de código**, montar um mapa de quais arquivos cada uma toca e
  antecipar os conflitos. Tarefas no mesmo arquivo quente (`load.py`, `cli.py`) ou na mesma
  página HTML vão em ondas diferentes ou no mesmo agente.
- **Reservar números de ADR** por agente antes de começar (evita dois `0006`).
- Uma worktree por tarefa, irmã do repositório, numa branch criada da `main` atual:
  ```powershell
  git worktree add ..\indicadores-br.worktrees\<branch> -b <branch> main
  ```
- **Semear o warehouse** de cada worktree com o snapshot de produção (não com o banco local):
  `gh release download warehouse -p prod.duckdb -O <worktree>\data\warehouse.duckdb`, depois
  `uv sync` na worktree. O driver `dbc` e o cache do `uv` são compartilhados (nível do usuário).

**Briefing de cada subagente** (o prompt precisa ser autossuficiente)
- Caminho absoluto da worktree e da branch; proibido editar fora dela.
- Escopo: arquivos que pode tocar e os que **não** pode; o que os outros agentes estão fazendo.
- Validação obrigatória antes de cada commit (pytest, ruff, `dbt build`).
- Entrega: push + PR com `gh pr create` + aguardar o CI. **Agente não faz merge.**
- Force push (`git push --force-with-lease`) só na **própria branch** e **antes de qualquer
  revisão**. Depois que o PR foi revisado, só commits novos: reescrever o histórico invalida o
  que o revisor já leu e os comentários ancorados nos commits.
- Pedir no relatório final: arquivos alterados, decisões tomadas, e o que pode conflitar.
- Não usar portas fixas compartilhadas (cada um a sua, se precisar de servidor).

**Integração (um PR por vez)**
1. Simular antes: `git merge-tree --write-tree --name-only origin/<a> origin/<b>` mostra os
   conflitos textuais sem tocar em nada.
2. Merge do PR sem conflito → na branch do próximo PR, `git merge origin/main`, resolver,
   rodar a validação completa **com dados reais** e dar push; o CI do PR roda de novo.
3. Mesmo sem conflito textual, atualizar a branch com a `main` antes do merge: merge limpo não
   garante que o resultado funciona.

**Conflitos semânticos** (o git junta sem acusar; só revisão pega)
- Exemplo real: a correção de `extraido_em` para `timestamptz` (PR #2) e a tabela
  `raw.ibge_sidra` criada em paralelo com o padrão antigo (PR #3).
- Na revisão, procurar padrões que uma branch corrigiu e a outra copiou do estado antigo.
- Depois de resolver, **transformar a regra em teste** (ex.: toda tabela em `TABELAS_RAW`
  nasce com `timestamptz`), para não depender de alguém lembrar.

**Limpeza** ao fim da onda: `git worktree remove`, `git branch -d` (só apaga o que já entrou),
`git push origin --delete <branch>` e `git fetch --prune`.
