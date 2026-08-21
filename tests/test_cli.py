"""Pruebas de la CLI de Baremo.

Se prueba lo que define al producto, no la fontaneria:
  · `baremo sondas` enseña el registro (y dice claramente cuando esta vacio);
  · `baremo evaluar --formato json` produce un informe con el esquema estable;
  · el codigo de salida es 2 cuando la cobertura no alcanza el umbral — un informe
    que no midio no puede "pasar" en silencio con un 0.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:  # permite correr pytest desde cualquier directorio
    sys.path.insert(0, str(RAIZ))

from baremo.cli import (  # noqa: E402
    SALIDA_BAJO_MINIMO,
    SALIDA_NO_PUBLICABLE,
    SALIDA_OK,
    descubrir_sondas,
    main,
)
from baremo.report import ESQUEMA, ESQUEMA_VERSION  # noqa: E402

LLAVES_RAIZ = {
    "esquema",
    "esquema_version",
    "manifiesto",
    "alcance",
    "resumen",
    "checks",
    "supresiones",
}
LLAVES_ALCANCE = {"declarado", "medido", "excluido", "omitido_sin_declarar"}
LLAVES_RESUMEN = {
    "cumplimiento",
    "cobertura",
    "umbral_cobertura",
    "publicable",
    "motivo_retencion",
    "totales",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Un sujeto plausible: algo de codigo, pruebas, pipeline y contenedor."""
    raiz = tmp_path / "repo-medido"
    (raiz / "src").mkdir(parents=True)
    (raiz / "tests").mkdir()
    (raiz / ".github" / "workflows").mkdir(parents=True)
    (raiz / "README.md").write_text("# repo-medido\n", encoding="utf-8")
    (raiz / "src" / "app.py").write_text("def sumar(a, b):\n    return a + b\n", encoding="utf-8")
    (raiz / "tests" / "test_app.py").write_text(
        "from src.app import sumar\n\n\ndef test_sumar():\n    assert sumar(1, 1) == 2\n",
        encoding="utf-8",
    )
    (raiz / ".github" / "workflows" / "ci.yml").write_text(
        "name: ci\non: [push]\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (raiz / "Dockerfile").write_text("FROM python:3.12-slim\n", encoding="utf-8")
    return raiz


def _evaluar_json(destino: Path, *extra: str) -> tuple[int, dict]:
    codigo = main(["evaluar", *extra, "--formato", "json", "--salida", str(destino)])
    return codigo, json.loads(destino.read_text(encoding="utf-8"))


def test_sondas_lista_el_registro(capsys: pytest.CaptureFixture[str]) -> None:
    codigo = main(["sondas"])
    salida = capsys.readouterr().out

    assert codigo == SALIDA_OK
    sondas = descubrir_sondas()
    if sondas:
        for cabecera in ("SONDA", "EJE", "PESO"):
            assert cabecera in salida
        for sonda in sondas:
            assert sonda.id in salida, f"la sonda {sonda.id} no aparece en el listado"
            assert sonda.eje in salida
        assert f"{len(sondas)} sonda(s) registrada(s)." in salida
    else:
        # Sin sondas el registro esta vacio, y hay que DECIRLO: no fingir un informe.
        assert "No hay sondas registradas" in salida


def test_evaluar_produce_json_con_el_esquema_esperado(repo: Path, tmp_path: Path) -> None:
    destino = tmp_path / "informe.json"
    codigo, datos = _evaluar_json(destino, str(repo))

    assert codigo in (SALIDA_OK, SALIDA_BAJO_MINIMO, SALIDA_NO_PUBLICABLE)
    assert LLAVES_RAIZ <= set(datos)
    assert datos["esquema"] == ESQUEMA
    assert datos["esquema_version"] == ESQUEMA_VERSION
    assert LLAVES_ALCANCE <= set(datos["alcance"])
    assert LLAVES_RESUMEN <= set(datos["resumen"])
    assert repo.name in datos["alcance"]["medido"]

    # El manifiesto es parte del informe, no un adorno: identifica con que se midio.
    manifiesto = datos["manifiesto"]
    assert manifiesto["herramienta"] == "baremo"
    assert manifiesto["version"]
    assert manifiesto["generado_en"]
    assert f"sujeto:{repo.name}" in manifiesto["hashes"]

    # Las supresiones siempre viajan en el informe, aunque no haya ninguna.
    assert set(datos["supresiones"]) == {"aplicadas", "vencidas", "sin_efecto"}

    # Cada sub-check reportado trae su veredicto y sus evidencias.
    for check in datos["checks"]:
        assert {"id", "titulo", "eje", "peso", "cumplimiento", "cobertura", "subchecks"} <= set(check)
        for sub in check["subchecks"]:
            assert {"id", "veredicto", "motivo", "evidencias", "sujeto"} <= set(sub)


def test_salida_2_cuando_la_cobertura_no_alcanza_el_umbral(repo: Path, tmp_path: Path) -> None:
    """Declarar tres sujetos y medir uno NO puede salir con 0."""
    config = tmp_path / "baremo.yml"
    config.write_text(
        "alcance:\n"
        "  declarado:\n"
        f"    - {repo.name}\n"
        "    - servicio-sin-medir-a\n"
        "    - servicio-sin-medir-b\n",
        encoding="utf-8",
    )
    destino = tmp_path / "informe.json"
    codigo, datos = _evaluar_json(
        destino, str(repo), "--config", str(config), "--umbral-cobertura", "1.0",
    )

    assert codigo == SALIDA_NO_PUBLICABLE
    resumen = datos["resumen"]
    assert resumen["publicable"] is False
    assert resumen["cumplimiento"] is None          # retenido, no sustituido por un 0
    assert resumen["motivo_retencion"]              # y se dice por que
    assert datos["alcance"]["omitido_sin_declarar"] == [
        "servicio-sin-medir-a",
        "servicio-sin-medir-b",
    ]


def test_el_informe_de_texto_dice_retenido_y_es_ascii(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "baremo.yml"
    config.write_text(
        f"alcance:\n  declarado: [{repo.name}, servicio-sin-medir]\n", encoding="utf-8"
    )
    codigo = main(
        ["evaluar", str(repo), "--config", str(config), "--umbral-cobertura", "1.0", "--sin-color"]
    )
    salida = capsys.readouterr().out

    assert codigo == SALIDA_NO_PUBLICABLE
    assert "RETENIDO" in salida
    assert "COBERTURA" in salida
    assert "OMITIDO SIN DECLARAR" in salida
    assert "servicio-sin-medir" in salida
    salida.encode("ascii")                          # el informe de consola es ASCII puro
    assert "\033[" not in salida                    # --sin-color desactiva los colores
