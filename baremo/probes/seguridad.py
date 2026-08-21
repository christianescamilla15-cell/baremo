"""Sonda «seguridad»: política, excepciones y escaneo declarado.

Dos correcciones deliberadas viven aquí:

  1. SEC_PROCESO_EXCEPCIONES es MULTILINGÜE. Un check que sólo reconoce
     'exception|waiver|suppress|false positive' reprueba a un equipo que
     documenta impecablemente su proceso en otro idioma. Ese falso negativo no
     mide madurez: mide el idioma del que escribió el check.
  2. La búsqueda NUNCA entra a directorios de dependencias. Aprobar un check de
     política porque `node_modules/<paquete>/SECURITY.md` menciona «waiver» es
     un falso positivo clásico: se estaría midiendo a un tercero.
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

#: Dónde puede vivir la política de seguridad.
PATRONES_POLITICA: tuple[str, ...] = (
    "SECURITY.md", "SECURITY.rst",
    ".github/SECURITY.md", ".github/SECURITY.rst",
    "docs/SECURITY.md", "docs/SECURITY.rst",
)

#: Documentación adicional donde el proceso de excepciones puede estar descrito.
PATRONES_DOCS = ("docs/*.md", "docs/*.rst", "docs/*/*.md", "docs/*/*.rst",
                 "CONTRIBUTING.md", "README.md")

#: Vocabulario del proceso de excepciones, en dos idiomas a propósito.
RE_EXCEPCIONES = re.compile(
    r"(?i)\b("
    r"exceptions?|waivers?|suppress(?:ion|ions|ed|ing)?|false[\s-]positives?|risk[\s-]accept\w*"
    r"|excepci[oó]n(?:es)?|exenci[oó]n(?:es)?|falsos?[\s-]positivos?|supresi[oó]n(?:es)?"
    r"|aceptaci[oó]n\s+de\s+riesgo"
    r")\b"
)

#: Segmentos de ruta de código de terceros. El barrido ya los poda; este filtro
#: es explícito para que la regla sea legible en el propio check.
SEGMENTOS_DE_TERCEROS: tuple[str, ...] = (
    "node_modules", "vendor", ".venv", "venv", "site-packages",
)

#: Manifiestos de dependencias: sin manifiesto no hay nada que escanear.
PATRONES_MANIFIESTO: tuple[str, ...] = (
    "requirements*.txt", "pyproject.toml", "Pipfile", "poetry.lock",
    "package.json", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "Cargo.toml", "composer.json", "*.csproj",
)

#: Configuración declarada de escaneo de dependencias.
PATRONES_ESCANEO_DEPS: tuple[str, ...] = (
    ".github/dependabot.y*ml", "dependabot.y*ml",
    "renovate.json", "renovate.json5", ".renovaterc", ".renovaterc.json",
    ".github/renovate.json",
)

#: Auditoría de dependencias invocada desde el pipeline.
RE_AUDITORIA_CI = re.compile(
    r"(?i)(npm\s+audit|yarn\s+audit|pnpm\s+audit|pip-audit|safety\s+check"
    r"|osv-scanner|dependency-check|dependency-review|bundler-audit"
    r"|cargo\s+audit|govulncheck|dotnet\s+list\s+package\s+--vulnerable)"
)

#: Configuración de análisis estático, por archivo…
PATRONES_SAST_ARCHIVO: tuple[str, ...] = (
    ".semgrep.y*ml", "semgrep.y*ml", ".semgrep/*.y*ml",
    ".bandit", "bandit.y*ml", ".flake8-bandit",
    "sonar-project.properties", ".sonarcloud.properties",
    ".github/codeql/*.y*ml", ".github/codeql-config.y*ml",
)

#: …y por contenido del pipeline o de la configuración del proyecto.
RE_SAST_CONTENIDO = re.compile(
    r"(?i)(codeql|semgrep|bandit|sonar(?:qube|cloud|-scanner)?|gosec|brakeman"
    r"|spotbugs|\[tool\.bandit\])"
)


def _es_de_terceros(ruta_relativa: str) -> bool:
    partes = ruta_relativa.split("/")
    return any(segmento in partes for segmento in SEGMENTOS_DE_TERCEROS)


@registrar("seguridad")
class SondaSeguridad(Sonda):
    titulo = "Seguridad declarada del repositorio"
    eje = "Seguridad"
    peso = 1.0
    descripciones = {
        "SEC_POLITICA": "Existe una política de seguridad publicada",
        "SEC_PROCESO_EXCEPCIONES": "La documentación describe cómo se gestionan excepciones",
        "SEC_ESCANEO_DEPENDENCIAS": "Hay manifiesto de dependencias y escaneo configurado",
        "SEC_ANALISIS_ESTATICO": "Hay configuración de análisis estático de código",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        politicas = [p for p in ctx.buscar(PATRONES_POLITICA)
                     if not _es_de_terceros(ctx.rel(p))]
        pipelines = ctx.buscar((".github/workflows/*.y*ml", ".gitlab-ci.y*ml",
                                "Jenkinsfile", "azure-pipelines*.y*ml"))
        return self._check([
            self._politica(ctx, politicas),
            self._proceso_excepciones(ctx, politicas),
            self._escaneo_dependencias(ctx, pipelines),
            self._analisis_estatico(ctx, pipelines),
        ])

    # -- SEC_POLITICA -------------------------------------------------------

    def _politica(self, ctx: Contexto, politicas: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "SEC_POLITICA", self.descripciones["SEC_POLITICA"]
        if not politicas:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, list(PATRONES_POLITICA),
                                       detalle="excluidos los directorios de dependencias")],
            )
        ruta = politicas[0]
        texto = ctx.leer(ruta) or ""
        primera = next((l for l in texto.splitlines() if l.strip()), "(archivo vacío)")
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=primera.strip(),
                       detalle=f"{len(texto)} caracteres de política")],
        )

    # -- SEC_PROCESO_EXCEPCIONES -------------------------------------------

    def _proceso_excepciones(self, ctx: Contexto, politicas: list[Path]) -> ResultadoSubcheck:
        id_sub = "SEC_PROCESO_EXCEPCIONES"
        desc = self.descripciones[id_sub]

        candidatos = list(politicas)
        for ruta in ctx.buscar(PATRONES_DOCS):
            if ruta not in candidatos and not _es_de_terceros(ctx.rel(ruta)):
                candidatos.append(ruta)

        inspeccionados = 0
        for ruta in candidatos:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            inspeccionados += 1
            for numero, linea in enumerate(texto.splitlines(), start=1):
                casa = RE_EXCEPCIONES.search(linea)
                if casa:
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                        [evidencia_linea(
                            ctx, ruta, numero, linea,
                            detalle=(f"término «{casa.group(1)}» — el vocabulario se "
                                     f"reconoce en dos idiomas a propósito"))],
                    )

        if not politicas:
            # No hay política que inspeccionar: la ausencia ya la reporta
            # SEC_POLITICA. Aquí no se midió la propiedad, y eso se dice.
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=(f"No existe un documento de política de seguridad donde buscar el "
                        f"proceso de excepciones ({inspeccionados} documentos generales "
                        f"revisados sin resultado). Haría falta publicar SECURITY.md "
                        f"describiendo cómo se solicitan, autorizan y vencen las "
                        f"excepciones y los falsos positivos."),
            )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [Evidencia(
                fuente=ctx.rel(politicas[0]),
                extracto=f"{inspeccionados} documentos leídos sin describir el proceso",
                detalle=("se buscó vocabulario en dos idiomas: excepción/exención/falso "
                         "positivo/supresión y exception/waiver/suppression/false positive"),
            )],
        )

    # -- SEC_ESCANEO_DEPENDENCIAS ------------------------------------------

    def _escaneo_dependencias(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub = "SEC_ESCANEO_DEPENDENCIAS"
        desc = self.descripciones[id_sub]

        manifiestos = [m for m in ctx.buscar(PATRONES_MANIFIESTO)
                       if not _es_de_terceros(ctx.rel(m))]
        if not manifiestos:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No se encontró ningún manifiesto de dependencias, así que no hay "
                        "superficie que escanear ni forma de juzgar el control. Haría "
                        "falta declarar las dependencias en un manifiesto versionado "
                        "(requirements.txt, pyproject.toml, package.json, go.mod, pom.xml…)."),
            )

        evidencia_manifiesto = Evidencia(
            fuente=ctx.rel(manifiestos[0]),
            extracto=f"{len(manifiestos)} manifiestos de dependencias declarados",
            detalle="superficie a escanear",
        )

        configs = [c for c in ctx.buscar(PATRONES_ESCANEO_DEPS)
                   if not _es_de_terceros(ctx.rel(c))]
        if configs:
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                [evidencia_manifiesto,
                 Evidencia(fuente=ctx.rel(configs[0]),
                           extracto="configuración de actualización/escaneo de dependencias",
                           detalle="declarada en el repositorio")],
            )

        for ruta in pipelines:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            for numero, linea in enumerate(texto.splitlines(), start=1):
                if RE_AUDITORIA_CI.search(linea):
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                        [evidencia_manifiesto,
                         evidencia_linea(ctx, ruta, numero, linea,
                                         detalle="auditoría de dependencias en el pipeline")],
                    )

        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [evidencia_manifiesto,
             evidencia_de_ausencia(
                 ctx, list(PATRONES_ESCANEO_DEPS) + ["job de auditoría en el pipeline"],
                 detalle=f"{len(pipelines)} definiciones de pipeline revisadas")],
        )

    # -- SEC_ANALISIS_ESTATICO ---------------------------------------------

    def _analisis_estatico(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub = "SEC_ANALISIS_ESTATICO"
        desc = self.descripciones[id_sub]

        configs = [c for c in ctx.buscar(PATRONES_SAST_ARCHIVO)
                   if not _es_de_terceros(ctx.rel(c))]
        if configs:
            ruta = configs[0]
            texto = ctx.leer(ruta) or ""
            primera = next((l for l in texto.splitlines() if l.strip()),
                           "(archivo de configuración vacío)")
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                [Evidencia(fuente=ctx.rel(ruta), extracto=primera.strip(),
                           detalle="configuración de análisis estático versionada")],
            )

        # También cuenta si el pipeline o la configuración del proyecto lo invoca.
        fuentes = list(pipelines) + [p for p in ctx.buscar(("pyproject.toml", "tox.ini",
                                                            "setup.cfg", ".pre-commit-config.y*ml"))
                                     if not _es_de_terceros(ctx.rel(p))]
        for ruta in fuentes:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            for numero, linea in enumerate(texto.splitlines(), start=1):
                casa = RE_SAST_CONTENIDO.search(linea)
                if casa:
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                        [evidencia_linea(ctx, ruta, numero, linea,
                                         detalle=f"análisis estático «{casa.group(1)}»")],
                    )

        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [evidencia_de_ausencia(
                ctx, list(PATRONES_SAST_ARCHIVO) + ["invocación de SAST en el pipeline"],
                detalle=f"{len(fuentes)} archivos de pipeline y configuración revisados")],
        )
