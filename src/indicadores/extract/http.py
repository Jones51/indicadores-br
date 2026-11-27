"""GET com retentativas para as APIs públicas (BCB e IBGE).

As duas APIs devolvem 5xx esporádicos (ex.: 502 do SGS em consultas de 10 anos) e às vezes
estouram o timeout. Isso não é erro dos dados: tentar de novo com espera crescente resolve, e
um run da CI não deve falhar por isso. Erros 4xx não são repetidos, porque têm significado:
404 = janela sem dados no SGS, 400 = parâmetro inválido no SIDRA.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

TENTATIVAS = 4
ESPERA_INICIAL_S = 2.0  # 2s, 4s, 8s entre as tentativas


def get_com_retentativas(
    client: httpx.Client,
    url: str,
    params: dict[str, str] | None = None,
    tentativas: int = TENTATIVAS,
    espera: Callable[[float], None] | None = None,
) -> httpx.Response:
    """Faz o GET; repete em 5xx e erros de transporte. Devolve a última resposta (ou propaga)."""
    espera = espera or time.sleep  # resolvido na chamada: testes podem trocar `time.sleep`
    for tentativa in range(1, tentativas + 1):
        ultima = tentativa == tentativas
        try:
            resp = client.get(url, params=params)
        except httpx.TransportError:  # timeout, conexão recusada/resetada
            if ultima:
                raise
        else:
            if resp.status_code < 500 or ultima:
                return resp
        espera(ESPERA_INICIAL_S * 2 ** (tentativa - 1))
    raise AssertionError("inalcançável")  # pragma: no cover
