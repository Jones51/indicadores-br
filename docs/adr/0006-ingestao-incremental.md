# ADR 0006 — Ingestão incremental com estado na CI, reconciliação "full vence" e auditoria

- **Status:** aceito
- **Data:** 2026-11-27
- **Altera:** ADR 0003 (a CI deixa de reconstruir do zero a cada execução)

## Contexto

Até aqui, cada `indicadores ingest` baixava todas as séries desde 2010 e substituía cada uma
inteira (ADRs 0001 e 0004). Isso era simples, idempotente e absorvia qualquer revisão da fonte.
O custo estava em outro lugar: a CI não tinha estado. Cada execução dependia de as duas APIs
devolverem o histórico completo, e uma resposta parcial ou vazia viraria um warehouse publicado
com buracos, sem nada para comparar.

A ingestão incremental reduz o volume pedido às APIs, de ~11 mil para ~170 linhas por execução.
Em troca, a CI passa a ter **estado** (o warehouse publicado), e estado precisa de garantias:
validação antes do uso, um jeito de detectar deriva, backup e auditoria.

## Decisão

### 1. Janela incremental com margem (`incremental.py`, funções puras)

| Periodicidade | Início da janela | Exemplo |
| --- | --- | --- |
| diária (BCB) | `max(data) − 90 dias` | última 27/11 → recarrega desde 29/08 |
| mensal (BCB), trimestre móvel (IBGE) | `max(data)` recuado **2 períodos** | última out → recarrega desde ago (ago, set, out) |
| trimestral (IBGE) | `max(data)` recuado 2 trimestres | 3º tri → recarrega desde o 1º tri |

- Nos períodos, a margem inclui o último período carregado **e** os 2 anteriores: a mesma
  convenção da diária, em que `max − 90 dias` também recarrega o último dia.
- A carga **substitui** o intervalo `data >= inicio` da série (delete + insert) numa transação,
  junto com a linha de auditoria. Repetir a carga produz o mesmo `raw` (idempotente).
- **Full automático** quando a série não tem dados (série nova, banco vazio), quando a última
  data está no futuro (`estado_invalido`) ou com `--full`. O incremental nunca começa antes de
  `--inicio`.
- **BCB:** `dataInicial` = início da janela, `dataFinal` = hoje; `janelas()` continua dividindo
  em blocos de 10 anos (no incremental é sempre um bloco).
- **IBGE/SIDRA:** a consulta incremental usa a faixa `p/AAAAPP-AAAAPP`, do período que contém
  o início da janela ao período de hoje. Na API real (27/11/2026) verificamos que a faixa pode
  terminar num período ainda não divulgado (vem só o que existe), que uma faixa sem períodos
  divulgados devolve só o cabeçalho e que uma faixa invertida devolve HTTP 400. Preferimos a faixa
  a `p/last N` porque a substituição é por **data**, e `last N` conta períodos divulgados, não
  datas: uma divulgação atrasada deslocaria a janela. O full continua com `p/all`. Assim a
  reconciliação compara dois caminhos de consulta diferentes, e não o mesmo caminho duas vezes.
- **Resposta vazia não apaga:** se a fonte devolve zero linhas para uma janela que tem dados, a
  carga falha (`JanelaVaziaError`) e nada muda. Uma instabilidade da API (o SGS devolve 404
  também para "sem dados") não pode virar perda de dados.

### 2. Estado da CI = `prod.duckdb` da release

1. A CI baixa o `prod.duckdb` da release `warehouse`, inclusive em PRs (só leitura).
2. **Valida** (`indicadores validar`): o arquivo abre no DuckDB? `raw.bcb_sgs` e
   `raw.ibge_sidra` existem com o schema que o código atual cria? As tabelas de controle, se
   existirem, também? Há chaves `(série, data)` duplicadas? O schema esperado é derivado dos
   próprios DDLs de `load.py`, então não existe uma segunda definição para manter em sincronia.
3. Inválido → o arquivo é descartado e a carga é full (`--motivo estado_invalido`). Release sem
   o asset → banco novo, e cada série vira full sozinha (`sem_dados`). **Erro ao consultar a
   release** (rede, permissão) → o run falha: não é seguro tratar isso como "não há estado".

### 3. Reconciliação semanal "full vence"

No agendamento de segunda-feira, depois do incremental, a CI faz uma carga **full num banco
separado** e roda `indicadores reconciliar --base prod.duckdb --full full.duckdb`:

