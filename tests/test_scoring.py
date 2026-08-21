"""Pruebas de `baremo.scoring.puntuar`.

Cada prueba de este archivo corresponde a un defecto medido en scorecards de madurez
reales. No son pruebas de regresión de una implementación: son la tesis del proyecto
escrita en forma ejecutable.
"""
from __future__ import annotations

import pytest

from baremo.model import Alcance, Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.scoring import UMBRAL_COBERTURA_POR_DEFECTO, puntuar

# --------------------------------------------------------------------------------------
# Constructores de apoyo
# --------------------------------------------------------------------------------------

def _sub(
    veredicto: Veredicto,
    sujeto: str = "<app>",
    id_subcheck: str = "SUB_1",
) -> ResultadoSubcheck:
    """Sub-check con evidencia: el modelo no admite veredictos sin fuente."""
    return ResultadoSubcheck(
        id=id_subcheck,
        descripcion="control de ejemplo",
        veredicto=veredicto,
        evidencias=[Evidencia(fuente="<entorno>/reporte.json", extracto="…")],
        sujeto=sujeto,
    )


def _check(
    veredictos: list[Veredicto],
    id_check: str = "CHK_1",
    peso: float = 1.0,
    eje: str = "entrega",
) -> ResultadoCheck:
    return ResultadoCheck(
        id=id_check,
        titulo=f"Check {id_check}",
        eje=eje,
        peso=peso,
        subchecks=[
            _sub(v, sujeto=f"sujeto-{i}", id_subcheck=f"{id_check}_{i}")
            for i, v in enumerate(veredictos)
        ],
    )


def _alcance_completo(n: int) -> Alcance:
    """Alcance sin brechas: todo lo declarado se midió."""
    sujetos = [f"sujeto-{i}" for i in range(n)]
    return Alcance(declarado=sujetos, medido=sujetos)


# --------------------------------------------------------------------------------------
# 1. La puntuación es PROPORCIONAL
# --------------------------------------------------------------------------------------

def test_corregir_58_de_59_sube_la_nota_no_es_todo_o_nada() -> None:
    """El caso que motiva el proyecto.

    En un modelo donde "mezcla de aprobados y reprobados" vale un valor fijo (medio
    punto), arreglar 58 de 59 sujetos vale exactamente lo mismo que arreglar 1: el
    esfuerzo no se ve y termina desincentivando cerrar el último tramo. Aquí la nota es
    la proporción real.
    """
    veredictos = [Veredicto.CUMPLE] * 58 + [Veredicto.NO_CUMPLE]
    nota = puntuar([_check(veredictos)], _alcance_completo(59))

    assert nota.cumplimiento == pytest.approx(58 / 59)
    assert nota.cumplimiento == pytest.approx(0.983, abs=0.001)
    # Lo que NO debe pasar: colapsar a un valor fijo por "estar mezclado".
    assert nota.cumplimiento != pytest.approx(0.5)
    assert nota.publicable is True


def test_cada_sujeto_corregido_mueve_la_nota() -> None:
    """La derivada existe: corregir uno más siempre sube el número."""
    anterior = -1.0
    for aprobados in range(0, 60):
        veredictos = [Veredicto.CUMPLE] * aprobados + [Veredicto.NO_CUMPLE] * (59 - aprobados)
        nota = puntuar([_check(veredictos)], _alcance_completo(59))
        assert nota.cumplimiento is not None
        assert nota.cumplimiento > anterior
        anterior = nota.cumplimiento


# --------------------------------------------------------------------------------------
# 2. NO_MEDIBLE no aprueba ni reprueba: baja la COBERTURA
# --------------------------------------------------------------------------------------

