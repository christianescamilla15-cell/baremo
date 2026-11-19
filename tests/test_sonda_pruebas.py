"""Sondas `pruebas.e2e-presente` (N08), `pruebas.paridad-golden` (N08b) y
`pruebas.regla-por-prueba` (N03)."""
from __future__ import annotations

import pytest

import baremo.probes
from baremo.model import Veredicto
from conftest import BINARIO, medir, por_sujeto, texto_de

E2E = "pruebas.e2e-presente"
GOLDEN = "pruebas.paridad-golden"
REGLAS = "pruebas.regla-por-prueba"

# ------------------------------------------------------------------- E2E

E2E_CLI = """import subprocess, sys

def test_el_programa_responde():
    salida = subprocess.run([sys.executable, "-m", "demo", "--version"], capture_output=True)
    assert salida.returncode == 0
"""
E2E_WEB = """import { test, expect } from '@playwright/test';
test('el contador inicia sesión', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('heading')).toHaveText('Bienvenido');
});
"""


def test_e2e_que_ejerce_y_afirma_cumple(repo) -> None:
    raiz = repo({"tests/e2e/test_cli.py": E2E_CLI, "e2e/login.spec.ts": E2E_WEB,
                 "e2e/paginas/login.ts": "export const usuario = 'x';\n",   # apoyo: no es sujeto
                 "playwright.config.ts": "export default {};\n"})
    assert por_sujeto(medir(E2E, raiz)) == {
        "demo/e2e:e2e/login.spec.ts": Veredicto.CUMPLE,
        "demo/e2e:tests/e2e/test_cli.py": Veredicto.CUMPLE,
    }


