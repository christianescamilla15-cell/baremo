"""Pruebas de `baremo.supresiones`.

Una supresión es la única forma legítima de que un hallazgo deje de restar. Por eso se
prueba con la misma dureza que la puntuación: que aplique cuando está vigente, que NO
aplique cuando venció, y que en ningún caso desaparezca del registro.
"""
from __future__ import annotations

from datetime import date

import pytest

from baremo.model import (
    Alcance,
    Evidencia,
    ResultadoCheck,
    ResultadoSubcheck,
    Supresion,
    Veredicto,
)
from baremo.scoring import puntuar
from baremo.supresiones import (
    EVENTO_APLICADA,
    EVENTO_HUERFANA,
    EVENTO_SIN_EFECTO,
    EVENTO_VENCIDA,
    SupresionInvalida,
    aplicar_supresiones,
    avisos,
    cargar_supresiones,
)

HOY = date(2026, 8, 21)
FECHA_VIGENTE = date(2026, 12, 31)
FECHA_VENCIDA = date(2026, 1, 31)

SUBCHECK = "SEC_ANALISIS_ESTATICO"
SUJETO = "mi-repo"
JUSTIFICACION = "El análisis corre en la plataforma de la organización, fuera de este repo."


# --------------------------------------------------------------------------------------
# Constructores de apoyo
# --------------------------------------------------------------------------------------

def _sub(
    veredicto: Veredicto,
    id_subcheck: str = SUBCHECK,
    sujeto: str = SUJETO,
) -> ResultadoSubcheck:
    return ResultadoSubcheck(
        id=id_subcheck,
        descripcion="El repositorio ejecuta análisis estático en cada cambio.",
        veredicto=veredicto,
        evidencias=[Evidencia(fuente="<entorno>/pipeline.yml", extracto="pasos: […]")],
        motivo="No se encontró ningún paso de análisis estático.",
        sujeto=sujeto,
    )


def _check(subchecks: list[ResultadoSubcheck]) -> ResultadoCheck:
    return ResultadoCheck(
        id="SEGURIDAD",
        titulo="Seguridad en la construcción",
        eje="seguridad",
        peso=1.0,
        subchecks=subchecks,
    )


def _supresion(
    vence: date = FECHA_VIGENTE,
    sujeto: str = SUJETO,
    subcheck: str = SUBCHECK,
    autorizada_por: str = "equipo-plataforma",
) -> Supresion:
    return Supresion(
        subcheck_id=subcheck,
        sujeto=sujeto,
        justificacion=JUSTIFICACION,
        vence=vence,
        autorizada_por=autorizada_por,
    )


def _eventos(registro: list[dict]) -> list[str]:
    return [entrada["evento"] for entrada in registro]


# --------------------------------------------------------------------------------------
# Vigente: aplica y deja rastro
# --------------------------------------------------------------------------------------

def test_supresion_vigente_convierte_no_cumple_en_suprimido() -> None:
    checks, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE)])], [_supresion()], HOY
    )

    subcheck = checks[0].subchecks[0]
    assert subcheck.veredicto is Veredicto.SUPRIMIDO

    # Suprimir no es borrar: la justificación, la autoridad y la fecha viajan con el dato.
    assert JUSTIFICACION in subcheck.motivo
    assert "equipo-plataforma" in subcheck.motivo
    assert "2026-12-31" in subcheck.motivo
    assert "No se encontró ningún paso" in subcheck.motivo   # el hallazgo original sigue ahí
    assert any(e.fuente == "supresiones.yml" for e in subcheck.evidencias)

    assert _eventos(registro) == [EVENTO_APLICADA]
    assert registro[0]["check"] == "SEGURIDAD"
    assert registro[0]["subcheck"] == SUBCHECK
    assert registro[0]["aviso"] is False


def test_solo_se_suprime_lo_que_reprueba() -> None:
    """NO_MEDIBLE nunca se convierte en SUPRIMIDO: no se puede exceptuar lo que no se midió."""
    checks, _ = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_MEDIBLE)])], [_supresion()], HOY
    )
    assert checks[0].subchecks[0].veredicto is Veredicto.NO_MEDIBLE


