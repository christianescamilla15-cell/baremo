"""Sonda `seguridad.confidencialidad` (N12).

Las listas de términos de estas pruebas son FALSAS y llegan por la variable de entorno.
La lista real de la máquina nunca se lee aquí (ver conftest.py).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from baremo.model import Veredicto
from baremo.probes import confidencialidad
from conftest import medir, texto_de

CONF = "seguridad.confidencialidad"
TERMINOS_FALSOS = "# comentario: no es regla\nzorglub\nproveedor-\\d{3}\n"


def _git(raiz: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(raiz), *args], check=True, capture_output=True)


@pytest.fixture
def repo_git(repo):
    def _crear(archivos: dict[str, str]) -> Path:
        raiz = repo(archivos)
        _git(raiz, "init", "-q")
        _git(raiz, "add", "-A")
        return raiz
    return _crear


def test_sin_menciones_cumple_y_dice_cuanto_reviso(repo_git, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", TERMINOS_FALSOS)
    raiz = repo_git({"README.md": "# Demo\n", "src/app.py": "x = 1\n"})
    check = medir(CONF, raiz)
    sub = check.subchecks[0]
    assert sub.veredicto is Veredicto.CUMPLE
    assert sub.evidencias[0].extracto == "2 archivos revisados con 2 reglas · 0 hallazgos"
    assert "git ls-files" in sub.evidencias[0].detalle


def test_una_mencion_no_cumple_y_la_evidencia_nunca_incluye_el_termino(
        repo_git, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", TERMINOS_FALSOS)
    raiz = repo_git({"README.md": "# Demo\n\nHecho para ZorGlub y proveedor-042.\n"})
    check = medir(CONF, raiz)
    sub = check.subchecks[0]
    assert sub.veredicto is Veredicto.NO_CUMPLE
    extractos = [e.extracto for e in sub.evidencias]
    assert "línea 3 · regla #1" in extractos and "línea 3 · regla #2" in extractos
    publicado = texto_de(check).lower()
    assert "zorglub" not in publicado
    assert "proveedor-042" not in publicado and "proveedor-" not in publicado


def test_solo_cuentan_los_archivos_versionados(repo_git, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", TERMINOS_FALSOS)
    raiz = repo_git({"README.md": "# Demo\n"})
    (raiz / "notas-locales.txt").write_text("zorglub\n", encoding="utf-8")   # sin versionar
    assert medir(CONF, raiz).subchecks[0].veredicto is Veredicto.CUMPLE


def test_fuera_de_git_revisa_el_arbol_y_lo_declara(repo, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", TERMINOS_FALSOS)
    sub = medir(CONF, repo({"a.md": "zorglub\n"})).subchecks[0]
    assert sub.veredicto is Veredicto.NO_CUMPLE
    assert "árbol de trabajo" in sub.evidencias[0].detalle


def test_la_lista_local_se_usa_si_la_variable_esta_vacia(
        repo_git, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lista = tmp_path / "lista-falsa.txt"
    lista.write_text("zorglub\n", encoding="utf-8")
    monkeypatch.setattr(confidencialidad, "LISTA_LOCAL", lista)
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", "")
    sub = medir(CONF, repo_git({"a.md": "zorglub\n"})).subchecks[0]
    assert sub.veredicto is Veredicto.NO_CUMPLE
    assert "lista local" in sub.evidencias[0].detalle


def test_sin_lista_es_no_medible(repo_git) -> None:
    sub = medir(CONF, repo_git({"README.md": "# Demo\n"})).subchecks[0]
    assert sub.veredicto is Veredicto.NO_MEDIBLE
    assert "No hay lista" in sub.motivo


def test_regla_invalida_es_no_medible_sin_imprimirla(repo_git, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", "zorglub\nsecreto([\n")
    sub = medir(CONF, repo_git({"README.md": "# Demo\n"})).subchecks[0]
    assert sub.veredicto is Veredicto.NO_MEDIBLE
    assert "regla #2" in sub.motivo
    assert "secreto" not in sub.motivo


def test_sin_archivos_revisados_es_no_medible(repo_git, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFIDENCIAL_TERMINOS", TERMINOS_FALSOS)
    raiz = repo_git({"logo.png": "x"})
    (raiz / "logo.png").write_bytes(b"\x00\x89PNG")      # binario: no se revisa
    _git(raiz, "add", "-A")
    assert medir(CONF, raiz).subchecks[0].veredicto is Veredicto.NO_MEDIBLE
