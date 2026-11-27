"""Extrator da API SIDRA do IBGE.

Endpoint: https://apisidra.ibge.gov.br/values/t/{tabela}/n1/all/v/{variavel}/p/all[/c{cl}/{cat}]/d/m

A resposta é uma lista JSON em que o **primeiro elemento é o cabeçalho** (rótulos das colunas
`NC`, `MN`, `V`, `D1C`, ...) e os demais são as observações. A ordem das dimensões `D1..Dn`
depende da tabela e das classificações pedidas, então a coluna de período é localizada pelo
rótulo no cabeçalho, não pela posição.

Conversão de período para data (ADR 0004): `data` = primeiro dia do **último mês** do período.
- trimestral `AAAATT` (202601 = 1º tri 2026)            -> 2026-03-01
- trimestre móvel `AAAAMM` (202610 = ago-set-out 2026) -> 2026-10-01
Assim o trimestre civil coincide com o trimestre móvel encerrado no mesmo mês.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

import httpx

from indicadores.config import SerieSIDRA

BASE_URL = "https://apisidra.ibge.gov.br/values"

# Rótulo da coluna de período no cabeçalho -> periodicidade do catálogo.
ROTULOS_PERIODO: dict[str, str] = {
    "Trimestre (Código)": "trimestral",
    "Trimestre Móvel (Código)": "trimestral_movel",
    "Mês (Código)": "mensal",
}

# Símbolos especiais do IBGE. "-" é zero absoluto (não resultante de arredondamento);
# os demais significam ausência de dado e a observação é descartada.
ZERO_ABSOLUTO = "-"
SEM_DADO = {"", "..", "...", "X"}


class RegistroSIDRA(NamedTuple):
    periodo_codigo: str
    periodo_nome: str
    data: date
    valor: float
    unidade: str


def montar_url(serie: SerieSIDRA) -> str:
    """Monta a URL da consulta: Brasil (n1), todos os períodos, máximo de casas decimais."""
    partes = [BASE_URL, f"t/{serie.tabela}", "n1/all", f"v/{serie.variavel}", "p/all"]
    partes += [f"c{cl}/{cat}" for cl, cat in serie.classificacoes]
    partes.append("d/m")
    return "/".join(partes)


def periodo_para_data(codigo: str, periodicidade: str) -> date:
    """Converte o código de período do SIDRA no primeiro dia do último mês do período."""
    if len(codigo) != 6 or not codigo.isdigit():
        raise ValueError(f"Código de período inválido: {codigo!r}")
    ano, sufixo = int(codigo[:4]), int(codigo[4:])
    if periodicidade == "trimestral":
        if not 1 <= sufixo <= 4:
            raise ValueError(f"Trimestre inválido em {codigo!r}")
        return date(ano, 3 * sufixo, 1)
    if periodicidade in ("trimestral_movel", "mensal"):
        if not 1 <= sufixo <= 12:
            raise ValueError(f"Mês inválido em {codigo!r}")
        return date(ano, sufixo, 1)
    raise ValueError(f"Periodicidade desconhecida: {periodicidade!r}")


def parse_valor(bruto: str | None) -> float | None:
    """Converte o campo `V`. Retorna None para os símbolos de ausência de dado."""
    texto = (bruto or "").strip()
    if texto in SEM_DADO:
        return None
    if texto == ZERO_ABSOLUTO:
        return 0.0
    return float(texto)


def localizar_periodo(cabecalho: dict[str, str]) -> tuple[str, str]:
    """Retorna (chave da coluna de código do período, periodicidade) a partir do cabeçalho."""
    for chave, rotulo in cabecalho.items():
        if rotulo in ROTULOS_PERIODO:
            return chave, ROTULOS_PERIODO[rotulo]
    raise ValueError(f"Cabeçalho SIDRA sem coluna de período: {cabecalho}")


def parse_resposta(payload: list[dict[str, str]]) -> tuple[str, list[RegistroSIDRA]]:
    """Converte a resposta do SIDRA em (periodicidade, registros), ignorando o cabeçalho."""
    if not payload:
        raise ValueError("Resposta SIDRA vazia (sem cabeçalho)")
    cabecalho, *linhas = payload
    chave_codigo, periodicidade = localizar_periodo(cabecalho)
    chave_nome = chave_codigo[:-1] + "N"  # D3C -> D3N
    registros = []
    for linha in linhas:
        valor = parse_valor(linha.get("V"))
        if valor is None:
            continue
        codigo = linha[chave_codigo]
        registros.append(
            RegistroSIDRA(
                periodo_codigo=codigo,
                periodo_nome=linha.get(chave_nome, ""),
                data=periodo_para_data(codigo, periodicidade),
                valor=valor,
                unidade=linha.get("MN", ""),
            )
        )
    return periodicidade, registros


def extrair_serie(
    serie: SerieSIDRA,
    inicio: date,
    client: httpx.Client | None = None,
) -> list[RegistroSIDRA]:
    """Baixa a série inteira (volume pequeno) e mantém os períodos com data >= `inicio`."""
    proprio_client = client is None
    client = client or httpx.Client(timeout=60.0)
    try:
        resp = client.get(montar_url(serie))
        if resp.status_code == 400:  # o SIDRA explica o erro em texto puro
            raise ValueError(f"SIDRA recusou a consulta de {serie.nome}: {resp.text.strip()}")
        resp.raise_for_status()
        periodicidade, registros = parse_resposta(resp.json())
    finally:
        if proprio_client:
            client.close()
    if periodicidade != serie.periodicidade:
        raise ValueError(
            f"{serie.nome}: periodicidade {periodicidade!r} na resposta, "
            f"esperada {serie.periodicidade!r}"
        )
    return [r for r in registros if r.data >= inicio]
