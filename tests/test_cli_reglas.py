"""Reglas de la CLI que no tenían prueba: códigos de salida 1, 3 y 64, y las supresiones
tal como las aplica la CLI (vigente, vencida, NO_MEDIBLE y supresión incompleta)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from baremo.cli import (
    SALIDA_BAJO_MINIMO,
    SALIDA_ERROR,
    SALIDA_USO,
    ErrorDeOperacion,
    aplicar_supresiones,
    cargar_supresiones,
    main,
)
from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Supresion, Veredicto

HOY = date(2026, 11, 19)


@pytest.fixture
def sujeto(repo) -> Path:
    return repo({"README.md": "# Demo\n", "src/app.py": "x = 1\n"})


def _check(*veredictos: Veredicto) -> ResultadoCheck:
    subs = [ResultadoSubcheck(id="SEC_POLITICA", descripcion="d", veredicto=v,
                              evidencias=[Evidencia(fuente="x")], motivo="m", sujeto=f"s{i}")
            for i, v in enumerate(veredictos)]
    return ResultadoCheck(id="seguridad", titulo="t", eje="e", subchecks=subs)


def _supresion(vence: date) -> Supresion:
    return Supresion(subcheck_id="SEC_POLITICA", sujeto="*", justificacion="porque sí, por escrito",
                     vence=vence, autorizada_por="Ana Pérez")


def test_salida_1_cuando_el_cumplimiento_queda_bajo_el_minimo(sujeto: Path, tmp_path: Path) -> None:
    codigo = main(["evaluar", str(sujeto), "--umbral-cobertura", "0", "--minimo", "1.0",
                   "--formato", "json", "--salida", str(tmp_path / "i.json")])
    assert codigo == SALIDA_BAJO_MINIMO


def test_salida_3_cuando_el_excluido_no_trae_motivo(sujeto: Path, tmp_path: Path) -> None:
    config = tmp_path / "baremo.yml"
    config.write_text("alcance:\n  excluido: [servicio-b]\n", encoding="utf-8")
    assert main(["evaluar", str(sujeto), "--config", str(config)]) == SALIDA_ERROR


def test_salida_3_cuando_el_sujeto_no_existe(tmp_path: Path) -> None:
    assert main(["evaluar", str(tmp_path / "no-existe")]) == SALIDA_ERROR


def test_salida_64_ante_un_uso_incorrecto() -> None:
    with pytest.raises(SystemExit) as salida:
        main(["evaluar", "--opcion-que-no-existe"])
    assert salida.value.code == SALIDA_USO


def test_supresion_vigente_convierte_no_cumple_en_suprimido_y_se_lista() -> None:
    check = _check(Veredicto.NO_CUMPLE)
    aplicadas, vencidas, _ = aplicar_supresiones([check], [_supresion(date(2026, 12, 31))], HOY)
    assert check.subchecks[0].veredicto is Veredicto.SUPRIMIDO
    assert len(aplicadas) == 1 and not vencidas
    assert "Ana Pérez" in check.subchecks[0].motivo


def test_supresion_vencida_no_aplica_y_vuelve_a_contar() -> None:
    check = _check(Veredicto.NO_CUMPLE)
    aplicadas, vencidas, _ = aplicar_supresiones([check], [_supresion(date(2026, 1, 31))], HOY)
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert not aplicadas and len(vencidas) == 1


def test_una_supresion_nunca_tapa_un_no_medible() -> None:
    check = _check(Veredicto.NO_MEDIBLE)
    aplicadas, _, sin_efecto = aplicar_supresiones([check], [_supresion(date(2026, 12, 31))], HOY)
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
    assert not aplicadas and len(sin_efecto) == 1


@pytest.mark.parametrize("cuerpo", [
    "supresiones:\n  - subcheck: X\n    vence: 2026-12-31\n    autorizada_por: Ana\n",
    "supresiones:\n  - subcheck: X\n    vence: 2026-12-31\n    justificacion: motivo\n",
    "supresiones:\n  - subcheck: X\n    justificacion: motivo\n    autorizada_por: Ana\n",
])
def test_una_supresion_sin_justificacion_autor_o_vencimiento_se_rechaza(tmp_path: Path, cuerpo: str) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text(cuerpo, encoding="utf-8")
    with pytest.raises(ErrorDeOperacion):
        cargar_supresiones(archivo)
