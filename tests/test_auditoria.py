"""Herança da auditoria entre warehouses: tolerante a schema diferente e sem nunca falhar."""

from datetime import date

import duckdb
import pytest
from conftest import SERIES_BCB_TESTE, SERIES_IBGE_TESTE

from indicadores.auditoria import herdar_auditoria_de_arquivo
from indicadores.estado import diagnosticar_estado
from indicadores.ingestao import ingerir
from indicadores.load import conectar

CARGA = (
    "'{id}', 'bcb', 'selic_meta', 'incremental', 'margem', date '2024-04-01', "
    "date '2024-06-30', date '2024-06-30', 91, 91, 91, 0.2, timestamptz '2024-06-30 09:17:00+00'"
)


@pytest.fixture
def origem(tmp_path):
    """Warehouse antigo com 2 cargas e 1 reconciliação, no schema atual."""
    caminho = tmp_path / "antigo.duckdb"
    con = conectar(caminho)
    for id_ in ("r1", "r2"):
        con.execute(f"insert into raw.cargas values ({CARGA.format(id=id_)})")
    con.execute(
        "insert into raw.reconciliacoes (execucao_id, fonte, serie_nome, linhas_incremental, "
        "linhas_full, so_incremental, so_full, valores_diferentes, situacao, detalhe) "
        "values ('r2', 'bcb', 'selic_meta', 10, 10, 0, 0, 0, 'igual', 'sem diferenças')"
    )
    con.close()
    return caminho


def _contar(caminho, tabela):
    con = duckdb.connect(str(caminho), read_only=True)
    try:
        return con.execute(f"select count(*) from raw.{tabela}").fetchone()[0]
    finally:
        con.close()


def test_copia_historico_e_e_idempotente(origem, tmp_path):
    destino = tmp_path / "novo.duckdb"
    assert herdar_auditoria_de_arquivo(origem, destino) == [
        "raw.cargas: 2 linhas copiadas",
        "raw.reconciliacoes: 1 linhas copiadas",
    ]
    assert herdar_auditoria_de_arquivo(origem, destino)[0] == "raw.cargas: 0 linhas copiadas"
    assert (_contar(destino, "cargas"), _contar(destino, "reconciliacoes")) == (2, 1)


def test_schema_diferente_copia_as_colunas_em_comum(origem, tmp_path):
    con = duckdb.connect(str(origem))
    con.execute("alter table raw.cargas add column coluna_do_futuro varchar")
    con.execute("alter table raw.cargas drop column duracao_s")  # destino: not null sem default
    con.execute("alter table raw.reconciliacoes drop column detalhe")
    con.execute("alter table raw.reconciliacoes drop column maior_diferenca")  # nulável
    con.close()
    destino = tmp_path / "novo.duckdb"

    mensagens = herdar_auditoria_de_arquivo(origem, destino)

    # cargas: falta coluna not null no destino -> não copia, registra o motivo, não levanta
    assert mensagens[0].startswith("raw.cargas: não copiado (ConstraintException")
    # reconciliacoes: `detalhe` é not null sem default -> também não; sem ela, copiaria
    assert mensagens[1].startswith("raw.reconciliacoes: não copiado")
    assert _contar(destino, "cargas") == 0


def test_colunas_extras_e_nulaveis_ausentes_sao_toleradas(origem, tmp_path):
    con = duckdb.connect(str(origem))
    con.execute("alter table raw.cargas add column coluna_do_futuro varchar")
    con.execute("alter table raw.cargas drop column ultima_data_antes")  # nulável no destino
    con.close()
    destino = tmp_path / "novo.duckdb"
    (cargas, _) = herdar_auditoria_de_arquivo(origem, destino)
    assert cargas == (
        "raw.cargas: 2 linhas copiadas (colunas só na origem ignoradas: coluna_do_futuro; "
        "colunas ausentes na origem: ultima_data_antes)"
    )
    assert _contar(destino, "cargas") == 2


def test_origem_sem_chave_ou_sem_tabelas_ou_corrompida_nao_falha(origem, tmp_path):
    con = duckdb.connect(str(origem))
    con.execute("alter table raw.cargas drop column modo")
    con.execute("drop table raw.reconciliacoes")
    con.close()
    destino = tmp_path / "novo.duckdb"
    assert herdar_auditoria_de_arquivo(origem, destino) == [
        "raw.cargas: não copiado, a origem não tem a chave modo",
        "raw.reconciliacoes: ausente na origem, nada a copiar",
    ]
    lixo = tmp_path / "lixo.duckdb"
    lixo.write_bytes(b"corrompido")
    (mensagem,) = herdar_auditoria_de_arquivo(lixo, destino)
    assert mensagem.startswith("origem não abre")


def test_estado_descartado_por_schema_preserva_auditoria(fonte, origem, tmp_path):
    """Fluxo da CI: abre mas é inválido -> descarta, herda a auditoria, faz full."""
    con = duckdb.connect(str(origem))
    con.execute("alter table raw.bcb_sgs add column coluna_do_futuro varchar")
    con.close()
    diagnostico = diagnosticar_estado(origem)
    assert diagnostico.abre and not diagnostico.valido

    novo = tmp_path / "prod.duckdb"
    herdar_auditoria_de_arquivo(origem, novo)
    fonte.publicar_ate(date(2024, 6, 30))
    con = conectar(novo)
    try:
        with fonte.client() as client:
            ingerir(
                con,
                SERIES_BCB_TESTE,
                SERIES_IBGE_TESTE,
                inicio_padrao=date(2023, 1, 1),
                hoje=date(2024, 6, 30),
                execucao_id="r3",
                forcar_full=True,
                motivo_full="estado_invalido",
                client_bcb=client,
                client_ibge=client,
            )
        execucoes = con.execute(
            "select execucao_id, motivo, count(*) from raw.cargas group by all order by all"
        ).fetchall()
    finally:
        con.close()
    assert execucoes == [("r1", "margem", 1), ("r2", "margem", 1), ("r3", "estado_invalido", 4)]
    assert diagnosticar_estado(novo).valido