def test_no_medible_no_aprueba_ni_reprueba_baja_la_cobertura() -> None:
    nota = puntuar(
        [_check([Veredicto.CUMPLE] * 4 + [Veredicto.NO_MEDIBLE])],
        _alcance_completo(5),
    )
    detalle = nota.checks[0]

    # Ni aprobado ni reprobado: fuera del denominador del cumplimiento.
    assert detalle.aprobados == 4
    assert detalle.reprobados == 0
    assert detalle.no_medibles == 1
    assert detalle.medibles == 4
    assert nota.cumplimiento == pytest.approx(1.0)

    # El precio de no haber podido medir se cobra en la cobertura, no en el cumplimiento.
    assert nota.cobertura == pytest.approx(4 / 5)


def test_un_check_sin_datos_no_arrastra_el_promedio_a_cero() -> None:
    """Un check que no pudo medirse NO vale cero: sale del promedio y baja la cobertura.

    Contarlo como cero castigaría a quien instrumenta de más; contarlo como aprobado es
    el defecto original. La tercera salida —no contarlo, pero reportarlo— es la correcta.
    """
    con_datos = _check([Veredicto.CUMPLE] * 4, id_check="CHK_A")
    sin_datos = _check([Veredicto.NO_MEDIBLE] * 4, id_check="CHK_B")
    nota = puntuar([con_datos, sin_datos], _alcance_completo(8))

    assert nota.checks[1].cumplimiento is None
    assert nota.cumplimiento == pytest.approx(1.0)   # no es 0.5
    assert nota.cobertura == pytest.approx(4 / 8)
    assert nota.publicable is False


# --------------------------------------------------------------------------------------
# 3. Degradar la instrumentación no puede pagar
# --------------------------------------------------------------------------------------

def test_marcar_como_no_medible_lo_que_cumple_nunca_sube_el_cumplimiento() -> None:
    base = puntuar(
        [_check([Veredicto.CUMPLE] * 7 + [Veredicto.NO_CUMPLE] * 3)],
        _alcance_completo(10),
    )
    degradada = puntuar(
        [_check(
            [Veredicto.NO_MEDIBLE] * 4 + [Veredicto.CUMPLE] * 3 + [Veredicto.NO_CUMPLE] * 3
        )],
        _alcance_completo(10),
    )

    assert base.cumplimiento is not None and degradada.cumplimiento is not None
    assert degradada.cumplimiento <= base.cumplimiento
    assert degradada.cobertura < base.cobertura


def test_degradar_la_instrumentacion_no_produce_una_nota_publicable_mejor() -> None:
    """El agujero clásico: dejar de medir lo que reprueba.

    Aislado, el porcentaje SÍ sube — 7/7 en vez de 7/10 — y ese es exactamente el
    incentivo perverso que hay que cerrar. Se cierra con la segunda cifra: la cobertura
    cae al 70% y la nota deja de ser publicable. El número mejorado no se puede reportar.
    """
    base = puntuar(
        [_check([Veredicto.CUMPLE] * 7 + [Veredicto.NO_CUMPLE] * 3)],
        _alcance_completo(10),
    )
    apagando_lo_que_reprueba = puntuar(
        [_check([Veredicto.CUMPLE] * 7 + [Veredicto.NO_MEDIBLE] * 3)],
        _alcance_completo(10),
    )

    assert base.publicable is True
    assert base.cumplimiento == pytest.approx(0.7)

    # El número aislado sube…
    assert apagando_lo_que_reprueba.cumplimiento == pytest.approx(1.0)
    # …pero no se publica, porque la cobertura delata que se miró menos.
    assert apagando_lo_que_reprueba.cobertura == pytest.approx(0.7)
    assert apagando_lo_que_reprueba.publicable is False
    assert "cobertura" in apagando_lo_que_reprueba.motivo_retencion.lower()


# --------------------------------------------------------------------------------------
# 4. Sin cobertura suficiente, el cumplimiento se RETIENE
# --------------------------------------------------------------------------------------

