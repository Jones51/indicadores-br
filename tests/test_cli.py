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


def test_validar_sai_com_1_em_estado_invalido(monkeypatch, tmp_path, capsys):
    lixo = tmp_path / "prod.duckdb"
    lixo.write_bytes(b"nao e duckdb")
    with pytest.raises(SystemExit) as saida:
        _rodar(monkeypatch, "validar", "--db", str(lixo))
    assert saida.value.code == 1
    assert "[inválido]" in capsys.readouterr().out


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
