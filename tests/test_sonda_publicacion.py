"""Sondas de publicación (N11): README estándar, licencia y política de seguridad."""
from __future__ import annotations

from baremo.model import Veredicto
from conftest import BINARIO, medir, por_sujeto, texto_de

README = "documentacion.readme-estandar"
LICENCIA = "documentacion.licencia"
POLITICA = "documentacion.politica-de-seguridad"

FLUJO_CI = "name: ci\non: [push]\njobs:\n  p:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest -q\n"
FLUJO_SEGURIDAD = ("name: seguridad\non: [push]\njobs:\n  c:\n    runs-on: ubuntu-latest\n    steps:\n"
                   "      - uses: github/codeql-action/analyze@v3\n")
INSIGNIAS = (
    "[![ci](https://github.com/x/demo/actions/workflows/ci.yml/badge.svg)](https://github.com/x/demo)\n"
    "[![seguridad](https://github.com/x/demo/actions/workflows/seguridad.yml/badge.svg)](https://x)\n"
)
README_COMPLETO = INSIGNIAS + """
# Demo

## Arquitectura
Ver [el modelo C4](docs/arquitectura/README.md).

## Cómo ejecutar
```bash
pip install -e .
```

## Pruebas
Se corren con `pytest -q`; el mapa regla → prueba está en [docs/reglas.md](docs/reglas.md).

## Seguridad
Ver [SECURITY.md](SECURITY.md).

## Licencia
MIT, ver [LICENSE](LICENSE).
"""
ARCHIVOS_COMPLETOS = {
    "README.md": README_COMPLETO,
    ".github/workflows/ci.yml": FLUJO_CI,
    ".github/workflows/seguridad.yml": FLUJO_SEGURIDAD,
    "docs/arquitectura/README.md": "# Arquitectura\n",
    "docs/reglas.md": "# Reglas\n",
    "SECURITY.md": "# Seguridad\n",
    "LICENSE": "MIT License\n",
}

MIT = """MIT License

Copyright (c) 2026 Ana Pérez

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction. The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
"""

# ------------------------------------------------------------------- README estándar

def test_readme_completo_cumple_los_siete_elementos(repo) -> None:
    check = medir(README, repo(ARCHIVOS_COMPLETOS))
    assert len(check.subchecks) == 7
    assert set(por_sujeto(check).values()) == {Veredicto.CUMPLE}


def test_insignia_que_apunta_a_un_flujo_inexistente_no_cumple(repo) -> None:
    archivos = dict(ARCHIVOS_COMPLETOS)
    del archivos[".github/workflows/seguridad.yml"]
    check = medir(README, repo(archivos))
    assert por_sujeto(check)["demo/readme:insignia-seguridad"] is Veredicto.NO_CUMPLE
    assert "no existe" in texto_de(check)


def test_insignia_de_ci_cuyo_flujo_no_corre_pruebas_no_cumple(repo) -> None:
    archivos = dict(ARCHIVOS_COMPLETOS, **{".github/workflows/ci.yml": "jobs:\n  a:\n    steps:\n      - run: echo hola\n"})
    assert por_sujeto(medir(README, repo(archivos)))["demo/readme:insignia-ci"] is Veredicto.NO_CUMPLE


def test_seccion_que_enlaza_a_un_documento_inexistente_no_cumple(repo) -> None:
    archivos = dict(ARCHIVOS_COMPLETOS)
    del archivos["docs/arquitectura/README.md"]
    check = medir(README, repo(archivos))
    assert por_sujeto(check)["demo/readme:arquitectura"] is Veredicto.NO_CUMPLE
    assert "la sección existe" in texto_de(check)


def test_aprueban_no_es_una_seccion_de_pruebas(repo) -> None:
    """Regresión: «pruebas?» sin límite de palabra casaba con «aprueban»."""
    archivos = dict(ARCHIVOS_COMPLETOS, **{"README.md": "# x\n\n## Ante la duda aprueban\nTexto.\n"})
    check = medir(README, repo(archivos))
    assert por_sujeto(check)["demo/readme:pruebas"] is Veredicto.NO_CUMPLE
    assert "ninguno de pruebas" in texto_de(check)


def test_sin_readme_cada_elemento_no_cumple(repo) -> None:
    check = medir(README, repo({"src/app.py": "x = 1\n"}))
    assert len(check.subchecks) == 7
    assert set(por_sujeto(check).values()) == {Veredicto.NO_CUMPLE}


def test_readme_ilegible_es_no_medible(repo) -> None:
    check = medir(README, repo({"README.md": BINARIO}))
    assert set(por_sujeto(check).values()) == {Veredicto.NO_MEDIBLE}


# ------------------------------------------------------------------- licencia

