"""Sonda «entrega»: empaquetado, ejecución y operación.

El sub-check ENT_IMAGEN_NO_ROOT es el ejemplo canónico de la tesis del
proyecto: si no hay Dockerfile, la respuesta correcta NO es «cumple» (nadie
demostró nada) ni «no cumple» (no hay imagen que corra como root) sino
NO_MEDIBLE. En un scorecard que promedia ausencias como aprobados, borrar el
Dockerfile subiría la nota.
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
    registrar,
    subcheck,
)

PATRONES_CONTENEDOR: tuple[str, ...] = (
    "Dockerfile", "Dockerfile.*", "*.Dockerfile", "Containerfile", "Containerfile.*",
)

#: Infraestructura como código, por archivo.
PATRONES_IAC: tuple[str, ...] = (
    "*.tf", "*.tfvars", "*.bicep",
    "cdk.json", "cdk.context.json",
    "template.yaml", "template.yml",
    "serverless.yml", "serverless.yaml",
    "docker-compose*.y*ml", "compose.y*ml",
    "Chart.yaml", "kustomization.y*ml",
    "*.tfstate.backup",
)

_RE_USER = re.compile(r"^\s*USER\s+(?P<usuario>\S+)", re.IGNORECASE)
_RE_SALUD = re.compile(
    r"(?i)(HEALTHCHECK\s|livenessProbe|readinessProbe|startupProbe|healthcheck\s*:"
    r"|/healthz|/livez|/readyz|/actuator/health|[\"'`/]health[\"'`/\s)]|/-/healthy)"
)
_USUARIOS_ROOT: frozenset[str] = frozenset({"root", "0", "0:0", "root:root"})


@registrar("entrega")
class SondaEntrega(Sonda):
    titulo = "Entrega y operación del servicio"
    eje = "Entrega y operación"
    peso = 1.0
    descripciones = {
        "ENT_CONTENEDOR": "El servicio se empaqueta como imagen de contenedor",
        "ENT_IMAGEN_NO_ROOT": "La imagen declara un usuario de ejecución no privilegiado",
        "ENT_SALUD": "Hay una comprobación de salud declarada",
        "ENT_IAC": "La infraestructura está declarada como código",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        dockerfiles = ctx.buscar(PATRONES_CONTENEDOR)
        return self._check([
            self._contenedor(ctx, dockerfiles),
            self._imagen_no_root(ctx, dockerfiles),
            self._salud(ctx, dockerfiles),
            self._iac(ctx),
        ])

    # -- ENT_CONTENEDOR -----------------------------------------------------

    def _contenedor(self, ctx: Contexto, dockerfiles: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "ENT_CONTENEDOR", self.descripciones["ENT_CONTENEDOR"]
        if not dockerfiles:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, list(PATRONES_CONTENEDOR))],
            )
        evidencias: list[Evidencia] = []
        for ruta in dockerfiles[:5]:
            texto = ctx.leer(ruta) or ""
            base = next((l.strip() for l in texto.splitlines()
                         if l.strip().upper().startswith("FROM")), "(sin instrucción FROM)")
            evidencias.append(Evidencia(
                fuente=ctx.rel(ruta), extracto=base,
                detalle=f"{len(dockerfiles)} definiciones de imagen encontradas",
            ))
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, evidencias)

    # -- ENT_IMAGEN_NO_ROOT -------------------------------------------------

    def _imagen_no_root(self, ctx: Contexto, dockerfiles: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "ENT_IMAGEN_NO_ROOT", self.descripciones["ENT_IMAGEN_NO_ROOT"]
        if not dockerfiles:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No hay Dockerfile ni Containerfile: no existe imagen cuyo usuario "
                        "de ejecución medir. Haría falta la definición de la imagen, o "
                        "declarar el sujeto como no contenedorizado en el alcance."),
            )

        buenos: list[Evidencia] = []
        malos: list[Evidencia] = []
        indeterminados: list[str] = []

        for ruta in dockerfiles:
            texto = ctx.leer(ruta)
            if texto is None:
                indeterminados.append(f"{ctx.rel(ruta)} (ilegible)")
                continue
            # Se toma la ÚLTIMA instrucción USER: en una construcción multietapa
            # es la que gobierna la imagen final. Es una heurística y se declara.
            ultima: tuple[int, str, str] | None = None
            for numero, linea in enumerate(texto.splitlines(), start=1):
                casa = _RE_USER.match(linea)
                if casa:
                    ultima = (numero, linea, casa.group("usuario"))
            if ultima is None:
                malos.append(Evidencia(
                    fuente=ctx.rel(ruta),
                    extracto="ninguna instrucción USER en el archivo",
                    detalle="sin USER la imagen corre como root",
                ))
                continue
            numero, linea, usuario = ultima
            if usuario.startswith("$") or "${" in usuario:
                indeterminados.append(f"{ctx.rel(ruta)}:{numero} USER {usuario}")
            elif usuario.lower() in _USUARIOS_ROOT:
                malos.append(evidencia_linea(ctx, ruta, numero, linea,
                                             detalle="última instrucción USER: privilegiada"))
            else:
                buenos.append(evidencia_linea(ctx, ruta, numero, linea,
                                              detalle="última instrucción USER: no privilegiada"))

        if malos:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto, malos[:10])
        if indeterminados:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("El usuario de ejecución se resuelve por variable de construcción y "
                        "no puede juzgarse en estático: " + "; ".join(indeterminados[:5]) +
                        ". Para medirlo haría falta el valor efectivo del argumento "
                        "(bitácora de construcción) o fijar el usuario literalmente."),
            )
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, buenos[:5])

    # -- ENT_SALUD ----------------------------------------------------------

    def _salud(self, ctx: Contexto, dockerfiles: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "ENT_SALUD", self.descripciones["ENT_SALUD"]
        inspeccionados = 0
        for ruta in list(dockerfiles) + ctx.archivos_texto:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            inspeccionados += 1
            for numero, linea in enumerate(texto.splitlines(), start=1):
                if _RE_SALUD.search(linea):
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                        [evidencia_linea(ctx, ruta, numero, linea,
                                         detalle="comprobación de salud declarada")],
                    )
        if inspeccionados == 0:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No se pudo leer ningún archivo de texto del sujeto. Haría falta un "
                        "árbol de trabajo legible para buscar HEALTHCHECK, sondas de "
                        "liveness/readiness o una ruta de salud en el código."),
            )
        if ctx.barrido_truncado:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=(f"El barrido se truncó al alcanzar el tope de archivos "
                        f"({len(ctx.archivos)}): no se puede afirmar la ausencia de una "
                        f"comprobación de salud sobre un universo incompleto."),
            )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [evidencia_de_ausencia(
                ctx, ["HEALTHCHECK", "livenessProbe/readinessProbe", "healthcheck:",
                      "rutas /health, /healthz, /livez, /readyz"],
                detalle=f"{inspeccionados} archivos de texto inspeccionados")],
        )

    # -- ENT_IAC ------------------------------------------------------------

    def _iac(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "ENT_IAC", self.descripciones["ENT_IAC"]
        encontrados = ctx.buscar(PATRONES_IAC)
        if encontrados:
            ruta = encontrados[0]
            texto = ctx.leer(ruta) or ""
            primera = next((l for l in texto.splitlines() if l.strip()), "(archivo vacío)")
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                [Evidencia(fuente=ctx.rel(ruta), extracto=primera.strip(),
                           detalle=f"{len(encontrados)} archivos de infraestructura como código")],
            )

        # Manifiestos de orquestación: se reconocen por contenido, no por nombre.
        for ruta in ctx.buscar(("*.yaml", "*.yml")):
            relativa = ctx.rel(ruta)
            if relativa.startswith(".github/workflows/"):
                continue
            texto = ctx.leer(ruta)
            if not texto or "apiVersion:" not in texto or "kind:" not in texto:
                continue
            numero, linea = next(
                ((n, l) for n, l in enumerate(texto.splitlines(), start=1)
                 if l.startswith("kind:")), (1, "kind:"),
            )
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                [evidencia_linea(ctx, ruta, numero, linea,
                                 detalle="manifiesto de orquestación (apiVersion + kind)")],
            )

        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [evidencia_de_ausencia(ctx, list(PATRONES_IAC) + ["manifiestos apiVersion/kind"])],
        )
