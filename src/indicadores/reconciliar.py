"""Reconciliação "full vence": compara o warehouse incremental com uma carga full do zero.

Uso na CI agendada (ADR 0006):

    DUCKDB_PATH=data/full.duckdb indicadores ingest --full --motivo reconciliacao
    indicadores reconciliar --base data/prod.duckdb --full data/full.duckdb

A comparação é série a série (contagem, min/max de data, soma) e linha a linha por
(série, data): linhas só de um lado e valores diferentes. Classificação:

- `igual`: nenhuma diferença;
- `revisao`: diferenças de valor ou de linhas compatíveis com revisão da fonte — registradas,
  **não** falham; o full vence (é ele que segue para o build e a publicação);
- `estrutural`: a série sumiu no full, a data máxima regrediu ou a contagem caiu mais que
  `QUEDA_MAXIMA` — falha o run antes de publicar;
- `fora_do_catalogo`: série só existe no incremental e saiu do catálogo; o full a descarta.

O histórico de auditoria (`raw.cargas`, `raw.reconciliacoes`) vive no warehouse publicado, então
o banco full (recém-criado) herda o histórico do incremental (`auditoria.herdar_auditoria`,
tolerante a schema diferente), e o resultado da reconciliação é gravado nele.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import astuple, dataclass, fields, replace
from datetime import date
from pathlib import Path

import duckdb

from indicadores.auditoria import herdar_auditoria
from indicadores.load import conectar, transacao

TOLERANCIA = 1e-9  # diferença de valor abaixo disso é ruído de float, não revisão
QUEDA_MAXIMA = 0.01  # full com mais de 1% de linhas a menos que o incremental = estrutural
SITUACOES = ("igual", "revisao", "estrutural", "fora_do_catalogo")
ALIAS_BASE = "base_incremental"

# Formato longo comum às duas fontes; `{db}` é o catálogo (vazio = banco principal).
SQL_LONGO = """
    select 'bcb' as fonte, serie_nome, data, valor from {db}raw.bcb_sgs
    union all
    select 'ibge' as fonte, serie_nome, data, valor from {db}raw.ibge_sidra
"""

SQL_COMPARACAO = f"""
with
incremental as ({SQL_LONGO.format(db=ALIAS_BASE + ".")}),
completo as ({SQL_LONGO.format(db="")}),
pares as (
    select
        coalesce(i.fonte, c.fonte)           as fonte,
        coalesce(i.serie_nome, c.serie_nome) as serie_nome,
        i.data as data_i, i.valor as valor_i,
        c.data as data_c, c.valor as valor_c
    from incremental as i
    full outer join completo as c
        on i.fonte = c.fonte and i.serie_nome = c.serie_nome and i.data = c.data
)
select
    fonte,
    serie_nome,
    count(data_i)::integer                                        as linhas_incremental,
    count(data_c)::integer                                        as linhas_full,
    min(data_i)                                                   as data_min_incremental,
    min(data_c)                                                   as data_min_full,
    max(data_i)                                                   as data_max_incremental,
    max(data_c)                                                   as data_max_full,
    sum(valor_i)                                                  as soma_incremental,
    sum(valor_c)                                                  as soma_full,
    count(*) filter (where data_c is null)::integer               as so_incremental,
    count(*) filter (where data_i is null)::integer               as so_full,
    count(*) filter (where abs(valor_i - valor_c) > {TOLERANCIA})::integer as valores_diferentes,
    max(abs(valor_i - valor_c))                                   as maior_diferenca
from pares
group by 1, 2
order by 1, 2
"""

SQL_EXEMPLOS = f"""
with
incremental as ({SQL_LONGO.format(db=ALIAS_BASE + ".")}),
completo as ({SQL_LONGO.format(db="")})
select
    coalesce(i.fonte, c.fonte), coalesce(i.serie_nome, c.serie_nome), coalesce(i.data, c.data),
    i.valor, c.valor
from incremental as i
full outer join completo as c
    on i.fonte = c.fonte and i.serie_nome = c.serie_nome and i.data = c.data
