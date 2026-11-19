"""Paridad contra un oráculo (N08b): el informe de un repositorio fijo coincide con el golden.

`tests/golden/informe_repo_golden.json` guarda, para un repositorio de ejemplo construido
aquí mismo, el veredicto de CADA sub-check (por id y sujeto) y los dos números. Se revisó
a mano contra el repositorio: cada veredicto se puede justificar leyendo los archivos de
REPOSITORIO. Cualquier cambio de una sonda que mueva un veredicto rompe esta prueba, y la
diferencia se imprime sub-check por sub-check para clasificarla como mejora o defecto.

El listón no es «pasa»: es el CONTROL NEGATIVO. La segunda prueba altera un solo archivo
del repositorio y exige que la comparación lo detecte; un oráculo que no detecta nada no
es un oráculo.

Regenerar (sólo tras clasificar cada diferencia): BAREMO_REGENERAR_GOLDEN=1 pytest
tests/test_paridad_golden.py — la prueba falla a propósito para que el diff se revise.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from baremo.cli import main
from conftest import construir

GOLDEN = Path(__file__).parent / "golden" / "informe_repo_golden.json"

ADR = """# ADR 0001 · Usar SQLite

- Estado: aceptada

## Contexto
El servicio guarda saldos de una sola sucursal y corre en una sola máquina.

## Decisión
Usamos SQLite en modo WAL como único almacenamiento del servicio.

