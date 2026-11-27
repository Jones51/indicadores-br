"""Códigos de saída da CLI: o workflow da CI depende deles para decidir full e publicação."""

from datetime import date

import duckdb
import pytest

from indicadores import cli
from indicadores.config import SERIES_BCB
from indicadores.load import carregar_serie, conectar


def _rodar(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["indicadores", *args])
    cli.main()


def test_validar_sai_com_4_em_arquivo_corrompido(monkeypatch, tmp_path, capsys):
    lixo = tmp_path / "prod.duckdb"
    lixo.write_bytes(b"nao e duckdb")
    with pytest.raises(SystemExit) as saida:
        _rodar(monkeypatch, "validar", "--db", str(lixo))
    assert saida.value.code == cli.SAIDA_CORROMPIDO == 4
    assert "[corrompido]" in capsys.readouterr().out


def test_validar_sai_com_3_quando_abre_mas_e_invalido(monkeypatch, tmp_path, capsys):
    caminho = tmp_path / "prod.duckdb"
    conectar(caminho).close()
    con = duckdb.connect(str(caminho))
    con.execute("alter table raw.bcb_sgs add column fonte_nova varchar")  # schema "do futuro"
    con.close()
    with pytest.raises(SystemExit) as saida:
        _rodar(monkeypatch, "validar", "--db", str(caminho))
    assert saida.value.code == cli.SAIDA_INVALIDO == 3
    assert "[inválido] raw.bcb_sgs com schema diferente" in capsys.readouterr().out


def test_herdar_auditoria_pela_cli(monkeypatch, tmp_path, capsys):
    origem, destino = tmp_path / "antigo.duckdb", tmp_path / "novo.duckdb"
    con = conectar(origem)
    con.execute(
        "insert into raw.cargas values ('r1', 'bcb', 'selic_meta', 'full', 'sem_dados', "
        "date '2010-01-01', null, date '2024-01-01', 1, 0, 1, 0.1, now())"
    )
    con.close()
    _rodar(monkeypatch, "herdar-auditoria", "--origem", str(origem), "--db", str(destino))
    assert "[auditoria] raw.cargas: 1 linhas copiadas" in capsys.readouterr().out


def test_validar_sai_com_0_em_estado_valido(monkeypatch, tmp_path, capsys):
    caminho = tmp_path / "prod.duckdb"
    conectar(caminho).close()
    _rodar(monkeypatch, "validar", "--db", str(caminho))
    assert "[ok] estado válido" in capsys.readouterr().out


def test_reconciliar_sai_com_2_em_divergencia_estrutural(monkeypatch, tmp_path):
    selic = next(s for s in SERIES_BCB if s.nome == "selic_meta")
    base, full = tmp_path / "base.duckdb", tmp_path / "full.duckdb"
    con = conectar(base)
    carregar_serie(con, selic, [(date(2024, 1, 1), 11.75), (date(2024, 1, 2), 11.75)])
    con.close()
    conectar(full).close()  # full sem a série: "série sumiu"
    relatorio = tmp_path / "rec.md"

    with pytest.raises(SystemExit) as saida:
        _rodar(
            monkeypatch,
            "reconciliar",
            "--base",
            str(base),
            "--full",
            str(full),
            "--relatorio",
            str(relatorio),
            "--execucao-id",
            "teste",
        )

    assert saida.value.code == 2
    assert "série sumiu no full" in relatorio.read_text(encoding="utf-8")
    con = duckdb.connect(str(full), read_only=True)
    assert con.execute("select situacao from raw.reconciliacoes").fetchall() == [("estrutural",)]
    con.close()