def test_licencia_mit_con_titular_y_manifiestos_coherentes_cumple(repo) -> None:
    raiz = repo({
        "LICENSE": MIT,
        "pyproject.toml": '[project]\nname = "demo"\nlicense = "MIT"\n',
        "web/package.json": '{"name": "web", "license": "MIT"}',
        "tests/fixtures/pyproject.toml": '[project]\nname = "otro"\n',   # no es un paquete
    })
    assert por_sujeto(medir(LICENCIA, raiz)) == {
        "demo/licencia:archivo": Veredicto.CUMPLE,
        "demo/licencia:pyproject.toml": Veredicto.CUMPLE,
        "demo/licencia:web/package.json": Veredicto.CUMPLE,
    }


def test_licencia_de_plantilla_sin_titular_no_cumple(repo) -> None:
    plantilla = MIT.replace("Copyright (c) 2026 Ana Pérez", "Copyright (c) [year] [fullname]")
    check = medir(LICENCIA, repo({"LICENSE": plantilla}))
    assert por_sujeto(check)["demo/licencia:archivo"] is Veredicto.NO_CUMPLE


def test_manifiesto_con_otra_licencia_no_cumple(repo) -> None:
    raiz = repo({"LICENSE": MIT, "pyproject.toml": '[project]\nname = "d"\nlicense = "Apache-2.0"\n'})
    assert por_sujeto(medir(LICENCIA, raiz))["demo/licencia:pyproject.toml"] is Veredicto.NO_CUMPLE


def test_manifiesto_sin_licencia_no_cumple_y_privado_no_es_sujeto(repo) -> None:
    raiz = repo({"LICENSE": MIT, "pyproject.toml": '[project]\nname = "d"\n',
                 "web/package.json": '{"name": "web", "private": true}'})
    assert por_sujeto(medir(LICENCIA, raiz)) == {
        "demo/licencia:archivo": Veredicto.CUMPLE,
        "demo/licencia:pyproject.toml": Veredicto.NO_CUMPLE,
    }


def test_licencia_por_cabecera_spdx(repo) -> None:
    raiz = repo({"LICENSE": "SPDX-License-Identifier: MPL-2.0\n\nTexto completo...\n",
                 "Cargo.toml": '[package]\nname = "d"\nlicense = "MPL-2.0"\n'})
    assert set(por_sujeto(medir(LICENCIA, raiz)).values()) == {Veredicto.CUMPLE}


def test_licencia_no_reconocida_es_no_medible(repo) -> None:
    raiz = repo({"LICENSE": "Todos los derechos reservados, salvo acuerdo.\n",
                 "pyproject.toml": '[project]\nname = "d"\nlicense = "MIT"\n'})
    assert set(por_sujeto(medir(LICENCIA, raiz)).values()) == {Veredicto.NO_MEDIBLE}


def test_sin_licencia_no_cumple(repo) -> None:
    check = medir(LICENCIA, repo({"README.md": "# x\n"}))
    assert por_sujeto(check) == {"demo/licencia:archivo": Veredicto.NO_CUMPLE}


# ------------------------------------------------------------------- política de seguridad

POLITICA_BUENA = """# Seguridad

Escribe a seguridad@demo.dev con el asunto «Seguridad: Demo». Respondo en 72 horas hábiles.
"""


def test_politica_con_canal_plazo_y_adaptada_cumple(repo) -> None:
    check = medir(POLITICA, repo({"SECURITY.md": POLITICA_BUENA}))
    assert por_sujeto(check) == {
        "demo/politica:canal": Veredicto.CUMPLE,
        "demo/politica:plazo": Veredicto.CUMPLE,
        "demo/politica:adaptada": Veredicto.CUMPLE,
    }


def test_politica_copiada_de_la_plantilla_no_cumple(repo) -> None:
    plantilla = POLITICA_BUENA.replace("«Seguridad: Demo»", "«Seguridad: <proyecto>»")
    check = medir(POLITICA, repo({".github/SECURITY.md": plantilla}))
    assert por_sujeto(check)["demo/politica:adaptada"] is Veredicto.NO_CUMPLE
    assert "<proyecto>" in texto_de(check)


def test_politica_con_correo_de_ejemplo_y_sin_plazo_no_cumple(repo) -> None:
    check = medir(POLITICA, repo({"SECURITY.md": "# Seguridad\nAbre un issue o escribe a security@example.com.\n"}))
    veredictos = por_sujeto(check)
    assert veredictos["demo/politica:canal"] is Veredicto.NO_CUMPLE
    assert veredictos["demo/politica:plazo"] is Veredicto.NO_CUMPLE


def test_politica_con_avisos_privados_de_la_forja_cumple_el_canal(repo) -> None:
    texto = "# Security\nReport at https://github.com/x/demo/security/advisories/new within 5 days.\n"
    assert por_sujeto(medir(POLITICA, repo({"SECURITY.md": texto})))["demo/politica:canal"] is Veredicto.CUMPLE


def test_sin_politica_tres_no_cumple(repo) -> None:
    assert set(por_sujeto(medir(POLITICA, repo({"README.md": "# x\n"}))).values()) == {Veredicto.NO_CUMPLE}


def test_politica_ilegible_es_no_medible(repo) -> None:
    assert set(por_sujeto(medir(POLITICA, repo({"SECURITY.md": BINARIO}))).values()) == {Veredicto.NO_MEDIBLE}