def test_cobertura_bajo_el_umbral_retiene_el_cumplimiento_y_lo_explica() -> None:
    nota = puntuar(
        [_check([Veredicto.CUMPLE] * 4 + [Veredicto.NO_MEDIBLE] * 6)],
        _alcance_completo(10),
    )

    assert nota.cobertura == pytest.approx(0.4)
    assert nota.publicable is False

    motivo = nota.motivo_retencion
    assert motivo, "retener sin explicar por qué sería el mismo defecto en otra forma"
    assert "40%" in motivo                      # la cobertura obtenida
    assert "80%" in motivo                      # el umbral exigido
    assert "retiene" in motivo.lower()

    # El cumplimiento sigue calculado —se puede auditar—, pero no es publicable.
    assert nota.cumplimiento == pytest.approx(1.0)


def test_el_umbral_de_cobertura_es_configurable() -> None:
    checks = [_check([Veredicto.CUMPLE] * 6 + [Veredicto.NO_MEDIBLE] * 4)]
    alcance = _alcance_completo(10)

    laxo = puntuar(checks, alcance, umbral_cobertura=0.5)
    estricto = puntuar(checks, alcance, umbral_cobertura=UMBRAL_COBERTURA_POR_DEFECTO)

    assert laxo.publicable is True
    assert estricto.publicable is False


# --------------------------------------------------------------------------------------
# 5. El alcance declarado y no medido PESA
# --------------------------------------------------------------------------------------

def test_lo_declarado_que_no_se_midio_ni_se_excluyo_baja_la_cobertura() -> None:
    """Recortar el alcance en silencio es la otra forma de mirar menos.

    Excluir con motivo declarado es legítimo y no castiga; omitir sin decirlo, sí.
    """
    check = _check([Veredicto.CUMPLE] * 8)
    declarado = [f"sujeto-{i}" for i in range(12)]

    completo = puntuar([check], _alcance_completo(8))
    parcial = puntuar(
        [check],
        Alcance(
            declarado=declarado,
            medido=[f"sujeto-{i}" for i in range(8)],
            excluido={"sujeto-8": "Repositorio archivado; se apaga este trimestre."},
        ),
    )

    # sujeto-9, sujeto-10 y sujeto-11 se declararon y nadie los midió ni los excluyó.
    assert parcial.alcance.omitido_sin_declarar == ["sujeto-9", "sujeto-10", "sujeto-11"]
    assert parcial.cobertura == pytest.approx(8 / 11)
    assert parcial.cobertura < completo.cobertura

    # Y el motivo nombra a los ausentes: la omisión se señala con nombre y apellido.
    motivo = parcial.motivo_retencion
    assert parcial.publicable is False
    assert "sujeto-9" in motivo and "sujeto-11" in motivo


def test_excluir_con_motivo_declarado_no_castiga_la_cobertura() -> None:
    check = _check([Veredicto.CUMPLE] * 8)
    nota = puntuar(
        [check],
        Alcance(
            declarado=[f"sujeto-{i}" for i in range(9)],
            medido=[f"sujeto-{i}" for i in range(8)],
            excluido={"sujeto-8": "Sin código propio: sólo configuración generada."},
        ),
    )

    assert nota.alcance.omitido_sin_declarar == []
    assert nota.cobertura == pytest.approx(1.0)
    assert nota.publicable is True


# --------------------------------------------------------------------------------------
# 6. Las supresiones cuentan como cumplimiento, pero se ven
# --------------------------------------------------------------------------------------

def test_suprimidos_cuentan_como_cumplimiento_pero_se_contabilizan_aparte() -> None:
    nota = puntuar(
        [_check([Veredicto.CUMPLE] * 3 + [Veredicto.SUPRIMIDO] * 2)],
        _alcance_completo(5),
    )
    detalle = nota.checks[0]

    assert nota.cumplimiento == pytest.approx(1.0)
    assert detalle.medibles == 5
    # La cifra de arriba es 100%, pero el reporte puede decir CUÁNTO de ese 100% es
    # excepción declarada. Un aprobado y una supresión no son lo mismo.
    assert detalle.aprobados == 3
    assert detalle.suprimidos == 2

    sin_supresiones = puntuar(
        [_check([Veredicto.CUMPLE] * 3 + [Veredicto.NO_CUMPLE] * 2)],
        _alcance_completo(5),
    )
    assert sin_supresiones.cumplimiento == pytest.approx(0.6)


