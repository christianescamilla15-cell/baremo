"""Sonda `entrega.check-que-analiza`: los escaneos prueban que analizaron algo."""
from __future__ import annotations

from baremo.model import Veredicto
from conftest import medir, por_sujeto, texto_de

ANALISIS = "entrega.check-que-analiza"

SEGURIDAD = """name: seguridad
on: [push]
jobs:
  confidencialidad:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python herramientas/confidencialidad.py
  semgrep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: semgrep scan --config p/default --error --json-output=semgrep.json
      - name: probar que analizó archivos
        run: python3 herramientas/verificar_reportes.py semgrep semgrep.json
  secretos:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: gitleaks/gitleaks-action@v2
  codeql:
    runs-on: ubuntu-latest
    steps:
      - uses: github/codeql-action/init@v3
      - uses: github/codeql-action/analyze@v3
  sbom:
    runs-on: ubuntu-latest
    steps:
      - uses: anchore/sbom-action@v0
        with:
          output-file: sbom.spdx.json
      - run: python3 herramientas/verificar_reportes.py sbom sbom.spdx.json || true
"""


def test_un_subcheck_por_job_que_escanea(repo) -> None:
    check = medir(ANALISIS, repo({".github/workflows/seguridad.yml": SEGURIDAD,
                                  ".github/workflows/ci.yml": "jobs:\n  p:\n    steps:\n      - run: pytest\n"}))
    assert por_sujeto(check) == {
        "demo/job:.github/workflows/seguridad.yml#confidencialidad": Veredicto.CUMPLE,
        "demo/job:.github/workflows/seguridad.yml#semgrep": Veredicto.CUMPLE,
        "demo/job:.github/workflows/seguridad.yml#secretos": Veredicto.NO_CUMPLE,
        "demo/job:.github/workflows/seguridad.yml#codeql": Veredicto.CUMPLE,
        # «|| true» convierte la verificación en decoración: no cuenta.
        "demo/job:.github/workflows/seguridad.yml#sbom": Veredicto.NO_CUMPLE,
    }
    assert "gitleaks sin verificación de su reporte" in texto_de(check)


def test_verificacion_en_el_mismo_paso_con_grep_cuenta(repo) -> None:
    flujo = """jobs:
  secretos:
    steps:
      - shell: bash
        run: |
          ./gitleaks git --redact -v 2>&1 | tee gitleaks.log
          grep -Eq '[1-9][0-9]* commits scanned' gitleaks.log
"""
    check = medir(ANALISIS, repo({".github/workflows/s.yml": flujo}))
    assert check.subchecks[0].veredicto is Veredicto.CUMPLE
    assert "grep -Eq" in check.subchecks[0].evidencias[0].extracto


def test_escaneo_desde_una_imagen_con_etiqueta_se_reconoce(repo) -> None:
    flujo = """jobs:
  secretos:
    steps:
      - run: docker run --rm -v "$PWD:/repo" ghcr.io/gitleaks/gitleaks:v8.21.2 git /repo 2>&1 | tee gitleaks.log
"""
    check = medir(ANALISIS, repo({".github/workflows/s.yml": flujo}))
    assert por_sujeto(check) == {"demo/job:.github/workflows/s.yml#secretos": Veredicto.NO_CUMPLE}


def test_verificacion_que_puede_no_fallar_no_cuenta(repo) -> None:
    flujo = """jobs:
  trivy:
    steps:
      - uses: aquasecurity/trivy-action@0.28.0
        with: {scan-type: fs, format: json, output: trivy.json}
      - run: python3 herramientas/verificar_reportes.py trivy trivy.json
        continue-on-error: true
"""
    assert medir(ANALISIS, repo({".github/workflows/t.yml": flujo})).subchecks[0].veredicto is Veredicto.NO_CUMPLE


def test_sin_escaneos_es_no_medible(repo) -> None:
    check = medir(ANALISIS, repo({".github/workflows/ci.yml": "jobs:\n  p:\n    steps:\n      - run: pytest\n"}))
    assert por_sujeto(check) == {"demo/pipeline:escaneos": Veredicto.NO_MEDIBLE}


def test_sin_flujos_es_no_medible(repo) -> None:
    check = medir(ANALISIS, repo({"README.md": "# x\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
    assert "No hay flujos" in check.subchecks[0].motivo


def test_flujo_de_otra_forja_es_no_medible_y_lo_dice(repo) -> None:
    check = medir(ANALISIS, repo({".gitlab-ci.yml": "sast:\n  script: semgrep scan\n"}))
    assert "otra forja" in check.subchecks[0].motivo


def test_flujo_invalido_es_no_medible(repo) -> None:
    check = medir(ANALISIS, repo({".github/workflows/roto.yml": "jobs: [\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
    assert "no es YAML válido" in check.subchecks[0].motivo