def test_e2e_que_recorre_sin_afirmar_no_cumple(repo) -> None:
    sin_afirmar = "test('recorre', async ({ page }) => {\n  await page.goto('/');\n});\n"
    check = medir(E2E, repo({"e2e/recorrido.spec.ts": sin_afirmar}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "no afirma nada" in texto_de(check)


def test_e2e_que_no_sale_del_proceso_no_cumple(repo) -> None:
    unitaria = "from demo import sumar\n\ndef test_suma():\n    assert sumar(1, 1) == 2\n"
    check = medir(E2E, repo({"tests/test_suma_e2e.py": unitaria}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "no ejerce el sistema desde fuera" in texto_de(check)


def test_escenario_gherkin_cumple(repo) -> None:
    escenario = "Feature: Alta\n  Scenario: alta correcta\n    Given un contador\n    When registra\n    Then ve su folio\n"
    assert medir(E2E, repo({"features/alta.feature": escenario})).subchecks[0].veredicto is Veredicto.CUMPLE


def test_solo_configuracion_e2e_no_cumple(repo) -> None:
    check = medir(E2E, repo({"playwright.config.ts": "export default {};\n"}))
    assert por_sujeto(check) == {"demo/e2e:suite": Veredicto.NO_CUMPLE}
    assert "playwright.config.ts" in texto_de(check)


def test_e2e_ilegible_es_no_medible(repo) -> None:
    assert medir(E2E, repo({"e2e/flujo.spec.ts": BINARIO})).subchecks[0].veredicto is Veredicto.NO_MEDIBLE


def test_sin_e2e_y_barrido_truncado_es_no_medible(repo, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = repo({"a.txt": "a", "b.txt": "b"})
    monkeypatch.setattr(baremo.probes, "LIMITE_ARCHIVOS", 1)
    assert medir(E2E, raiz).subchecks[0].veredicto is Veredicto.NO_MEDIBLE


# ------------------------------------------------------------------- golden

PARIDAD = """import json
from pathlib import Path

GOLDEN = Path(__file__).parent / "golden" / "lote_0001.json"

def test_lote_igual_al_oraculo():
    assert calcular_lote() == json.loads(GOLDEN.read_text())
"""


def test_golden_comparado_por_una_prueba_cumple(repo) -> None:
    raiz = repo({"tests/golden/lote_0001.json": "{}", "tests/test_paridad.py": PARIDAD})
    check = medir(GOLDEN, raiz)
    assert por_sujeto(check) == {"demo/golden:tests/golden/lote_0001.json": Veredicto.CUMPLE}
    assert check.subchecks[0].evidencias[1].detalle.endswith("compara por igualdad")


def test_golden_comparado_por_carpeta_cumple(repo) -> None:
    por_carpeta = ('import pathlib\n\ndef test_todos():\n    for f in pathlib.Path("oraculo").glob("*.csv"):\n'
                   '        assert procesar(f) == esperado(f)\n')
    raiz = repo({"tests/oraculo/a.csv": "1", "tests/oraculo/b.csv": "2", "tests/test_lotes.py": por_carpeta})
    assert set(por_sujeto(medir(GOLDEN, raiz)).values()) == {Veredicto.CUMPLE}


def test_golden_huerfano_no_cumple(repo) -> None:
    check = medir(GOLDEN, repo({"tests/golden/lote_0002.json": "{}", "tests/test_x.py": "def test_x():\n    assert True\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "oráculo huérfano" in texto_de(check)


def test_golden_nombrado_sin_comparar_no_cumple(repo) -> None:
    solo_lee = 'def test_existe():\n    abrir("tests/golden/lote_0003.json")\n'
    check = medir(GOLDEN, repo({"tests/golden/lote_0003.json": "{}", "tests/test_y.py": solo_lee}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "sin comparar por igualdad" in texto_de(check)


def test_sin_golden_no_cumple(repo) -> None:
    assert por_sujeto(medir(GOLDEN, repo({"tests/test_x.py": "x = 1\n"}))) == {"demo/golden:oraculo": Veredicto.NO_CUMPLE}


def test_sin_golden_y_barrido_truncado_es_no_medible(repo, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = repo({"a.txt": "a", "b.txt": "b"})
    monkeypatch.setattr(baremo.probes, "LIMITE_ARCHIVOS", 1)
    assert medir(GOLDEN, raiz).subchecks[0].veredicto is Veredicto.NO_MEDIBLE


# ------------------------------------------------------------------- regla ↔ prueba

PRUEBAS_PY = """import pytest

def test_conciliar_por_folio():
    assert True

@pytest.mark.parametrize("x", [1, 2])
def test_redondeo(x):
    assert x

@pytest.mark.skip(reason="pendiente")
def test_saltada():
    assert True

class TestEstados:
    def test_cerrado_no_reabre(self):
        assert True
"""
PRUEBAS_TS = "it('rechaza fecha futura', () => { expect(1).toBe(1); });\nit.skip('omitida', () => {});\n"
MAPA = """# Reglas de negocio

| Regla | Descripción | Prueba(s) |
|---|---|---|
| R01 | Se concilia por folio | `tests/test_reglas.py::test_conciliar_por_folio` |
| R02 | Redondeo bancario | `tests/test_reglas.py::test_redondeo[1]`, `web/fecha.test.ts::rechaza fecha futura` |
| R03 | Un periodo cerrado no se reabre | tests/test_reglas.py::TestEstados::test_cerrado_no_reabre |
| R04 | Regla sin prueba | — |
| R05 | Prueba que no existe | `tests/test_reglas.py::test_fantasma` |
| R06 | Archivo que no existe | `tests/test_otro.py::test_x` |
| R07 | Prueba saltada | `tests/test_reglas.py::test_saltada` |
| R08 | Prueba omitida en JS | `web/fecha.test.ts::omitida` |
| R09 | Lenguaje no soportado | `spec/regla_spec.rb::valida` |

| Término | Significado |
|---|---|
| Folio | Identificador fiscal |
"""


def test_cada_regla_es_un_sujeto_con_su_veredicto(repo) -> None:
    raiz = repo({"docs/reglas.md": MAPA, "tests/test_reglas.py": PRUEBAS_PY,
                 "web/fecha.test.ts": PRUEBAS_TS, "spec/regla_spec.rb": "it 'valida' do\nend\n"})
    check = medir(REGLAS, raiz)
    assert por_sujeto(check) == {
        "demo/regla:R01": Veredicto.CUMPLE,
        "demo/regla:R02": Veredicto.CUMPLE,
        "demo/regla:R03": Veredicto.CUMPLE,
        "demo/regla:R04": Veredicto.NO_CUMPLE,
        "demo/regla:R05": Veredicto.NO_CUMPLE,
        "demo/regla:R06": Veredicto.NO_CUMPLE,
        "demo/regla:R07": Veredicto.NO_CUMPLE,
        "demo/regla:R08": Veredicto.NO_CUMPLE,
        "demo/regla:R09": Veredicto.NO_MEDIBLE,
    }
    texto = texto_de(check)
    assert "regla sin prueba" in texto
    assert "no define «test_fantasma»" in texto
    assert "marcada skip" in texto


def test_un_modulo_saltado_entero_no_cubre_reglas(repo) -> None:
    saltado = "import pytest\npytestmark = pytest.mark.skip\n\ndef test_a():\n    assert True\n"
    raiz = repo({"docs/reglas.md": "| Regla | Prueba |\n|---|---|\n| R1 | `tests/test_a.py::test_a` |\n",
                 "tests/test_a.py": saltado})
    assert medir(REGLAS, raiz).subchecks[0].veredicto is Veredicto.NO_CUMPLE


def test_sin_mapa_de_reglas_es_no_medible(repo) -> None:
    check = medir(REGLAS, repo({"tests/test_a.py": "def test_a():\n    assert True\n"}))
    assert por_sujeto(check) == {"demo/reglas:docs/reglas.md": Veredicto.NO_MEDIBLE}
    assert "docs/reglas.md" in check.subchecks[0].motivo


def test_mapa_sin_tabla_de_pruebas_es_no_medible(repo) -> None:
    check = medir(REGLAS, repo({"docs/reglas.md": "# Reglas\n\nPendiente de escribir.\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
