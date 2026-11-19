"""Sonda `seguridad.confidencialidad` (N12): ningún archivo versionado menciona un término vetado.

Misma lógica que `herramientas/confidencialidad.py` de la plantilla común:

  · La lista NO vive en el repositorio, ni siquiera como huellas (un término corto se
    recupera por fuerza bruta). Llega por la variable de entorno CONFIDENCIAL_TERMINOS
    o, si está vacía, de ~/.config/confidencial/terminos.txt. Una expresión regular por
    línea, sin distinguir mayúsculas; las líneas vacías y las que empiezan con «#» no
    son reglas.
  · Se revisan los archivos VERSIONADOS (`git ls-files`); si el sujeto no es un
    repositorio de Git, el árbol de trabajo completo, y la evidencia lo dice.
  · La evidencia NUNCA incluye el término ni la línea donde aparece: sólo archivo,
    número de línea y número de regla. Los registros de un repositorio público son
    públicos, y un informe que repite el término lo publica.
  · Sin lista, o sin un solo archivo revisado, el veredicto es NO_MEDIBLE: no se
    aprueba por no mirar.

El sujeto es el repositorio entero, a propósito: un hallazgo en uno de trescientos
archivos no es «99.7 % confidencial», es una fuga.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.probes import Contexto, Sonda, registrar, subcheck

VARIABLE: str = "CONFIDENCIAL_TERMINOS"
#: Ruta de la lista local. Se lee en tiempo de ejecución, igual que la herramienta.
LISTA_LOCAL: Path = Path.home() / ".config" / "confidencial" / "terminos.txt"
MAXIMO_EVIDENCIAS: int = 20


class ReglaInvalida(Exception):
    def __init__(self, numero: int) -> None:
        super().__init__(numero)
        self.numero = numero


def cargar_reglas(lista_local: Path | None = None) -> tuple[list[re.Pattern[str]], str]:
    """(reglas compiladas, origen legible). Nunca devuelve ni imprime los términos."""
    local = lista_local if lista_local is not None else LISTA_LOCAL
    texto = os.environ.get(VARIABLE) or ""
    origen = f"variable de entorno {VARIABLE}"
    if not texto:
        origen = "lista local (~/.config/confidencial/terminos.txt)"
        try:
            texto = local.read_text(encoding="utf-8") if local.is_file() else ""
        except OSError:
            texto = ""
    reglas: list[re.Pattern[str]] = []
    for linea in texto.splitlines():
        if not linea.strip() or linea.startswith("#"):
            continue
        try:
            reglas.append(re.compile(linea.strip(), re.IGNORECASE))
        except re.error as exc:
            raise ReglaInvalida(len(reglas) + 1) from exc
    return reglas, origen


def _archivos_versionados(ctx: Contexto) -> tuple[list[str], str]:
    try:
        proceso = subprocess.run(
            ["git", "-C", str(ctx.ruta_repo), "ls-files", "-z"],
            capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        proceso = None
    if proceso is not None and proceso.returncode == 0:
        return [a for a in proceso.stdout.decode("utf-8", "replace").split("\0") if a], "git ls-files"
    return [ctx.rel(a) for a in ctx.archivos], "árbol de trabajo (el sujeto no es un repositorio de Git)"


@registrar("seguridad.confidencialidad")
class SondaConfidencialidad(Sonda):
    """Revisa cada archivo versionado (git ls-files) contra la lista de términos vetados
    (variable CONFIDENCIAL_TERMINOS o ~/.config/confidencial/terminos.txt; una
    expresión regular por línea). La evidencia sólo dice archivo, línea y número de
    regla: nunca el término. Sin lista o sin archivos revisados: NO_MEDIBLE."""

    titulo = "Sin datos confidenciales de terceros en el repositorio"
    eje = "Seguridad"
    peso = 1.0
    descripciones = {
        "CONFIDENCIALIDAD": "Ningún archivo versionado menciona un término de la lista vetada",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        return self._check([self._revisar(ctx)])

    def _revisar(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "CONFIDENCIALIDAD", self.descripciones["CONFIDENCIALIDAD"]
        sujeto = ctx.nombre_sujeto
        try:
            reglas, origen = cargar_reglas()
        except ReglaInvalida as exc:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"La regla #{exc.numero} de la lista no es una expresión regular "
                        f"válida: no se puede afirmar la ausencia de ese término. Haría falta "
                        f"corregir la lista (el término no se imprime)."),
            )
        if not reglas:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"No hay lista de términos vetados (variable {VARIABLE} vacía y sin "
                        f"~/.config/confidencial/terminos.txt): sin lista no se puede afirmar "
                        f"que el repositorio no mencione a un tercero."),
            )
        archivos, como = _archivos_versionados(ctx)
        hallazgos: list[tuple[str, int, int]] = []
        revisados = 0
        for relativa in archivos:
            ruta = ctx.ruta_repo / relativa
            try:
                datos = ruta.read_bytes()
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                continue
            if b"\0" in datos[:8192]:
                continue                    # binario
            revisados += 1
            for numero, linea in enumerate(datos.decode("utf-8", "replace").splitlines(), start=1):
                for k, regla in enumerate(reglas, start=1):
                    if regla.search(linea):
                        hallazgos.append((relativa, numero, k))
        resumen = (f"{revisados} archivos revisados con {len(reglas)} reglas · "
                   f"{len(hallazgos)} hallazgos")
        detalle = f"lista: {origen} · archivos: {como}"
        if revisados == 0:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=f"No se revisó ningún archivo ({como}): no se aprueba por no mirar.",
            )
        if hallazgos:
            evidencias = [Evidencia(fuente=".", extracto=resumen, detalle=detalle)]
            evidencias += [
                Evidencia(fuente=archivo, extracto=f"línea {numero} · regla #{k}",
                          detalle="el término no se imprime: el informe de un repo público es público")
                for archivo, numero, k in hallazgos[:MAXIMO_EVIDENCIAS]
            ]
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto, evidencias)
        return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto,
                        [Evidencia(fuente=".", extracto=resumen, detalle=detalle)])
