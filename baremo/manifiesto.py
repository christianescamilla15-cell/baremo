"""Manifiesto de la corrida: lo que hace REPRODUCIBLE un reporte de Baremo.

Un porcentaje de madurez sin manifiesto no es un dato, es una anécdota: nadie puede
repetir la medición ni explicar por qué el mismo repositorio dio 62% el martes y 78% el
jueves. El manifiesto responde, sin preguntar a nadie, las cuatro cosas de las que
depende el número:

  * **Con qué versión se midió.** Es el punto más caro y el más fácil de pasar por alto.
    Cuando un equipo mide con una copia desactualizada de la herramienta, las sondas no
    coinciden con las columnas del reporte consolidado: se comparan controles que ya
    cambiaron de significado y las tablas quedan CORRIDAS — una columna reporta lo que
    la otra llama distinto, y la diferencia se lee como si un equipo hubiera mejorado o
    empeorado. Por eso la versión de la herramienta viaja DENTRO del reporte y no en el
    correo que lo acompaña.
  * **Con qué configuración.** El hash sha256 de `baremo.yml` distingue dos corridas con
    el mismo comando y distinto alcance. Sin él, reducir el alcance es indetectable.
  * **Con qué excepciones.** El hash de `supresiones.yml` hace lo propio con las
    supresiones: cambiar el archivo cambia el número, así que el archivo se firma.
  * **Sobre qué sujetos.** Declarados, medidos y excluidos, por separado. La diferencia
    entre los tres es justamente lo que la cobertura penaliza.

Cuando un archivo no existe, su hash es la cadena `"sin-archivo"`: es un valor legítimo
y explícito, distinto de un hash vacío o de una clave ausente.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baremo.config import Configuracion
from baremo.model import Alcance

SIN_ARCHIVO = "sin-archivo"

# Nombres bajo los cuales se busca el registro de sondas. El manifiesto no impone la
# forma del registro: lo describe si está, y lo dice si no está.
_ATRIBUTOS_REGISTRO = ("SONDAS", "REGISTRO", "REGISTRO_DE_SONDAS", "SONDAS_REGISTRADAS")
_FUNCIONES_REGISTRO = ("listar_sondas", "sondas_registradas", "registro", "sondas")


def sha256_de_archivo(ruta: str | Path | None) -> str:
    """sha256 del CONTENIDO del archivo, o `"sin-archivo"` si no existe.

    Se hashea el contenido y no la ruta: mover el archivo no cambia la medición, editarlo
    sí. Se lee en binario para que el hash no dependa del final de línea del sistema.
    """
    if ruta is None:
        return SIN_ARCHIVO
    archivo = Path(ruta)
    if not archivo.is_file():
        return SIN_ARCHIVO
    digest = hashlib.sha256()
    with archivo.open("rb") as manejador:
        for bloque in iter(lambda: manejador.read(65536), b""):
            digest.update(bloque)
    return digest.hexdigest()


def construir_manifiesto(
    config: Configuracion,
    sujetos: Iterable[str],
    version_herramienta: str,
) -> dict[str, Any]:
    """Arma el manifiesto de una corrida.

    `sujetos` son los sujetos EFECTIVAMENTE medidos, que casi nunca coinciden con los
    declarados: esa brecha es un dato del reporte, no un detalle a limar.

    Devuelve un `dict` serializable tal cual a JSON (fechas y rutas ya como cadenas).
    """
    medidos = [str(s) for s in sujetos]
    declarados = list(config.sujetos)
    excluidos = dict(config.excluidos)

    alcance = Alcance(declarado=declarados, medido=medidos, excluido=excluidos)
    sondas = _sondas_del_manifiesto(config)

    manifiesto: dict[str, Any] = {
        "herramienta": {
            "nombre": "baremo",
            # Va aquí, en el reporte, y no en el correo: medir con una copia
            # desactualizada corre las columnas de las tablas comparativas.
            "version": version_herramienta,
        },
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "configuracion": {
            "ruta": str(config.ruta) if config.ruta else SIN_ARCHIVO,
            "sha256": sha256_de_archivo(config.ruta),
            "por_defecto": config.por_defecto,
            "version_esquema": config.version,
            "avisos": list(config.avisos),
        },
        "supresiones": {
            "ruta": str(config.ruta_supresiones),
            "sha256": sha256_de_archivo(config.ruta_supresiones),
        },
        "umbral_cobertura": config.umbral_cobertura,
        "convenciones": {
            "entornos": list(config.convenciones.entornos),
            "rama_principal": config.convenciones.rama_principal,
        },
        "sondas": sondas,
        "sujetos": {
            "declarados": declarados,
            "medidos": medidos,
            "excluidos": excluidos,
            # Lo declarado que no se midió ni se excluyó: la omisión que baja la cobertura.
            "omitidos_sin_declarar": alcance.omitido_sin_declarar,
            # Lo medido fuera del alcance declarado: también rompe la comparabilidad.
            "medidos_fuera_de_alcance": [
                s for s in medidos if declarados and s not in declarados
            ],
        },
    }
    manifiesto["advertencias"] = _advertencias(manifiesto, config)
    return manifiesto


def a_json(manifiesto: dict[str, Any], indentado: int = 2) -> str:
    """Serializa el manifiesto de forma estable, para poder diferenciar dos corridas."""
    return json.dumps(manifiesto, ensure_ascii=False, indent=indentado, sort_keys=True)


# --------------------------------------------------------------------------------------
# Interno
# --------------------------------------------------------------------------------------

def _sondas_del_manifiesto(config: Configuracion) -> list[dict[str, Any]]:
    """Sondas registradas (con su versión) más las que la configuración pesa.

    Una sonda a la que se le declaró peso pero que no está registrada NO se omite del
    manifiesto: aparece con `registrada: false`. Es el caso en que alguien cree estar
    ponderando un control que nadie ejecutó.
    """
    registradas = _registro_de_sondas()
    salida: list[dict[str, Any]] = []
    vistas: set[str] = set()

    for cruda in registradas:
        identificador, version = _describir_sonda(cruda)
        if not identificador or identificador in vistas:
            continue
        vistas.add(identificador)
        salida.append(
            {
                "id": identificador,
                "version": version,
                "peso": config.peso_de_sonda(identificador),
                "registrada": True,
            }
        )

    for nombre in config.sondas:
        if nombre in vistas:
            continue
        salida.append(
            {
                "id": nombre,
                "version": "desconocida",
                "peso": config.peso_de_sonda(nombre),
                "registrada": False,
            }
        )

    salida.sort(key=lambda s: s["id"])
    return salida


def _registro_de_sondas() -> list[Any]:
    """Busca el registro de sondas sin exigir que exista.

    El manifiesto tiene que poder armarse aunque el paquete de sondas todavía no esté
    disponible; en ese caso la lista simplemente queda vacía y las advertencias lo dicen.
    """
    try:
        modulo = importlib.import_module("baremo.probes")
    except Exception:  # pragma: no cover - depende del estado del paquete
        return []

    for atributo in _ATRIBUTOS_REGISTRO:
        valor = getattr(modulo, atributo, None)
        if isinstance(valor, dict):
            return list(valor.values())
        if isinstance(valor, (list, tuple, set)):
            return list(valor)

    for nombre in _FUNCIONES_REGISTRO:
        funcion = getattr(modulo, nombre, None)
        if not callable(funcion):
            continue
        try:
            resultado = funcion()
        except Exception:  # pragma: no cover - una sonda rota no tumba el manifiesto
            continue
        if isinstance(resultado, dict):
            return list(resultado.values())
        if isinstance(resultado, (list, tuple, set)):
            return list(resultado)

    return []


def _describir_sonda(cruda: Any) -> tuple[str, str]:
    """Extrae (id, versión) de una sonda, venga como dict, como objeto o como clase."""
    if isinstance(cruda, dict):
        identificador = cruda.get("id") or cruda.get("nombre") or ""
        version = cruda.get("version") or "desconocida"
        return str(identificador), str(version)

    for atributo in ("id", "nombre", "__name__"):
        identificador = getattr(cruda, atributo, None)
        if identificador:
            version = getattr(cruda, "version", None) or "desconocida"
            return str(identificador), str(version)

    return "", "desconocida"


def _advertencias(manifiesto: dict[str, Any], config: Configuracion) -> list[str]:
    """Lo que impide tomar este reporte como comparable con otro. Se dice de frente."""
    salida: list[str] = []

    if config.por_defecto:
        salida.append(
            "Se midió con la configuración por defecto: no hay alcance declarado contra "
            "el cual contrastar lo medido."
        )
    if manifiesto["configuracion"]["sha256"] == SIN_ARCHIVO and not config.por_defecto:
        salida.append(
            "No se pudo firmar la configuración: el archivo declarado no está en disco."
        )
    if manifiesto["supresiones"]["sha256"] == SIN_ARCHIVO:
        salida.append(
            "No hay archivo de supresiones: ninguna excepción se aplicó en esta corrida."
        )
    if not manifiesto["sondas"]:
        salida.append(
            "No se encontró ninguna sonda registrada: el reporte no mide nada todavía."
        )
    for sonda in manifiesto["sondas"]:
        if not sonda["registrada"]:
            salida.append(
                f"La sonda {sonda['id']!r} tiene peso declarado ({sonda['peso']}) pero no "
                "está registrada: se está ponderando un control que nadie ejecuta."
            )
    if manifiesto["sujetos"]["omitidos_sin_declarar"]:
        salida.append(
            "Sujetos declarados que no se midieron ni se excluyeron: "
            + ", ".join(manifiesto["sujetos"]["omitidos_sin_declarar"])
        )
    if manifiesto["sujetos"]["medidos_fuera_de_alcance"]:
        salida.append(
            "Sujetos medidos que no estaban declarados en el alcance: "
            + ", ".join(manifiesto["sujetos"]["medidos_fuera_de_alcance"])
        )
    return salida