def test_el_comodin_de_sujeto_aplica_a_todos_los_sujetos_del_subcheck() -> None:
    checks, registro = aplicar_supresiones(
        [
            _check([
                _sub(Veredicto.NO_CUMPLE, sujeto="repo-a"),
                _sub(Veredicto.NO_CUMPLE, sujeto="repo-b"),
            ])
        ],
        [_supresion(sujeto="*")],
        HOY,
    )

    assert [s.veredicto for s in checks[0].subchecks] == [
        Veredicto.SUPRIMIDO,
        Veredicto.SUPRIMIDO,
    ]
    assert _eventos(registro) == [EVENTO_APLICADA, EVENTO_APLICADA]
    assert [e["sujeto_afectado"] for e in registro] == ["repo-a", "repo-b"]


def test_la_supresion_exacta_gana_a_la_comodin() -> None:
    """Lo particular manda sobre lo general: una excepción acotada no la absorbe una amplia."""
    exacta = _supresion(sujeto="repo-b", autorizada_por="responsable-del-repo")
    comodin = _supresion(sujeto="*", autorizada_por="equipo-plataforma")

    _, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE, sujeto="repo-b")])],
        [comodin, exacta],
        HOY,
    )

    aplicadas = [e for e in registro if e["evento"] == EVENTO_APLICADA]
    assert len(aplicadas) == 1
    assert aplicadas[0]["autorizada_por"] == "responsable-del-repo"
    # La comodín no aplicó, y aun así aparece en el registro.
    assert EVENTO_SIN_EFECTO in _eventos(registro)


# --------------------------------------------------------------------------------------
# Vencida: NO aplica, y se reporta
# --------------------------------------------------------------------------------------

def test_supresion_vencida_no_aplica_y_se_reporta() -> None:
    checks, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE)])], [_supresion(vence=FECHA_VENCIDA)], HOY
    )

    # El hallazgo vuelve a contar tal cual estaba.
    subcheck = checks[0].subchecks[0]
    assert subcheck.veredicto is Veredicto.NO_CUMPLE
    assert subcheck.motivo == "No se encontró ningún paso de análisis estático."

    assert _eventos(registro) == [EVENTO_VENCIDA]
    entrada = registro[0]
    assert entrada["aviso"] is True
    assert entrada["vence"] == "2026-01-31"
    assert "VENCIDA" in entrada["detalle"]
    assert "vuelven a contar" in entrada["detalle"]
    assert avisos(registro) == [entrada]


def test_una_supresion_vencida_deja_reprobado_el_check_al_puntuar() -> None:
    """La prueba de que no es cosmética: el número cambia según la vigencia."""
    checks_base = [_check([_sub(Veredicto.NO_CUMPLE), _sub(Veredicto.CUMPLE, sujeto="otro")])]
    alcance = Alcance(declarado=[SUJETO, "otro"], medido=[SUJETO, "otro"])

    con_vigente, _ = aplicar_supresiones(checks_base, [_supresion()], HOY)
    con_vencida, _ = aplicar_supresiones(
        checks_base, [_supresion(vence=FECHA_VENCIDA)], HOY
    )

    assert puntuar(con_vigente, alcance).cumplimiento == pytest.approx(1.0)
    assert puntuar(con_vencida, alcance).cumplimiento == pytest.approx(0.5)

    # Y aun cuando aplica, el reporte puede separar aprobado de exceptuado.
    assert puntuar(con_vigente, alcance).checks[0].suprimidos == 1


def test_supresion_que_vence_hoy_todavia_aplica() -> None:
    """El día del vencimiento aún cuenta; el siguiente ya no. La frontera se prueba."""
    checks_hoy, _ = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE)])], [_supresion(vence=HOY)], HOY
    )
    checks_manana, _ = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE)])], [_supresion(vence=HOY)], date(2026, 8, 22)
    )

    assert checks_hoy[0].subchecks[0].veredicto is Veredicto.SUPRIMIDO
    assert checks_manana[0].subchecks[0].veredicto is Veredicto.NO_CUMPLE


# --------------------------------------------------------------------------------------
# Casos que no alteran nada: tampoco se callan
# --------------------------------------------------------------------------------------

def test_supresion_de_un_subcheck_que_cumple_no_altera_nada() -> None:
    original = _check([_sub(Veredicto.CUMPLE)])
    checks, registro = aplicar_supresiones([original], [_supresion()], HOY)

    subcheck = checks[0].subchecks[0]
    assert subcheck.veredicto is Veredicto.CUMPLE
    assert subcheck.motivo == original.subchecks[0].motivo
    assert len(subcheck.evidencias) == len(original.subchecks[0].evidencias)

    # No cambió el resultado, pero el archivo de supresiones tiene una entrada de más.
    assert _eventos(registro) == [EVENTO_SIN_EFECTO]
    assert registro[0]["aviso"] is True


