"""Supresiones declaradas (`supresiones.yml`): excepciones que se VEN.

Una supresión es la manera honesta de decir "esto no aplica aquí, y este es el motivo,
y esta es la fecha en que hay que volver a discutirlo". Se distingue de las dos formas
deshonestas de obtener el mismo número:

  * bajar el alcance para que el sujeto incómodo no se mida (lo detecta la cobertura), y
  * marcar el control como aprobado a mano (lo detecta la evidencia obligatoria).

Reglas del módulo, todas orientadas a que nunca se pierda el rastro:

  1. Sólo una supresión VIGENTE convierte NO_CUMPLE en SUPRIMIDO. Vencida NO aplica:
     el sujeto vuelve a reprobar y el vencimiento sale como aviso.
  2. Nunca se toca un CUMPLE, un NO_MEDIBLE ni un veredicto ya suprimido. Una supresión
     sobre algo que ya cumple no cambia nada, pero se reporta como `sin_efecto`: suele
     significar que la excepción ya sobra y puede borrarse del archivo.
  3. Una supresión que no coincide con ningún sub-check se reporta como `huerfana`.
     Es el síntoma de un archivo que envejeció respecto de los controles.
  4. Se devuelve una copia de los checks; la lista de entrada no se muta.

Esquema de `supresiones.yml` (lista de mapas):

```yaml
- subcheck: SEC_ANALISIS_ESTATICO
  sujeto: "mi-repo"                 # "*" o ausente = todos los sujetos de ese sub-check
  justificacion: "El análisis corre en la plataforma de la organización, fuera de este repo."
  vence: 2026-12-31                 # fecha ISO; obligatoria: sin vencimiento es permiso eterno
  autorizada_por: "equipo-plataforma"
```

Las claves no reconocidas se ignoran; las obligatorias (`subcheck`, `justificacion`,
`vence`, `autorizada_por`) se exigen, de modo que una errata en el nombre de una clave
obligatoria falla en vez de producir una supresión sin justificación.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Supresion, Veredicto

RUTA_SUPRESIONES_POR_DEFECTO = Path("supresiones.yml")

# Comodín de sujeto: la supresión aplica a todos los sujetos de ese sub-check.
COMODIN_SUJETO = "*"

# Eventos del registro de aplicación.
EVENTO_APLICADA = "aplicada"      # NO_CUMPLE -> SUPRIMIDO
EVENTO_VENCIDA = "vencida"        # no aplicó: la excepción caducó
EVENTO_SIN_EFECTO = "sin_efecto"  # coincidió, pero no había nada que suprimir
EVENTO_HUERFANA = "huerfana"      # no coincidió con ningún sub-check evaluado

# Los eventos que un reporte debe mostrar como aviso, no como nota al pie.
EVENTOS_AVISO = frozenset({EVENTO_VENCIDA, EVENTO_SIN_EFECTO, EVENTO_HUERFANA})

_CLAVES_OBLIGATORIAS = ("subcheck", "justificacion", "vence", "autorizada_por")


class SupresionInvalida(ValueError):
    """El archivo de supresiones no se puede leer sin suponer.

    Se falla en vez de saltarse la entrada: una supresión mal escrita que se ignora en
    silencio es indistinguible de una supresión que sí aplicó.
    """


def cargar_supresiones(
    ruta: str | Path | None = RUTA_SUPRESIONES_POR_DEFECTO,
) -> list[Supresion]:
    """Lee `supresiones.yml`. Si no existe, no hay supresiones (lista vacía).

    Lanza `SupresionInvalida` si el archivo existe pero alguna entrada está incompleta:
    sin justificación, sin autoridad o sin fecha de vencimiento.
    """
    if ruta is None:
        return []

    archivo = Path(ruta)
    if not archivo.is_file():
        return []

    try:
        crudo: Any = yaml.safe_load(archivo.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - depende del archivo del usuario
        raise SupresionInvalida(f"{archivo} no es YAML válido: {exc}") from exc

    if crudo is None:
        return []
    if not isinstance(crudo, list):
        raise SupresionInvalida(
            f"{archivo}: la raíz debe ser una lista de supresiones, "
            f"se leyó {type(crudo).__name__}."
        )

    supresiones: list[Supresion] = []
    for posicion, entrada in enumerate(crudo, start=1):
        supresiones.append(_leer_supresion(entrada, archivo, posicion))
    return supresiones


def aplicar_supresiones(
    checks: list[ResultadoCheck],
    supresiones: list[Supresion],
    hoy: date | None = None,
) -> tuple[list[ResultadoCheck], list[dict[str, Any]]]:
    """Aplica las supresiones VIGENTES y devuelve `(checks_nuevos, registro)`.

    `checks_nuevos` es una copia: los objetos de entrada no se modifican, para que el
    reporte pueda mostrar el antes y el después si lo necesita.

    `registro` es la bitácora completa de lo que pasó con cada supresión: una entrada
    `aplicada` por cada sub-check efectivamente suprimido (con el check al que pertenece),
    más una entrada de cierre por cada supresión que NO aplicó — vencida, sin efecto o
    huérfana. Ningún caso se resuelve callando.
    """
    dia = hoy if hoy is not None else date.today()

    # Contadores por supresión, indexados por posición en la lista declarada.
    coincidencias = [0] * len(supresiones)
    aplicaciones = [0] * len(supresiones)
    bloqueadas_por_vencimiento = [0] * len(supresiones)

    aplicadas: list[dict[str, Any]] = []
    checks_nuevos: list[ResultadoCheck] = []

    for check in checks:
        subchecks_nuevos: list[ResultadoSubcheck] = []
        for sub in check.subchecks:
            candidatas = _candidatas(sub, supresiones)
            for indice, _ in candidatas:
                coincidencias[indice] += 1

            vigentes = [(i, s) for i, s in candidatas if s.vigente(dia)]
            vencidas = [(i, s) for i, s in candidatas if not s.vigente(dia)]

            if sub.veredicto is Veredicto.NO_CUMPLE and vigentes:
                indice, supresion = vigentes[0]
                aplicaciones[indice] += 1
                subchecks_nuevos.append(_suprimir(sub, supresion))
                aplicadas.append(
                    _entrada(
                        EVENTO_APLICADA,
                        supresion,
                        check_id=check.id,
                        sujeto_afectado=sub.sujeto,
                        detalle=(
                            f"{sub.id} pasó de NO_CUMPLE a SUPRIMIDO; "
                            f"la excepción vence el {supresion.vence.isoformat()}."
                        ),
                    )
                )
                continue

            if sub.veredicto is Veredicto.NO_CUMPLE and vencidas:
                # No se suprime: el hallazgo vuelve a contar y queda constancia de por qué.
                for indice, _ in vencidas:
                    bloqueadas_por_vencimiento[indice] += 1

            # Copia con su propia lista de evidencias: el objeto de entrada queda intacto.
            subchecks_nuevos.append(
                dataclasses.replace(sub, evidencias=list(sub.evidencias))
            )

        checks_nuevos.append(dataclasses.replace(check, subchecks=subchecks_nuevos))

    registro = aplicadas + _cierre(
        supresiones, dia, coincidencias, aplicaciones, bloqueadas_por_vencimiento
    )
    return checks_nuevos, registro


def avisos(registro: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Subconjunto del registro que un reporte NO debe esconder."""
    return [entrada for entrada in registro if entrada["evento"] in EVENTOS_AVISO]