- compara série a série (contagem, min/max de data, soma dos valores) e **linha a linha** por
  `(série, data)`: linhas só no incremental, linhas só no full e valores diferentes
  (tolerância `1e-9`);
- **revisão** (valores diferentes, linhas a mais ou poucas a menos) é registrada e **não falha**.
  O full vence: é ele que segue para o `dbt build` e é publicado;
- **estrutural** falha o run antes de publicar: série que sumiu no full, data máxima que
  regrediu, ou contagem que caiu mais de 1% (`QUEDA_MAXIMA`). São sinais de fonte quebrada ou
  catálogo errado, e não de revisão, então nenhum dos dois bancos é confiável para publicar;
- séries que saíram do catálogo e só existem no incremental ficam como `fora_do_catalogo`: o
  full as descarta, o que limpa órfãos (ADR 0004);
- o resultado vai para o **resumo do run** e para `raw.reconciliacoes`. O banco full herda o
  histórico de `raw.cargas`/`raw.reconciliacoes` do incremental, então a auditoria não se perde
  quando o full vence.

A reconciliação também roda em **PRs** (só valida, nada é publicado). Assim o caminho do
agendamento é exercitado antes do merge. No `workflow_dispatch`, roda se `reconciliar` for
marcado. Fora disso, push e manual rodam só o incremental.

### 4. Portão, backup e rollback

- **Portão:** `dbt build` (modelos + testes, inclusive os das sources de auditoria) e
  `dbt source freshness` precisam passar. Qualquer falha antes da publicação deixa o
  `prod.duckdb` publicado intocado.
- **Backup:** antes de sobrescrever, o `prod.duckdb` baixado no início sobe como
  `prod.anterior.duckdb` na mesma release, mas só se for válido. Um estado inválido não
  sobrescreve um backup bom.
- **Rollback:** publicar `prod.anterior.duckdb` de volta como `prod.duckdb` (passo a passo no
  README). O dashboard/docs voltam no próximo run.

### 5. Auditoria `raw.cargas`

Uma linha por série por execução, na **mesma transação** da carga: `execucao_id`
(`GITHUB_RUN_ID-tentativa` na CI; `local-<instante>-<aleatório>` fora dela), `fonte`,
`serie_nome`, `modo` (`full`/`incremental`), `motivo` (`margem`, `sem_dados`, `forcado`,
`estado_invalido`, `reconciliacao`), `inicio_pedido`, `ultima_data_antes`/`depois`,
`linhas_recebidas`/`removidas`/`inseridas`, `duracao_s` e `executado_em` (`timestamptz`, como
toda coluna de tempo da raw; um teste trava a regra). Ela é declarada como source no dbt com
testes e `freshness`. O dashboard mostra a última carga por fonte (`ultimas_cargas` no JSON).

## Alternativas descartadas

- **Incremental sem reconciliação:** revisões fora da margem (o PIB é revisado anos para trás,
  e o IPCA tem revisões raras) ficariam para sempre no warehouse publicado.
- **Reconciliar sem publicar o full ("incremental vence" e só alerta):** exigiria corrigir à mão
  a cada revisão. O full é a definição de verdade; o incremental é otimização.
- **Estado em cache do Actions:** é por branch, expira e não é público. A release já é o
  artefato que os usuários consomem, então validar e publicar sobre ela mantém uma fonte única.
- **`p/last N` no SIDRA:** ver item 1.

## Consequências e riscos

- A CI passa a depender do próprio artefato publicado. Se um `prod.duckdb` ruim passar pela
  validação e pelo portão, o incremental seguinte parte dele. Mitigações: validação de schema e
  de duplicatas, portão dbt, reconciliação semanal que reconstrói do zero, e backup para
  rollback.
- **Revisões fora da margem** ficam até a próxima segunda-feira (no máximo ~1 semana), o mesmo
  horizonte do `freshness`.
- **Corrida entre runs:** dois runs na `main` são serializados pelo grupo de `concurrency` (sem
  `cancel-in-progress` fora de PRs), então o estado baixado é o último publicado. Um upload
  manual de asset durante um run seria sobrescrito.
- A validação não detecta valores errados com schema certo. Isso é papel da reconciliação.
- O critério de "estrutural" (1% de queda, data máxima) é uma heurística; uma revisão legítima
  que remova muitas linhas falhará o run e exigirá olhar o relatório e, se for o caso, rodar o
  workflow manual com `modo: full`.
- Em PRs, a reconciliação dobra as chamadas às APIs (um incremental + um full).
- `raw.cargas` cresce ~8 linhas por run (~16 nas segundas): desprezível.