def test_supresion_huerfana_se_reporta() -> None:
    _, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE, id_subcheck="OTRO_CONTROL")])],
        [_supresion()],
        HOY,
    )

    assert _eventos(registro) == [EVENTO_HUERFANA]
    assert "No coincidió" in registro[0]["detalle"]


def test_supresion_de_otro_sujeto_no_aplica() -> None:
    checks, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE, sujeto="repo-a")])],
        [_supresion(sujeto="repo-b")],
        HOY,
    )

    assert checks[0].subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert _eventos(registro) == [EVENTO_HUERFANA]


def test_sin_supresiones_todo_queda_igual() -> None:
    checks, registro = aplicar_supresiones(
        [_check([_sub(Veredicto.NO_CUMPLE)])], [], HOY
    )
    assert checks[0].subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert registro == []


def test_no_muta_los_checks_de_entrada() -> None:
    """El reporte tiene que poder mostrar el antes y el después."""
    original = _check([_sub(Veredicto.NO_CUMPLE)])
    checks, _ = aplicar_supresiones([original], [_supresion()], HOY)

    assert original.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert len(original.subchecks[0].evidencias) == 1
    assert checks[0] is not original
    assert checks[0].subchecks[0] is not original.subchecks[0]


# --------------------------------------------------------------------------------------
# Lectura del archivo declarado
# --------------------------------------------------------------------------------------

def test_cargar_supresiones_archivo_inexistente_no_es_error(tmp_path) -> None:
    assert cargar_supresiones(tmp_path / "no-existe.yml") == []


def test_cargar_supresiones_archivo_vacio(tmp_path) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text("", encoding="utf-8")
    assert cargar_supresiones(archivo) == []


def test_cargar_supresiones_lee_la_forma_declarada(tmp_path) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text(
        f"""
- subcheck: {SUBCHECK}
  sujeto: "{SUJETO}"
  justificacion: "{JUSTIFICACION}"
  vence: 2026-12-31
  autorizada_por: "equipo-plataforma"
- subcheck: OTRO_CONTROL
  justificacion: "No aplica a bibliotecas sin despliegue."
  vence: "2027-01-15"
  autorizada_por: "comité-de-arquitectura"
""",
        encoding="utf-8",
    )

    leidas = cargar_supresiones(archivo)

    assert len(leidas) == 2
    assert leidas[0].subcheck_id == SUBCHECK
    assert leidas[0].sujeto == SUJETO
    assert leidas[0].vence == date(2026, 12, 31)
    assert leidas[0].vigente(HOY) is True
    # Fecha entrecomillada y sujeto ausente: se aceptan, el sujeto queda como comodín.
    assert leidas[1].vence == date(2027, 1, 15)
    assert leidas[1].sujeto == "*"


@pytest.mark.parametrize(
    "cuerpo",
    [
        # Sin justificación: sería una aprobación silenciosa.
        f"- subcheck: {SUBCHECK}\n  vence: 2026-12-31\n  autorizada_por: alguien\n",
        # Sin vencimiento: sería un permiso eterno.
        f"- subcheck: {SUBCHECK}\n  justificacion: motivo\n  autorizada_por: alguien\n",
        # Sin autoridad: nadie se hace responsable.
        f"- subcheck: {SUBCHECK}\n  justificacion: motivo\n  vence: 2026-12-31\n",
        # Justificación vacía.
        f"- subcheck: {SUBCHECK}\n  justificacion: ''\n"
        "  vence: 2026-12-31\n  autorizada_por: alguien\n",
    ],
)
def test_una_supresion_incompleta_falla_en_vez_de_ignorarse(tmp_path, cuerpo: str) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text(cuerpo, encoding="utf-8")

    with pytest.raises(SupresionInvalida):
        cargar_supresiones(archivo)


def test_fecha_no_iso_falla(tmp_path) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text(
        f"- subcheck: {SUBCHECK}\n"
        "  justificacion: motivo\n"
        "  vence: 'el trimestre que viene'\n"
        "  autorizada_por: alguien\n",
        encoding="utf-8",
    )

    with pytest.raises(SupresionInvalida):
        cargar_supresiones(archivo)


def test_raiz_que_no_es_lista_falla(tmp_path) -> None:
    archivo = tmp_path / "supresiones.yml"
    archivo.write_text("subcheck: X\n", encoding="utf-8")

    with pytest.raises(SupresionInvalida):
        cargar_supresiones(archivo)