where i.data is null or c.data is null or abs(i.valor - c.valor) > {TOLERANCIA}
order by 1, 2, 3 desc
limit ?
"""


@dataclass(frozen=True)
class Comparacao:
    """Uma linha de `raw.reconciliacoes` (sem `execucao_id` e `executado_em`)."""

    fonte: str
    serie_nome: str
    linhas_incremental: int
    linhas_full: int
    data_min_incremental: date | None
    data_min_full: date | None
    data_max_incremental: date | None
    data_max_full: date | None
    soma_incremental: float | None
    soma_full: float | None
    so_incremental: int
    so_full: int
    valores_diferentes: int
    maior_diferenca: float | None
    situacao: str = ""
    detalhe: str = ""


def classificar(c: Comparacao, catalogo: Iterable[str]) -> tuple[str, str]:
    """(situacao, detalhe) de uma série comparada. Função pura: os critérios ficam testáveis."""
    if c.serie_nome not in set(catalogo):
        if c.linhas_full == 0:
            return "fora_do_catalogo", "série fora do catálogo: descartada pelo full"
        return "estrutural", "série fora do catálogo apareceu no full"
    estruturais = []
    if c.linhas_full == 0 and c.linhas_incremental > 0:
        estruturais.append("série sumiu no full")
    else:
        if (
            c.data_max_full is not None
            and c.data_max_incremental is not None
            and c.data_max_full < c.data_max_incremental
        ):
            estruturais.append(
                f"data máxima regrediu ({c.data_max_incremental} -> {c.data_max_full})"
            )
        if c.linhas_full < c.linhas_incremental * (1 - QUEDA_MAXIMA):
            queda = 1 - c.linhas_full / c.linhas_incremental
            estruturais.append(
                f"contagem caiu {queda:.1%} ({c.linhas_incremental} -> {c.linhas_full})"
            )
    if estruturais:
        return "estrutural", "; ".join(estruturais)
    revisoes = []
    if c.valores_diferentes:
        revisoes.append(f"{c.valores_diferentes} valores revisados (máx. {c.maior_diferenca:.6g})")
    if c.so_full:
        revisoes.append(f"{c.so_full} linhas só no full")
    if c.so_incremental:
        revisoes.append(f"{c.so_incremental} linhas só no incremental")
    if revisoes:
        return "revisao", "; ".join(revisoes)
    return "igual", "sem diferenças"


def comparar(con: duckdb.DuckDBPyConnection, catalogo: Iterable[str]) -> list[Comparacao]:
    """Compara o banco principal (full) com o anexado em `ALIAS_BASE` (incremental)."""
    catalogo = tuple(catalogo)
    comparacoes = []
    for linha in con.execute(SQL_COMPARACAO).fetchall():
        c = Comparacao(*linha)
        situacao, detalhe = classificar(c, catalogo)
        comparacoes.append(replace(c, situacao=situacao, detalhe=detalhe))
    return comparacoes


def gravar(con: duckdb.DuckDBPyConnection, execucao_id: str, comparacoes: list[Comparacao]) -> None:
    colunas = ["execucao_id", *(f.name for f in fields(Comparacao))]
    marcadores = ", ".join("?" for _ in colunas)
    con.execute("delete from raw.reconciliacoes where execucao_id = ?", [execucao_id])
    con.executemany(
        f"insert into raw.reconciliacoes ({', '.join(colunas)}) values ({marcadores})",
        [[execucao_id, *astuple(c)] for c in comparacoes],
    )


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def relatorio_markdown(
    execucao_id: str,
    comparacoes: list[Comparacao],
    exemplos: list[tuple],
    auditoria: Iterable[str] = (),
) -> str:
    estruturais = [c for c in comparacoes if c.situacao == "estrutural"]
    revisoes = [c for c in comparacoes if c.situacao == "revisao"]
    if estruturais:
        veredito = (
            f"**Divergência estrutural em {len(estruturais)} série(s): run falha, nada é "
            "publicado.**"
        )
    elif revisoes:
        veredito = (
            f"Revisões em {len(revisoes)} série(s): registradas; **o full vence** e segue "
            "para o build."
        )
    else:
        veredito = "Incremental e full idênticos; **o full vence** e segue para o build."
    saida = [
        f"### Reconciliação incremental × full — execução `{execucao_id}`",
        "",
        veredito,
        "",
        "| Fonte | Série | Situação | Linhas (inc → full) | Datas inc | Datas full "
        "| Só inc | Só full | Valores ≠ | Detalhe |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for c in comparacoes:
        saida.append(
            f"| {c.fonte} | `{c.serie_nome}` | {c.situacao} | "
            f"{c.linhas_incremental} → {c.linhas_full} | "
            f"{_fmt(c.data_min_incremental)}..{_fmt(c.data_max_incremental)} | "
            f"{_fmt(c.data_min_full)}..{_fmt(c.data_max_full)} | "
            f"{c.so_incremental} | {c.so_full} | {c.valores_diferentes} | {c.detalhe} |"
        )
    if exemplos:
        saida += [
            "",
            f"Exemplos de linhas divergentes (até {len(exemplos)}):",
            "",
            "| Fonte | Série | Data | Incremental | Full |",
            "| --- | --- | --- | ---: | ---: |",
        ]
        saida += [
            f"| {f} | `{s}` | {d} | {_fmt(vi)} | {_fmt(vf)} |" for f, s, d, vi, vf in exemplos
        ]
    if auditoria := list(auditoria):
        saida += ["", "Auditoria herdada do incremental:", ""]
        saida += [f"- {mensagem}" for mensagem in auditoria]
    return "\n".join(saida) + "\n"


def reconciliar(
    base: Path | str,
    full: Path | str,
    catalogo: Iterable[str],
    execucao_id: str | None = None,
    max_exemplos: int = 20,
) -> tuple[list[Comparacao], str]:
    """Compara `base` (incremental, só leitura) com `full`, grava a auditoria em `full`.

    Retorna (comparações, relatório markdown). Quem chama decide o que fazer com divergências
    estruturais (a CLI sai com código 2).
    """
    base, full = Path(base), Path(full)
    if base.resolve() == full.resolve():
        raise ValueError("--base e --full precisam ser arquivos diferentes")
    if not base.exists() or not full.exists():
        raise FileNotFoundError(f"warehouse não encontrado: {base if not base.exists() else full}")
    con = conectar(full)
    try:
        caminho = base.as_posix().replace("'", "''")  # literal SQL: aspas escapadas
        con.execute(f"attach '{caminho}' as {ALIAS_BASE} (read_only)")
        if execucao_id is None:
            linha = con.execute(
                "select execucao_id from raw.cargas order by executado_em desc limit 1"
            ).fetchone()
            execucao_id = linha[0] if linha else "sem-execucao"
        comparacoes = comparar(con, catalogo)
        exemplos = con.execute(SQL_EXEMPLOS, [max_exemplos]).fetchall()
        auditoria = herdar_auditoria(con, ALIAS_BASE)  # transação própria; nunca levanta
        with transacao(con):
            gravar(con, execucao_id, comparacoes)
        con.execute(f"detach {ALIAS_BASE}")
    finally:
        con.close()
    return comparacoes, relatorio_markdown(execucao_id, comparacoes, exemplos, auditoria)
