"""El contrato que toda sonda hereda: evidencia obligatoria, NO_MEDIBLE con motivo, nada
de aprobar por ausencia, y una sonda rota nunca aprueba. Más dos paridades de
documentación: el README lista cada sonda registrada y la versión es una sola."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import baremo
from baremo.cli import SondaRegistrada
from baremo.model import Evidencia, Veredicto
from baremo.probes import REGISTRO, Contexto, subcheck

RAIZ = Path(__file__).resolve().parents[1]


def test_cumple_sin_evidencia_es_un_error_de_programacion() -> None:
    with pytest.raises(ValueError, match="sin evidencia no es auditable"):
        subcheck("X_1", "algo", Veredicto.CUMPLE, "demo")


def test_no_cumple_sin_evidencia_es_un_error_de_programacion() -> None:
    with pytest.raises(ValueError, match="sin evidencia no es auditable"):
        subcheck("X_1", "algo", Veredicto.NO_CUMPLE, "demo")


def test_no_medible_sin_motivo_es_un_error_de_programacion() -> None:
    with pytest.raises(ValueError, match="exige un motivo"):
        subcheck("X_1", "algo", Veredicto.NO_MEDIBLE, "demo")


def test_evidencia_sin_fuente_no_es_evidencia() -> None:
    with pytest.raises(ValueError, match="sin fuente"):
        Evidencia(fuente="")


def test_una_sonda_que_falla_es_no_medible_y_nunca_aprueba(tmp_path: Path) -> None:
    class Rota:
        id = "rota"

        def evaluar(self, ctx: Contexto) -> None:
            raise RuntimeError("se cayó la conexión")

    sonda = SondaRegistrada(id="rota", titulo="Rota", eje="x", peso=1.0, descripcion="",
                            version="1", objeto=Rota())
    check = sonda.correr("demo", tmp_path)
    assert [s.veredicto for s in check.subchecks] == [Veredicto.NO_MEDIBLE]
    assert "RuntimeError" in check.subchecks[0].motivo


@pytest.mark.parametrize("id_sonda", sorted(REGISTRO))
def test_sujeto_ilegible_es_todo_no_medible(id_sonda: str, tmp_path: Path) -> None:
    check = REGISTRO[id_sonda]().evaluar(Contexto(ruta_repo=tmp_path / "no-existe", nombre_sujeto="demo"))
    assert check.subchecks
    assert {s.veredicto for s in check.subchecks} == {Veredicto.NO_MEDIBLE}
    assert all(s.motivo for s in check.subchecks)


@pytest.mark.parametrize("id_sonda", sorted(REGISTRO))
def test_un_repositorio_vacio_no_aprueba_nada(id_sonda: str, tmp_path: Path) -> None:
    """Ninguna sonda da CUMPLE por no haber encontrado nada."""
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    check = REGISTRO[id_sonda]().evaluar(Contexto(ruta_repo=vacio, nombre_sujeto="vacio"))
    assert check.subchecks
    assert Veredicto.CUMPLE not in {s.veredicto for s in check.subchecks}


def test_el_readme_documenta_cada_sonda_registrada() -> None:
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    filas = [l for l in texto.splitlines() if l.startswith("|")]
    documentadas = {m for fila in filas for m in re.findall(r"`([a-z0-9.-]+)`", fila)}
    faltantes = sorted(set(REGISTRO) - documentadas)
    assert not faltantes, f"sondas registradas sin fila en el README: {faltantes}"


def test_la_version_declarada_es_una_sola() -> None:
    proyecto = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert proyecto["version"] == baremo.__version__