def test_suprimir_no_afecta_la_cobertura() -> None:
    """Una supresión es una decisión sobre algo que SÍ se midió: la cobertura no cambia."""
    nota = puntuar([_check([Veredicto.SUPRIMIDO] * 4)], _alcance_completo(4))
    assert nota.cobertura == pytest.approx(1.0)
    assert nota.checks[0].no_medibles == 0


# --------------------------------------------------------------------------------------
# 7. Pesos
# --------------------------------------------------------------------------------------

def test_una_sonda_con_peso_doble_mueve_el_doble() -> None:
    pesado_bien = puntuar(
        [
            _check([Veredicto.CUMPLE], id_check="SEGURIDAD", peso=2.0),
            _check([Veredicto.NO_CUMPLE], id_check="PRUEBAS", peso=1.0),
        ],
        _alcance_completo(1),
    )
    pesado_al_reves = puntuar(
        [
            _check([Veredicto.NO_CUMPLE], id_check="SEGURIDAD", peso=2.0),
            _check([Veredicto.CUMPLE], id_check="PRUEBAS", peso=1.0),
        ],
        _alcance_completo(1),
    )

    assert pesado_bien.cumplimiento == pytest.approx(2 / 3)
    assert pesado_al_reves.cumplimiento == pytest.approx(1 / 3)

    # Con pesos iguales, los mismos veredictos dan justo la mitad: el peso es lo único
    # que separa a los dos escenarios.
    plano = puntuar(
        [
            _check([Veredicto.CUMPLE], id_check="SEGURIDAD", peso=1.0),
            _check([Veredicto.NO_CUMPLE], id_check="PRUEBAS", peso=1.0),
        ],
        _alcance_completo(1),
    )
    assert plano.cumplimiento == pytest.approx(0.5)


def test_un_check_sin_datos_no_consume_su_peso() -> None:
    """Si un check pesado no pudo medirse, su peso no se reparte a favor de nadie."""
    nota = puntuar(
        [
            _check([Veredicto.NO_MEDIBLE], id_check="SEGURIDAD", peso=2.0),
            _check([Veredicto.CUMPLE], id_check="PRUEBAS", peso=1.0),
        ],
        _alcance_completo(1),
    )
    assert nota.cumplimiento == pytest.approx(1.0)   # sólo el check que midió
    assert nota.cobertura == pytest.approx(0.5)      # …y la cobertura lo denuncia
    assert nota.publicable is False


# --------------------------------------------------------------------------------------
# 8. Sin datos no hay nota
# --------------------------------------------------------------------------------------

def test_todos_los_checks_sin_datos_dan_cumplimiento_none_y_no_publicable() -> None:
    nota = puntuar(
        [
            _check([Veredicto.NO_MEDIBLE] * 3, id_check="CHK_A"),
            _check([Veredicto.NO_MEDIBLE] * 2, id_check="CHK_B"),
        ],
        _alcance_completo(5),
    )

    assert nota.cumplimiento is None
    assert nota.publicable is False
    assert "pudo medirse" in nota.motivo_retencion
    assert nota.cobertura == pytest.approx(0.0)


def test_sin_checks_no_hay_nota_que_publicar() -> None:
    """El caso degenerado: no medir NADA no puede leerse como cumplimiento perfecto."""
    nota = puntuar([], Alcance())

    assert nota.cumplimiento is None
    assert nota.publicable is False
    assert nota.motivo_retencion
