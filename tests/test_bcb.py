from datetime import date

from indicadores.extract.bcb import janelas, parse_registros


def test_parse_registros_converte_e_ignora_vazios():
    payload = [
        {"data": "01/01/2024", "valor": "11.75"},
        {"data": "02/01/2024", "valor": ""},
    ]
    assert parse_registros(payload) == [(date(2024, 1, 1), 11.75)]


def test_janelas_cobre_intervalo_sem_buracos():
    inicio, fim = date(2000, 1, 1), date(2024, 6, 30)
    js = list(janelas(inicio, fim))
    assert js[0][0] == inicio
    assert js[-1][1] == fim
    for (_, f1), (i2, _) in zip(js, js[1:], strict=False):
        assert (i2 - f1).days == 1


def test_janelas_intervalo_curto_retorna_uma():
    assert list(janelas(date(2024, 1, 1), date(2024, 2, 1))) == [
        (date(2024, 1, 1), date(2024, 2, 1))
    ]