## Consecuencias
No hay servidor de base de datos que operar; escalar a varias sucursales exigirá migrar.
"""

REPOSITORIO: dict[str, str] = {
    ".gitignore": "node_modules/\n__pycache__/\ndist/\n.env\n",
    "README.md": (
        "[![ci](https://github.com/x/repo-golden/actions/workflows/ci.yml/badge.svg)](https://x)\n\n"
        "# Saldos\n\nServicio de saldos por sucursal.\n\n"
        "## Cómo ejecutar\n```bash\npip install -e .\n```\n\n"
        "## Pruebas\n```bash\npytest -q\n```\n\n## Licencia\nMIT.\n"
    ),
    "LICENSE": ("MIT License\n\nCopyright (c) 2026 Ana Pérez\n\nPermission is hereby granted, free of "
                "charge, to any person obtaining a copy. The above copyright notice and this permission "
                "notice shall be included in all copies.\n"),
    "pyproject.toml": '[project]\nname = "saldos"\nversion = "1.0.0"\nlicense = "MIT"\n',
    "SECURITY.md": "# Seguridad\n\nEscribe a seguridad@saldos.dev con el asunto «Seguridad: <proyecto>».\n",
    "docs/adr/0001-usar-sqlite.md": ADR,
    "docs/arquitectura/README.md": (
        "# Arquitectura\n\n```mermaid\nC4Context\n  Person(cajero, \"Cajero\")\n"
        "  System(saldos, \"Saldos\", \"Calcula saldos\")\n  Rel(cajero, saldos, \"Consulta\")\n```\n\n"
        "```mermaid\nC4Container\n  System_Boundary(b, \"<proyecto>\") {\n"
        "    Container(api, \"API\", \"Python\", \"…\")\n  }\n```\n"
    ),
    "openapi.yaml": (
        "openapi: 3.0.3\ninfo: {title: Saldos, version: 1.0.0}\npaths:\n  /saldo:\n    get:\n"
        "      summary: Saldo actual\n      responses:\n        '200':\n          description: Saldo\n"
        "          content:\n            application/json:\n              schema: {type: number}\n"
        "    post:\n      summary: Ajusta el saldo\n      responses:\n        '200': {}\n"
    ),
    "src/app.py": "def sumar(a, b):\n    return a + b\n",
    "tests/test_app.py": (
        "import json\nimport pytest\nfrom pathlib import Path\nfrom src.app import sumar\n\n"
        "def test_suma():\n    assert sumar(1, 1) == 2\n\n"
        "def test_saldo_igual_al_oraculo():\n"
        "    assert sumar(2, 3) == json.loads(Path('tests/golden/saldo.json').read_text())\n\n"
        "@pytest.mark.skip(reason='pendiente')\ndef test_saltada():\n    assert False\n"
    ),
    "tests/golden/saldo.json": "5\n",
    "docs/reglas.md": (
        "# Reglas\n\n| Regla | Descripción | Prueba |\n|---|---|---|\n"
        "| R1 | Suma de saldos | `tests/test_app.py::test_suma` |\n"
        "| R2 | Saldo negativo bloquea | `tests/test_app.py::test_saltada` |\n"
    ),
    ".github/workflows/ci.yml": (
        "name: ci\non: [push]\njobs:\n  pruebas:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - uses: actions/checkout@v4\n      - run: pytest -q\n"
        "      - run: semgrep scan --config p/default --error\n"
    ),
    "Dockerfile": "FROM python:3.12-slim\nHEALTHCHECK CMD python -c 'print(1)'\nUSER app\n",
}


def normalizar(informe: dict[str, Any]) -> dict[str, Any]:
    """Lo que el oráculo fija: veredicto por (sub-check, sujeto) y los dos números."""
    resumen = informe["resumen"]
    return {
        "resumen": {
            "cumplimiento": round(resumen["cumplimiento_calculado"], 4),
            "cobertura": round(resumen["cobertura"], 4),
            "publicable": resumen["publicable"],
            "totales": resumen["totales"],
        },
        "veredictos": {
            check["id"]: {f'{s["id"]} @ {s["sujeto"]}': s["veredicto"] for s in check["subchecks"]}
            for check in informe["checks"]
        },
    }


def diferencias(obtenido: dict[str, Any], esperado: dict[str, Any]) -> list[str]:
    salida: list[str] = []
    for clave in sorted(set(obtenido["resumen"]) | set(esperado["resumen"])):
        if obtenido["resumen"].get(clave) != esperado["resumen"].get(clave):
            salida.append(f"resumen.{clave}: esperado {esperado['resumen'].get(clave)!r}, "
                          f"obtenido {obtenido['resumen'].get(clave)!r}")
    for check in sorted(set(obtenido["veredictos"]) | set(esperado["veredictos"])):
        uno = obtenido["veredictos"].get(check, {})
        otro = esperado["veredictos"].get(check, {})
        for sub in sorted(set(uno) | set(otro)):
            if uno.get(sub) != otro.get(sub):
                salida.append(f"{check} · {sub}: esperado {otro.get(sub)}, obtenido {uno.get(sub)}")
    return salida


def _informe(tmp_path: Path, archivos: dict[str, str]) -> dict[str, Any]:
    raiz = construir(tmp_path / "repo-golden", archivos)
    destino = tmp_path / "informe.json"
    main(["evaluar", str(raiz), "--formato", "json", "--salida", str(destino), "--hoy", "2026-11-19"])
    return normalizar(json.loads(destino.read_text(encoding="utf-8")))


def test_el_informe_coincide_con_el_oraculo(tmp_path: Path) -> None:
    obtenido = _informe(tmp_path, REPOSITORIO)
    if os.environ.get("BAREMO_REGENERAR_GOLDEN") == "1":
        GOLDEN.write_text(json.dumps(obtenido, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")
        pytest.fail("golden regenerado: revisa y clasifica el diff antes de versionarlo")
    esperado = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert diferencias(obtenido, esperado) == []


def test_control_negativo_el_oraculo_detecta_un_solo_cambio(tmp_path: Path) -> None:
    esperado = json.loads(GOLDEN.read_text(encoding="utf-8"))
    alterado = dict(REPOSITORIO)
    alterado["docs/adr/0001-usar-sqlite.md"] = ADR.split("## Consecuencias")[0]
    difs = diferencias(_informe(tmp_path, alterado), esperado)
    assert any(d.startswith("documentacion.adr · ADR_COMPLETO @ repo-golden/adr:0001-usar-sqlite")
               for d in difs), difs