# --------------------------------------------------------------------------------------
# Interno
# --------------------------------------------------------------------------------------

def _candidatas(
    sub: ResultadoSubcheck, supresiones: list[Supresion]
) -> list[tuple[int, Supresion]]:
    """Supresiones que hablan de este sub-check, de la más específica a la más general.

    Una supresión con sujeto exacto gana a un comodín: lo particular manda sobre lo
    general, y así una excepción amplia no se traga el caso que alguien acotó a mano.
    """
    exactas: list[tuple[int, Supresion]] = []
    comodines: list[tuple[int, Supresion]] = []
    for indice, supresion in enumerate(supresiones):
        if supresion.subcheck_id != sub.id:
            continue
        objetivo = (supresion.sujeto or COMODIN_SUJETO).strip()
        if objetivo in ("", COMODIN_SUJETO):
            comodines.append((indice, supresion))
        elif objetivo == sub.sujeto:
            exactas.append((indice, supresion))
    return exactas + comodines


def _suprimir(sub: ResultadoSubcheck, supresion: Supresion) -> ResultadoSubcheck:
    """Devuelve una copia SUPRIMIDA que sigue cargando el motivo original.

    El veredicto cambia, pero el hallazgo no se borra: la evidencia de la excepción se
    suma a la que ya había, para que el reporte pueda mostrar qué se dejó de contar.
    """
    motivo = (
        f"SUPRIMIDO hasta {supresion.vence.isoformat()} "
        f"por {supresion.autorizada_por}: {supresion.justificacion}"
    )
    if sub.motivo:
        motivo += f" · Hallazgo original: {sub.motivo}"

    evidencia = Evidencia(
        fuente="supresiones.yml",
        extracto=supresion.justificacion,
        detalle=(
            f"Excepción declarada para {supresion.sujeto or COMODIN_SUJETO}, "
            f"autorizada por {supresion.autorizada_por}, "
            f"vence {supresion.vence.isoformat()}."
        ),
    )
    return dataclasses.replace(
        sub,
        veredicto=Veredicto.SUPRIMIDO,
        evidencias=[*sub.evidencias, evidencia],
        motivo=motivo,
    )


