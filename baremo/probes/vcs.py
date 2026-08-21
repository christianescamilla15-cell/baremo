"""Sonda «vcs»: higiene del control de versiones.

Mide cuatro cosas del árbol de trabajo: que los artefactos no se versionen, que
haya propiedad declarada del código, que no viajen secretos REALES y que la
protección de la rama por defecto esté declarada como dato.

Dos correcciones deliberadas frente a los scorecards habituales:

  1. VCS_SIN_SECRETOS busca por VALOR, no por NOMBRE de variable (ver la nota
     larga sobre falsos positivos más abajo).
  2. VCS_RAMA_DEFECTO no aprueba ni reprueba cuando la protección vive en la
     forja: devuelve NO_MEDIBLE y dice qué haría falta. Un check que reprueba
     por no poder mirar empuja a apagar el check; uno que aprueba por no poder
     mirar convierte la nota en ficción.
"""
from __future__ import annotations

import re
from pathlib import Path

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.probes import (
    Contexto,
    Sonda,
    evidencia_de_ausencia,
    evidencia_linea,
    recortar,
    registrar,
    subcheck,
)

# --------------------------------------------------------------------------
# Detección de secretos POR VALOR
# --------------------------------------------------------------------------
#
# ⚠️ NOTA SOBRE UN FALSO POSITIVO CLÁSICO ⚠️
#
# La mayoría de los detectores de secretos marcan por NOMBRE: cualquier
# identificador que contenga «secret», «key», «token» o «password» se reporta
# como hallazgo. Eso reprueba precisamente a quien nombra bien sus cosas:
#
#     EnableSecretRotation: true          ← una BANDERA de configuración
#     KmsKeySecretsArn: <identificador>   ← el NOMBRE de dónde vive el secreto
#     SECRET_NAME=credencial-de-app       ← una referencia, no la credencial
#
# Ninguno de esos es un secreto: son metadatos. Marcarlos genera ruido, el
# equipo aprende a ignorar el reporte y el hallazgo real se pierde entre cien
# falsos. Por eso esta sonda NO mira nombres de variables en absoluto: sólo
# reconoce VALORES con forma de credencial (cabeceras PEM, prefijos de token
# publicados, cadenas de conexión con la contraseña embebida).
#
# El precio de esta decisión es real y se declara: un secreto con forma
# arbitraria (una contraseña corta y sin prefijo) NO se detecta. Este check
# mide "no hay credenciales con forma reconocible", no "no hay secretos".

#: Nombres que NO son secretos aunque lo parezcan. Se conservan como
#: documentación viva del falso positivo y como red defensiva.
NOMBRES_QUE_NO_SON_SECRETO: tuple[str, ...] = (
    "EnableSecretRotation",
    "KmsKeySecretsArn",
    "SecretsManagerArn",
    "SECRET_NAME",
    "secretArn",
    "secretRef",
    "TOKEN_URL",
    "api_key_name",
)

