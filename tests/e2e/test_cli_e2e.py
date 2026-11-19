"""Extremo a extremo: Baremo como lo usa un pipeline, en un proceso aparte.

Nada de importar `main`: se ejecuta `python -m baremo.cli` con un entorno limpio
(HOME temporal y sin CONFIDENCIAL_TERMINOS), sobre un repositorio construido en un
directorio temporal, y se afirma sobre lo que el pipeline ve: el código de salida, el
informe escrito y la salida de consola.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from baremo.probes import REGISTRO

RAIZ = Path(__file__).resolve().parents[2]


def _baremo(*args: str, hogar: Path) -> subprocess.CompletedProcess[str]:
    entorno = {k: v for k, v in os.environ.items() if k != "CONFIDENCIAL_TERMINOS"}
    entorno.update({"HOME": str(hogar), "PYTHONPATH": str(RAIZ), "NO_COLOR": "1"})
    return subprocess.run([sys.executable, "-m", "baremo.cli", *args], capture_output=True,
                          text=True, env=entorno, cwd=hogar, timeout=120, check=False)


@pytest.fixture
def sujeto(tmp_path: Path) -> Path:
    raiz = tmp_path / "servicio"
    for relativa, contenido in {
        "README.md": "# Servicio\n\n## Cómo ejecutar\n```bash\npip install -e .\n```\n",
        "LICENSE": "SPDX-License-Identifier: MIT\n",
        "src/app.py": "def sumar(a, b):\n    return a + b\n",
        "tests/test_app.py": "from src.app import sumar\n\ndef test_sumar():\n    assert sumar(1, 1) == 2\n",
        ".github/workflows/ci.yml": "jobs:\n  p:\n    steps:\n      - uses: actions/checkout@v4\n      - run: pytest\n",
    }.items():
        (raiz / relativa).parent.mkdir(parents=True, exist_ok=True)
        (raiz / relativa).write_text(contenido, encoding="utf-8")
    return raiz


def test_evaluar_escribe_un_informe_publicable_con_todas_las_sondas(sujeto: Path, tmp_path: Path) -> None:
    informe = tmp_path / "informe.json"
    proceso = _baremo("evaluar", str(sujeto), "--umbral-cobertura", "0.5", "--formato", "json",
                      "--salida", str(informe), hogar=tmp_path)
    assert proceso.returncode == 0, proceso.stderr
    datos = json.loads(informe.read_text(encoding="utf-8"))
    assert datos["resumen"]["publicable"] is True
    assert {s["id"] for s in datos["manifiesto"]["sondas"]} == set(REGISTRO)
    # Sin lista de términos en el entorno, la confidencialidad NO se aprueba: es NO_MEDIBLE.
    conf = next(c for c in datos["checks"] if c["id"] == "seguridad.confidencialidad")
    assert [s["veredicto"] for s in conf["subchecks"]] == ["NO_MEDIBLE"]


def test_un_alcance_sin_medir_sale_con_2_y_dice_retenido(sujeto: Path, tmp_path: Path) -> None:
    config = tmp_path / "baremo.yml"
    config.write_text("alcance:\n  declarado: [servicio, otro-sin-medir]\n", encoding="utf-8")
    proceso = _baremo("evaluar", str(sujeto), "--config", str(config), "--umbral-cobertura", "1.0",
                      "--sin-color", hogar=tmp_path)
    assert proceso.returncode == 2
    assert "RETENIDO" in proceso.stdout
    assert "otro-sin-medir" in proceso.stdout


def test_sondas_lista_el_catalogo_completo(tmp_path: Path) -> None:
    proceso = _baremo("sondas", hogar=tmp_path)
    assert proceso.returncode == 0
    for id_sonda in REGISTRO:
        assert id_sonda in proceso.stdout
    assert f"{len(REGISTRO)} sonda(s) registrada(s)." in proceso.stdout


def test_explicar_un_subcheck_nuevo(tmp_path: Path) -> None:
    proceso = _baremo("explicar", "C4_NIVEL", hogar=tmp_path)
    assert proceso.returncode == 0
    assert "documentacion.arquitectura-c4" in proceso.stdout
    assert "NO_MEDIBLE" in proceso.stdout


def test_un_error_de_operacion_sale_con_3(tmp_path: Path) -> None:
    proceso = _baremo("evaluar", str(tmp_path / "no-existe"), hogar=tmp_path)
    assert proceso.returncode == 3
    assert "no existen" in proceso.stderr