def _cierre(
    supresiones: list[Supresion],
    dia: date,
    coincidencias: list[int],
    aplicaciones: list[int],
    bloqueadas: list[int],
) -> list[dict[str, Any]]:
    """Una entrada por cada supresión que NO terminó aplicando."""
    salida: list[dict[str, Any]] = []
    for indice, supresion in enumerate(supresiones):
        if not supresion.vigente(dia):
            dias = (dia - supresion.vence).days
            if bloqueadas[indice]:
                detalle = (
                    f"VENCIDA hace {dias} día(s): NO se aplicó y "
                    f"{bloqueadas[indice]} hallazgo(s) NO_CUMPLE vuelven a contar."
                )
            else:
                detalle = (
                    f"VENCIDA hace {dias} día(s): no se aplicó. "
                    "Renovarla con justificación o retirarla del archivo."
                )
            salida.append(_entrada(EVENTO_VENCIDA, supresion, detalle=detalle))
            continue

        if coincidencias[indice] == 0:
            salida.append(
                _entrada(
                    EVENTO_HUERFANA,
                    supresion,
                    detalle=(
                        "No coincidió con ningún sub-check evaluado: el control cambió "
                        "de nombre, o el sujeto ya no está en el alcance."
                    ),
                )
            )
            continue

        if aplicaciones[indice] == 0:
            salida.append(
                _entrada(
                    EVENTO_SIN_EFECTO,
                    supresion,
                    detalle=(
                        f"Coincidió con {coincidencias[indice]} sub-check(s) pero no "
                        "cambió ningún veredicto: o ya cumplían, o los cubrió una "
                        "supresión más específica. Probablemente ya sobra."
                    ),
                )
            )
    return salida


def _entrada(
    evento: str,
    supresion: Supresion,
    *,
    check_id: str = "",
    sujeto_afectado: str | None = None,
    detalle: str = "",
) -> dict[str, Any]:
    """Entrada del registro: serializable tal cual a JSON o a una tabla del reporte."""
    return {
        "evento": evento,
        "aviso": evento in EVENTOS_AVISO,
        "check": check_id,
        "subcheck": supresion.subcheck_id,
        "sujeto": supresion.sujeto or COMODIN_SUJETO,
        "sujeto_afectado": (
            sujeto_afectado if sujeto_afectado is not None else supresion.sujeto
        ),
        "justificacion": supresion.justificacion,
        "vence": supresion.vence.isoformat(),
        "autorizada_por": supresion.autorizada_por,
        "detalle": detalle,
    }


def _leer_supresion(entrada: Any, archivo: Path, posicion: int) -> Supresion:
    if not isinstance(entrada, dict):
        raise SupresionInvalida(
            f"{archivo}[{posicion}]: cada supresión debe ser un mapa, "
            f"se leyó {type(entrada).__name__}."
        )

    faltantes = [c for c in _CLAVES_OBLIGATORIAS if entrada.get(c) in (None, "")]
    if faltantes:
        raise SupresionInvalida(
            f"{archivo}[{posicion}]: faltan claves obligatorias: {', '.join(faltantes)}. "
            "Una supresión sin justificación, sin autoridad o sin vencimiento es una "
            "aprobación silenciosa."
        )

    subcheck = _cadena(entrada["subcheck"], archivo, posicion, "subcheck")
    justificacion = _cadena(entrada["justificacion"], archivo, posicion, "justificacion")
    autorizada_por = _cadena(entrada["autorizada_por"], archivo, posicion, "autorizada_por")

    sujeto_crudo = entrada.get("sujeto", COMODIN_SUJETO)
    if not isinstance(sujeto_crudo, str):
        raise SupresionInvalida(
            f"{archivo}[{posicion}]: 'sujeto' debe ser una cadena, se leyó {sujeto_crudo!r}."
        )

    return Supresion(
        subcheck_id=subcheck,
        sujeto=sujeto_crudo.strip(),
        justificacion=justificacion,
        vence=_fecha(entrada["vence"], archivo, posicion),
        autorizada_por=autorizada_por,
    )


def _cadena(valor: Any, archivo: Path, posicion: int, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise SupresionInvalida(
            f"{archivo}[{posicion}]: '{campo}' debe ser una cadena no vacía, "
            f"se leyó {valor!r}."
        )
    return valor.strip()


def _fecha(valor: Any, archivo: Path, posicion: int) -> date:
    """PyYAML ya entrega `date` si la fecha va sin comillas; si va entrecomillada, llega
    como cadena ISO. Se aceptan ambas para no castigar el estilo de escritura."""
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError as exc:
            raise SupresionInvalida(
                f"{archivo}[{posicion}]: 'vence' no es una fecha ISO (AAAA-MM-DD): "
                f"{valor!r}."
            ) from exc
    raise SupresionInvalida(
        f"{archivo}[{posicion}]: 'vence' debe ser una fecha ISO (AAAA-MM-DD), "
        f"se leyó {valor!r}."
    )