#: (etiqueta legible, patrón del VALOR).
PATRONES_SECRETO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("clave privada en formato PEM",
     re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("token de forja con prefijo publicado (gh[posr]_)",
     re.compile(r"\bgh[posr]_[A-Za-z0-9]{30,}\b")),
    ("token de acceso personal de forja (github_pat_)",
     re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b")),
    ("token de mensajería con prefijo publicado (xox…)",
     re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}\b")),
    ("identificador de clave de acceso de nube (AKIA/ASIA)",
     re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("clave de API con prefijo estándar sk-",
     re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    ("cadena de conexión con contraseña embebida",
     re.compile(r"\b[a-z][a-z0-9+.-]{2,}://[^\s:@/]{1,64}:[^\s:@/]{1,64}@")),
    # Las dos siguientes exigen la ESTRUCTURA de una cadena de conexión
    # (pares `clave=valor` separados por `;`). Sin esa exigencia, el patrón
    # degenera en un check por nombre y marca cualquier asignación de código
    # —`password = os.getenv("X")`, `user, password = partir(url)`—, que fue
    # justamente el falso positivo que esta sonda existe para no cometer.
    ("contraseña embebida en cadena de conexión (clave=valor;…)",
     re.compile(r"(?i)(?:server|data\s*source|host|initial\s*catalog|database|uid|user\s*id)"
                r"\s*=\s*[^;=\s][^;]{0,64};[^\n]{0,200}?"
                r"\b(?:password|pwd)\s*=\s*(?P<valor>[^;\s'\"<>]{6,})")),
    ("contraseña embebida en cadena de conexión (…;clave=valor)",
     re.compile(r"(?i)\b(?:password|pwd)\s*=\s*(?P<valor>[^;\s'\"<>]{6,})\s*;[^\n]{0,200}?"
                r"(?:server|data\s*source|host|initial\s*catalog|database|uid|user\s*id)\s*=")),
)

#: Marcas de que el valor es un ejemplo o una referencia, no una credencial.
_MARCADORES = (
    "${", "$(", "{{", "%(", "<", ">", "changeme", "change_me", "example",
    "ejemplo", "placeholder", "redacted", "xxxx", "****", "your-", "tu-",
    "dummy", "sample", "fake", "os.environ", "getenv", "process.env",
    "secrets.", "vault:", "sops:", "todo",
)


def _es_marcador_de_posicion(linea: str, valor: str) -> bool:
    """¿El valor es un ejemplo, un hueco o una referencia a otro sistema?"""
    minus = f"{linea}\n{valor}".lower()
    return any(marca in minus for marca in _MARCADORES)


def _redactar(valor: str) -> str:
    """Nunca se copia el secreto al reporte: se muestra su forma, no su valor."""
    limpio = valor.strip()
    if len(limpio) <= 8:
        return "•" * len(limpio) + f" ({len(limpio)} caracteres)"
    return f"{limpio[:4]}…{'•' * 8}… ({len(limpio)} caracteres)"


def hallar_secretos(texto: str) -> list[tuple[int, str, str]]:
    """Busca valores con forma de credencial.

    Devuelve (número de línea, etiqueta del patrón, fragmento REDACTADO).
    Reutilizada por la sonda de integración continua.
    """
    hallazgos: list[tuple[int, str, str]] = []
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if len(linea) > 4096:            # línea minificada: ruido, no evidencia
            continue
        for etiqueta, patron in PATRONES_SECRETO:
            encontrado = patron.search(linea)
            if not encontrado:
                continue
            valor = encontrado.groupdict().get("valor") or encontrado.group(0)
            if _es_marcador_de_posicion(linea, valor):
                continue
            if any(nombre.lower() in valor.lower() for nombre in NOMBRES_QUE_NO_SON_SECRETO):
                continue                  # red defensiva del falso positivo por nombre
            hallazgos.append((numero, etiqueta, _redactar(valor)))
            break
    return hallazgos


# --------------------------------------------------------------------------
# Sonda
# --------------------------------------------------------------------------

#: Formas aceptadas en .gitignore para dar por excluido un artefacto.
def _normalizar_regla(linea: str) -> str:
    regla = linea.strip()
    if regla.startswith("**/"):
        regla = regla[3:]
    regla = regla.lstrip("/").rstrip("/")
    return regla


@registrar("vcs")
class SondaVcs(Sonda):
    titulo = "Higiene del control de versiones"
    eje = "Control de versiones"
    peso = 1.0
    descripciones = {
        "VCS_GITIGNORE": "Existe .gitignore y excluye los artefactos habituales",
        "VCS_CODEOWNERS": "Existe CODEOWNERS con al menos una regla de propiedad",
        "VCS_SIN_SECRETOS": "No hay valores con forma de credencial versionados",
        "VCS_RAMA_DEFECTO": "La protección de la rama por defecto está declarada",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        codeowners = ctx.buscar(["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"])
        return self._check([
            self._gitignore(ctx),
            self._codeowners(ctx, codeowners),
            self._sin_secretos(ctx),
            self._rama_defecto(ctx, codeowners),
        ])

    # -- VCS_GITIGNORE ------------------------------------------------------

    def _gitignore(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "VCS_GITIGNORE", self.descripciones["VCS_GITIGNORE"]
        artefactos: list[str] = list(ctx.convencion(
            "artefactos_gitignore", ["node_modules", "__pycache__", "dist", ".env"],
        ))  # type: ignore[arg-type]

        archivos = ctx.buscar([".gitignore"])
        raiz = [a for a in archivos if ctx.rel(a) == ".gitignore"]
        if not raiz:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, [".gitignore (en la raíz del sujeto)"])],
            )

        ruta = raiz[0]
        texto = ctx.leer(ruta)
        if texto is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("El .gitignore existe pero no pudo leerse como texto "
                        "(binario, ilegible o por encima del tope de tamaño). "
                        "Haría falta acceso de lectura al archivo."),
            )

        cubiertos: dict[str, tuple[int, str]] = {}
        for numero, linea in enumerate(texto.splitlines(), start=1):
            crudo = linea.strip()
            if not crudo or crudo.startswith("#") or crudo.startswith("!"):
                continue                   # comentario o negación: no excluye
            regla = _normalizar_regla(crudo)
            for artefacto in artefactos:
                if artefacto in cubiertos:
                    continue
                if regla == artefacto or regla == artefacto + "*" or regla == "*" + artefacto:
                    cubiertos[artefacto] = (numero, crudo)

        faltantes = [a for a in artefactos if a not in cubiertos]
        evidencias = [evidencia_linea(ctx, ruta, n, l, detalle=f"excluye «{a}»")
                      for a, (n, l) in cubiertos.items()]
        if faltantes:
            evidencias.append(Evidencia(
                fuente=ctx.rel(ruta),
                extracto=f"{len(texto.splitlines())} reglas leídas",
                detalle="sin regla para: " + ", ".join(faltantes),
            ))
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto, evidencias)
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, evidencias)

    # -- VCS_CODEOWNERS -----------------------------------------------------

    def _codeowners(self, ctx: Contexto, candidatos: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "VCS_CODEOWNERS", self.descripciones["VCS_CODEOWNERS"]
        if not candidatos:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, ["CODEOWNERS", ".github/CODEOWNERS",
                                             "docs/CODEOWNERS"])],
            )

        regla = re.compile(r"^\s*[^#\s]+\s+(?:@[\w./-]+|[\w.+-]+@[\w.-]+)")
        for ruta in candidatos:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            for numero, linea in enumerate(texto.splitlines(), start=1):
                if regla.match(linea):
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                        [evidencia_linea(ctx, ruta, numero, linea,
                                         detalle="regla de propiedad")],
                    )
        # Existe el archivo pero no declara ninguna propiedad: no cumple, y la
        # evidencia lo dice sin ambigüedad.
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [Evidencia(fuente=ctx.rel(candidatos[0]),
                       extracto="archivo presente sin reglas de propiedad legibles",
                       detalle="ninguna línea asigna una ruta a un propietario")],
        )

    # -- VCS_SIN_SECRETOS ---------------------------------------------------

    def _sin_secretos(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "VCS_SIN_SECRETOS", self.descripciones["VCS_SIN_SECRETOS"]
        inspeccionados = 0
        evidencias: list[Evidencia] = []
        for ruta in ctx.archivos_texto:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            inspeccionados += 1
            for numero, etiqueta, redactado in hallar_secretos(texto):
                evidencias.append(Evidencia(
                    fuente=ctx.rel(ruta),
                    extracto=f"{etiqueta}: {redactado}",
                    detalle=f"línea {numero} · valor redactado a propósito",
                ))
                if len(evidencias) >= 20:
                    break
            if len(evidencias) >= 20:
                break

        if evidencias:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto, evidencias)

        if inspeccionados == 0:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No se pudo leer ningún archivo de texto del sujeto. "
                        "Haría falta un árbol de trabajo con contenido legible "
                        "para poder afirmar que no hay credenciales versionadas."),
            )
        if ctx.barrido_truncado:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=(f"El barrido se truncó al alcanzar el tope de archivos "
                        f"({len(ctx.archivos)}). No se puede afirmar una ausencia "
                        f"sobre un universo que no se recorrió completo: haría falta "
                        f"correr el barrido sin tope."),
            )
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
            [Evidencia(
                fuente=ctx.rel(ctx.ruta_repo) or ".",
                extracto=(f"{inspeccionados} archivos de texto inspeccionados con "
                          f"{len(PATRONES_SECRETO)} patrones de VALOR"),
                detalle=("no se marca por nombre de variable: una bandera como "
                         "EnableSecretRotation no es un secreto"),
            )],
        )

    # -- VCS_RAMA_DEFECTO ---------------------------------------------------

    def _rama_defecto(self, ctx: Contexto, codeowners: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "VCS_RAMA_DEFECTO", self.descripciones["VCS_RAMA_DEFECTO"]

        declaraciones = ctx.buscar([
            ".github/branch-protection.y*ml",
            ".github/branch_protection.y*ml",
            ".github/rulesets/*.json",
            ".github/rulesets/*.y*ml",
            "*ruleset*.json",
            "*ruleset*.y*ml",
            "branch-protection.y*ml",
        ])
        for ruta in declaraciones:
            texto = ctx.leer(ruta)
            extracto = recortar(texto.splitlines()[0]) if texto and texto.strip() else "(archivo vacío)"
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                [Evidencia(fuente=ctx.rel(ruta), extracto=extracto,
                           detalle="protección de rama declarada como archivo versionado")],
            )

        # Camino alterno: propiedad declarada + un flujo que exige revisión.
        if codeowners:
            exige = re.compile(r"(?i)(codeowners|approv|revisi[oó]n|required[_-]?reviews?)")
            for ruta in ctx.buscar([".github/workflows/*.y*ml"]):
                texto = ctx.leer(ruta)
                if not texto or "pull_request" not in texto:
                    continue
                for numero, linea in enumerate(texto.splitlines(), start=1):
                    if exige.search(linea):
                        return subcheck(
                            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                            [Evidencia(fuente=ctx.rel(codeowners[0]),
                                       extracto="propiedad del código declarada",
                                       detalle="CODEOWNERS presente"),
                             evidencia_linea(ctx, ruta, numero, linea,
                                             detalle="flujo sobre pull_request que exige revisión")],
                        )

        # No hay nada declarado en el árbol: la protección real vive en la forja.
        # NO se inventa un aprobado ni se reprueba: no se pudo medir.
        return subcheck(
            id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
            motivo=(
                "La protección de la rama por defecto no está declarada en el árbol "
                "de trabajo y su estado real vive en la configuración de la forja, "
                "accesible sólo con credenciales. Para medirla haría falta una de dos "
                "cosas: (a) declararla como archivo versionado —ruleset o "
                "branch-protection— o (b) un token de sólo lectura de la forja para "
                "consultar la protección efectiva. Se buscó: "
                ".github/branch-protection.yml, .github/rulesets/*, archivos *ruleset*, "
                "y CODEOWNERS junto a un flujo de pull_request que exija revisión."
            ),
        )
