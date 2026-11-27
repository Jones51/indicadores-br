from datetime import date

import pytest

from indicadores.extract.ibge import data_para_periodo, faixa_periodos, periodo_para_data
from indicadores.incremental import Janela, calcular_janela, inicio_com_margem, recuar_meses

INICIO = date(2010, 1, 1)
HOJE = date(2026, 11, 27)


@pytest.mark.parametrize(
    ("d", "meses", "esperado"),
    [
        (date(2026, 10, 1), 2, date(2026, 8, 1)),
        (date(2026, 2, 15), 2, date(2025, 12, 1)),
        (date(2026, 9, 1), 6, date(2026, 3, 1)),
        (date(2026, 1, 1), 12, date(2025, 1, 1)),
    ],
)
def test_recuar_meses(d, meses, esperado):
    assert recuar_meses(d, meses) == esperado


@pytest.mark.parametrize(
    ("ultima", "periodicidade", "esperado"),
    [
        (date(2026, 11, 27), "diaria", date(2026, 8, 29)),  # 90 dias
        (date(2026, 10, 1), "mensal", date(2026, 8, 1)),  # 2 meses
        (date(2026, 10, 1), "trimestral_movel", date(2026, 8, 1)),  # 2 trimestres móveis
        (date(2026, 9, 1), "trimestral", date(2026, 3, 1)),  # 2 trimestres = 6 meses
    ],
)
def test_inicio_com_margem_por_periodicidade(ultima, periodicidade, esperado):
    assert inicio_com_margem(ultima, periodicidade) == esperado


def test_inicio_com_margem_rejeita_periodicidade_desconhecida():
    with pytest.raises(ValueError):
        inicio_com_margem(HOJE, "anual")


def test_janela_diaria_incremental_90_dias():
    assert calcular_janela(date(2026, 11, 27), "diaria", INICIO, HOJE) == Janela(
        "incremental", "margem", date(2026, 8, 29)
    )


def test_janela_mensal_e_trimestral_recarregam_2_periodos_antes_do_ultimo():
    mensal = calcular_janela(date(2026, 10, 1), "mensal", INICIO, HOJE)
    trimestral = calcular_janela(date(2026, 9, 1), "trimestral", INICIO, HOJE)
    assert mensal == Janela("incremental", "margem", date(2026, 8, 1))
    # 3º tri carregado -> recarrega 1º, 2º e 3º tri (datas 03, 06 e 09)
    assert trimestral == Janela("incremental", "margem", date(2026, 3, 1))


def test_serie_vazia_vira_full_desde_o_inicio():
    assert calcular_janela(None, "diaria", INICIO, HOJE) == Janela("full", "sem_dados", INICIO)


def test_full_forcado_ignora_ultima_data():
    janela = calcular_janela(date(2026, 11, 27), "diaria", INICIO, HOJE, forcar_full=True)
    assert janela == Janela("full", "forcado", INICIO)
    janela = calcular_janela(
        HOJE, "mensal", INICIO, HOJE, forcar_full=True, motivo_full="reconciliacao"
    )
    assert janela.motivo == "reconciliacao"


def test_full_com_motivo_desconhecido_falha():
    with pytest.raises(ValueError):
        calcular_janela(HOJE, "diaria", INICIO, HOJE, forcar_full=True, motivo_full="xyz")


def test_ultima_data_no_futuro_e_estado_invalido():
    assert calcular_janela(date(2027, 1, 1), "diaria", INICIO, HOJE) == Janela(
        "full", "estado_invalido", INICIO
    )


def test_incremental_nunca_comeca_antes_do_inicio_do_historico():
    assert calcular_janela(date(2010, 2, 1), "diaria", INICIO, HOJE).inicio == INICIO


@pytest.mark.parametrize(
    ("d", "periodicidade", "codigo"),
    [
        (date(2026, 3, 1), "trimestral", "202601"),
        (date(2026, 2, 10), "trimestral", "202601"),
        (date(2026, 12, 1), "trimestral", "202604"),
        (date(2026, 10, 1), "trimestral_movel", "202610"),
        (date(2024, 1, 31), "mensal", "202401"),
    ],
)
def test_data_para_periodo(d, periodicidade, codigo):
    assert data_para_periodo(d, periodicidade) == codigo
    # o período encontrado termina no mês de `d` ou depois: a faixa não perde nada
    assert periodo_para_data(codigo, periodicidade) >= d.replace(day=1)


def test_faixa_periodos_da_margem_ate_hoje():
    assert faixa_periodos(date(2026, 3, 1), HOJE, "trimestral") == "202601-202604"
    assert faixa_periodos(date(2026, 8, 1), HOJE, "trimestral_movel") == "202608-202611"
    with pytest.raises(ValueError):
        faixa_periodos(HOJE, date(2026, 1, 1), "mensal")
