from datetime import date

import duckdb
import pytest
from conftest import SERIES_BCB_TESTE, SERIES_IBGE_TESTE

from indicadores.estado import diagnosticar_estado, validar_estado
from indicadores.ingestao import ingerir
from indicadores.load import conectar


@pytest.fixture
def valido(tmp_path):
    caminho = tmp_path / "prod.duckdb"
    conectar(caminho).close()
    return caminho


def test_banco_criado_pelo_codigo_atual_e_valido(valido):
    assert validar_estado(valido) == []


def test_banco_sem_tabelas_de_controle_ainda_e_valido(valido):
    # O prod publicado antes da auditoria não tem raw.cargas: `conectar()` cria na 1ª carga.
    con = duckdb.connect(str(valido))
    con.execute("drop table raw.cargas; drop table raw.reconciliacoes")
    con.close()
    assert validar_estado(valido) == []


def test_arquivo_inexistente_e_invalido(tmp_path):
    assert validar_estado(tmp_path / "nada.duckdb")[0].startswith("arquivo não existe")


def test_arquivo_que_nao_e_duckdb_e_invalido(tmp_path):
    lixo = tmp_path / "prod.duckdb"
    lixo.write_bytes(b"<html>not found</html>" * 100)
    assert validar_estado(lixo)[0].startswith("não abre no DuckDB")


def test_tabela_raw_ausente_e_invalido(valido):
    con = duckdb.connect(str(valido))
    con.execute("drop table raw.ibge_sidra")
    con.close()
    assert validar_estado(valido) == ["tabela raw.ibge_sidra ausente"]


def test_schema_diferente_e_invalido(valido):
    con = duckdb.connect(str(valido))
    con.execute("alter table raw.bcb_sgs alter extraido_em type timestamp")
    con.close()
    (problema,) = validar_estado(valido)
    assert problema.startswith("raw.bcb_sgs com schema diferente")


def test_chave_duplicada_e_invalido(valido):
    con = duckdb.connect(str(valido))
    con.execute(
        "insert into raw.bcb_sgs (serie_codigo, serie_nome, data, valor) values "
        "(432, 'selic_meta', date '2024-01-01', 1), (432, 'selic_meta', date '2024-01-01', 2)"
    )
    con.close()
    assert validar_estado(valido) == ["raw.bcb_sgs: 1 chaves (serie_codigo, data) duplicadas"]


def test_validacao_nao_altera_o_arquivo(valido):
    antes = valido.read_bytes()
    validar_estado(valido)
    assert valido.read_bytes() == antes


def test_estado_invalido_descartado_resulta_em_full(fonte, tmp_path):
    """Fluxo da CI: estado inválido -> arquivo descartado -> `ingest --full --motivo ...`."""
    caminho = tmp_path / "prod.duckdb"
    caminho.write_bytes(b"corrompido")
    assert validar_estado(caminho)
    caminho.unlink()

    fonte.publicar_ate(date(2024, 6, 30))
    con = conectar(caminho)
    try:
        with fonte.client() as client:
            cargas = ingerir(
                con,
                SERIES_BCB_TESTE,
                SERIES_IBGE_TESTE,
                inicio_padrao=date(2023, 1, 1),
                hoje=date(2024, 6, 30),
                forcar_full=True,
                motivo_full="estado_invalido",
                client_bcb=client,
                client_ibge=client,
            )
    finally:
        con.close()
    assert {(c.modo, c.motivo) for c in cargas} == {("full", "estado_invalido")}
    assert validar_estado(caminho) == []


def test_diagnostico_separa_corrompido_de_invalido_como_base(valido, tmp_path):
    """Corrompido não serve nem de backup; schema diferente serve (passou no build ao publicar)."""
    assert diagnosticar_estado(valido) == (True, [])
    assert diagnosticar_estado(valido).valido

    lixo = tmp_path / "lixo.duckdb"
    lixo.write_bytes(b"corrompido")
    corrompido = diagnosticar_estado(lixo)
    assert (corrompido.abre, corrompido.valido) == (False, False)
    ausente = diagnosticar_estado(tmp_path / "nada.duckdb")
    assert (ausente.abre, ausente.valido) == (False, False)

    con = duckdb.connect(str(valido))
    con.execute("alter table raw.bcb_sgs drop column extraido_em")  # schema antigo
    con.close()
    antigo = diagnosticar_estado(valido)
    assert (antigo.abre, antigo.valido) == (True, False)
    assert antigo.problemas[0].startswith("raw.bcb_sgs com schema diferente")


def test_duplicata_abre_mas_e_invalido(valido):
    con = duckdb.connect(str(valido))
    con.execute(
        "insert into raw.ibge_sidra (serie_nome, tabela, variavel, periodo_codigo, periodo_nome, "
        "data, valor, unidade) select 'x', 1, 1, '202401', 'p', date '2024-03-01', 1, '%' "
        "from range(2)"
    )
    con.close()
    diagnostico = diagnosticar_estado(valido)
    assert (diagnostico.abre, diagnostico.valido) == (True, False)
