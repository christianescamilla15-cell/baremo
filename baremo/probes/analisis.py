"""Sonda `entrega.check-que-analiza`: un escaneo que terminó no es un escaneo que analizó.

Lección de producción: escaneos de seguridad «verdes» durante semanas que sólo subían
el paquete y no analizaban un solo archivo. El paso terminaba con 0 porque no había
nada que reprobar. Un check que pasa por no mirar es la patología (c) de este proyecto
dentro del propio pipeline.

Por cada JOB de GitHub Actions que invoca un escáner de seguridad, cada herramienta del
job debe probar que miró algo, de una de dos formas:

  1. Un paso del mismo job verifica el reporte: llama a un verificador de reportes
     (`verificar_reportes …`) o afirma sobre el archivo (`jq -e`, `test -s`, `[ -s …]`,
     `grep -q`) mencionando la herramienta o el archivo que ella escribió. Una
     verificación que no puede fallar no es verificación: no cuenta si el paso tiene
     `continue-on-error: true` ni si la línea termina en `|| true`.
  2. La herramienta falla SOLA cuando no analiza nada. Es una lista corta y cada
     entrada declara por qué (ver HERRAMIENTAS_QUE_FALLAN_VACIAS).

Sin flujos de GitHub Actions, o sin escaneos en ellos, la sonda devuelve NO_MEDIBLE: la
ausencia de escaneos ya la castigan las sondas de seguridad, y reprobarla aquí otra vez
sería contar dos veces el mismo hueco.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.probes import Contexto, Sonda, recortar, registrar, subcheck, sujeto_de

PATRONES_WORKFLOW: tuple[str, ...] = (".github/workflows/*.y*ml",)
PATRONES_OTRAS_FORJAS: tuple[str, ...] = (
    ".gitlab-ci.yml", ".gitlab-ci.yaml", "Jenkinsfile", "azure-pipelines*.y*ml",
)

#: (herramienta, patrón sobre `uses:`, patrón sobre las líneas de `run:`)
ESCANERES: tuple[tuple[str, re.Pattern[str] | None, re.Pattern[str] | None], ...] = (
    ("codeql", re.compile(r"github/codeql-action/analyze"), re.compile(r"\bcodeql\s+database\s+analyze\b")),
    ("semgrep", re.compile(r"(?:returntocorp|semgrep)/semgrep-action"),
     re.compile(r"\bsemgrep\s+(?:scan|ci|--config)\b")),
    ("trivy", re.compile(r"aquasecurity/trivy-action"),
     re.compile(r"\btrivy\s+(?:fs|filesystem|image|config|repo|rootfs|sbom|k8s)\b")),
    ("gitleaks", re.compile(r"gitleaks/gitleaks-action"),
     re.compile(r"\bgitleaks\s+(?:detect|git|dir|protect|stdin)\b")),
    ("sbom", re.compile(r"anchore/sbom-action"), re.compile(r"\bsyft\s+(?:scan\s+|packages\s+)?\S")),
    ("grype", re.compile(r"anchore/scan-action"), re.compile(r"\bgrype\s+\S")),
    ("bandit", None, re.compile(r"\bbandit\s+-")),
    ("pip-audit", re.compile(r"pypa/gh-action-pip-audit"), re.compile(r"\bpip-audit\b")),
    ("npm-audit", None, re.compile(r"\b(?:npm|yarn|pnpm)\s+audit\b")),
    ("osv-scanner", re.compile(r"google/osv-scanner-action"), re.compile(r"\bosv-scanner\b")),
    ("checkov", re.compile(r"bridgecrewio/checkov-action"), re.compile(r"\bcheckov\s+-")),
    ("snyk", re.compile(r"snyk/actions"), re.compile(r"\bsnyk\s+(?:test|code|iac|container)\b")),
    ("zap", re.compile(r"zaproxy/action-"), None),
    ("dependency-check", re.compile(r"dependency-check/Dependency-Check_Action"),
     re.compile(r"\bdependency-check(?:\.sh)?\s+-")),
    ("confidencialidad", None, re.compile(r"\bconfidencialidad\.py\b")),
)

#: Herramientas que fallan solas cuando no analizan nada, con el porqué declarado.
HERRAMIENTAS_QUE_FALLAN_VACIAS: dict[str, str] = {
    "codeql": ("CodeQL termina con error («no source code was seen during the build», "
               "código 32) cuando no extrae ningún archivo del lenguaje configurado"),
    "confidencialidad": ("confidencialidad.py sale con 2 si no hay lista de términos o si "
                         "no revisó ningún archivo versionado"),
}

_RE_VERIFICADOR = re.compile(r"(?i)verificar[_-]?reportes?|verify[_-]?reports?")
_RE_AFIRMACION = re.compile(
    r"(?:\bjq\s+(?:-\w*\s+)*-\w*e|\btest\s+-s\b|\[\[?\s+-s\s|\bgrep\s+(?:-\w+\s+)*-\w*q)"
)
_RE_ARCHIVO_REPORTE = re.compile(r"[\w./-]+\.(?:json|sarif|xml|log|txt|csv|spdx|cdx)\b")


@dataclass
class Paso:
    indice: int
    uses: str
    run: str
    con: dict[str, Any]
    puede_fallar: bool


@dataclass
class Escaneo:
    herramienta: str
    paso: Paso
    archivos: set[str] = field(default_factory=set)


def _pasos(job: dict[str, Any]) -> list[Paso]:
    pasos: list[Paso] = []
    for indice, paso in enumerate(job.get("steps") or []):
        if not isinstance(paso, dict):
            continue
        con = paso.get("with") if isinstance(paso.get("with"), dict) else {}
        continuar = paso.get("continue-on-error")
        pasos.append(Paso(
            indice=indice,
            uses=str(paso.get("uses") or ""),
            run=str(paso.get("run") or ""),
            con=con,
            puede_fallar=not (continuar is True or str(continuar).lower() == "true"),
        ))
    return pasos


def _escaneos(pasos: Iterable[Paso]) -> list[Escaneo]:
    hallados: list[Escaneo] = []
    for paso in pasos:
        for herramienta, patron_uses, patron_run in ESCANERES:
            casa_uses = bool(patron_uses and paso.uses and patron_uses.search(paso.uses))
            casa_run = bool(patron_run and paso.run and patron_run.search(paso.run))
            if not (casa_uses or casa_run):
                continue
            texto = paso.run + "\n" + "\n".join(str(v) for v in paso.con.values())
            hallados.append(Escaneo(herramienta, paso, set(_RE_ARCHIVO_REPORTE.findall(texto))))
    return hallados


def _verificacion(escaneo: Escaneo, pasos: Iterable[Paso]) -> tuple[Paso, str] | None:
    """Paso y línea que verifican el reporte de la herramienta, si existen."""
    claves = {escaneo.herramienta} | escaneo.archivos
    for paso in pasos:
        if not paso.puede_fallar or not paso.run:
            continue
        for linea in paso.run.splitlines():
            limpia = linea.strip()
            if not limpia or limpia.startswith("#") or re.search(r"\|\|\s*true\s*$", limpia):
                continue
            if paso is escaneo.paso and any(
                    p and p.search(limpia) for _, _, p in ESCANERES):
                continue            # la línea del escaneo no se verifica a sí misma
            if not (_RE_VERIFICADOR.search(limpia) or _RE_AFIRMACION.search(limpia)):
                continue
            if any(clave.lower() in limpia.lower() for clave in claves):
                return paso, limpia
    return None


def _linea_de(texto: str, aguja: str, desde: int = 1) -> int:
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if numero >= desde and aguja and aguja in linea:
            return numero
    return desde


@registrar("entrega.check-que-analiza")
class SondaCheckQueAnaliza(Sonda):
    """Por cada job de GitHub Actions que invoca un escáner de seguridad (CodeQL,
    Semgrep, Trivy, gitleaks, syft, grype, bandit, pip-audit, npm audit, OSV,
    Checkov, Snyk, ZAP, dependency-check, confidencialidad), cada herramienta del job
    debe probar que analizó algo: un paso que verifica su reporte (verificador de
    reportes, jq -e, test -s, grep -q) y que PUEDE fallar, o una herramienta que falla
    sola con cero archivos (lista declarada). Sin escaneos: NO_MEDIBLE."""

    titulo = "Los escaneos de seguridad prueban que analizaron algo"
    eje = "Entrega y operación"
    peso = 1.0
    descripciones = {
        "ANALISIS_VERIFICADO": "Cada escaneo del job verifica que su reporte tenga resultados",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        id_sub, desc = "ANALISIS_VERIFICADO", self.descripciones["ANALISIS_VERIFICADO"]
        flujos = ctx.buscar(PATRONES_WORKFLOW)
        if not flujos:
            otras = ctx.buscar(PATRONES_OTRAS_FORJAS)
            motivo = (
                ("Hay definiciones de pipeline de otra forja ("
                 + ", ".join(ctx.rel(o) for o in otras[:3]) + ") que esta sonda no sabe leer; "
                 "haría falta un lector de ese formato.") if otras else
                ("No hay flujos de GitHub Actions: no existen escaneos cuya verificación "
                 "medir. La ausencia de escaneos ya la miden las sondas de seguridad.")
            )
            return self._check([subcheck(id_sub, desc, Veredicto.NO_MEDIBLE,
                                         sujeto_de(ctx, "pipeline", "escaneos"), motivo=motivo)])

        subchecks: list[ResultadoSubcheck] = []
        for ruta in flujos:
            subchecks.extend(self._flujo(ctx, ruta))
        if not subchecks:
            return self._check([subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_de(ctx, "pipeline", "escaneos"),
                motivo=(f"{len(flujos)} flujos leídos sin ningún escáner de seguridad reconocido "
                        f"({', '.join(h for h, *_ in ESCANERES)}): no hay escaneos cuya "
                        f"verificación medir."),
            )])
        return self._check(subchecks)

    def _flujo(self, ctx: Contexto, ruta: Path) -> list[ResultadoSubcheck]:
        id_sub, desc = "ANALISIS_VERIFICADO", self.descripciones["ANALISIS_VERIFICADO"]
        texto = ctx.leer(ruta)
        rel = ctx.rel(ruta)
        if texto is None:
            return [subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_de(ctx, "flujo", rel),
                             motivo=f"{rel} no pudo leerse como texto.")]
        try:
            datos = yaml.safe_load(texto)
        except yaml.YAMLError as exc:
            return [subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_de(ctx, "flujo", rel),
                             motivo=recortar(f"{rel} no es YAML válido: {exc}", 300))]
        jobs = datos.get("jobs") if isinstance(datos, dict) else None
        if not isinstance(jobs, dict):
            return []
        resultado: list[ResultadoSubcheck] = []
        for nombre, job in jobs.items():
            if not isinstance(job, dict):
                continue
            pasos = _pasos(job)
            escaneos = _escaneos(pasos)
            if not escaneos:
                continue
            resultado.append(self._job(ctx, ruta, texto, str(nombre), pasos, escaneos))
        return resultado

    def _job(self, ctx: Contexto, ruta: Path, texto: str, nombre: str,
             pasos: list[Paso], escaneos: list[Escaneo]) -> ResultadoSubcheck:
        id_sub, desc = "ANALISIS_VERIFICADO", self.descripciones["ANALISIS_VERIFICADO"]
        rel = ctx.rel(ruta)
        sujeto = sujeto_de(ctx, "job", f"{rel}#{nombre}")
        inicio_job = _linea_de(texto, f"{nombre}:")
        verificadas: list[Evidencia] = []
        sin_verificar: list[Evidencia] = []
        vistas: set[str] = set()
        for escaneo in escaneos:
            if escaneo.herramienta in vistas:
                continue
            vistas.add(escaneo.herramienta)
            aguja = escaneo.paso.uses or escaneo.paso.run.strip().splitlines()[0]
            linea_escaneo = _linea_de(texto, aguja, inicio_job)
            if escaneo.herramienta in HERRAMIENTAS_QUE_FALLAN_VACIAS:
                verificadas.append(Evidencia(
                    fuente=rel, extracto=recortar(aguja),
                    detalle=(f"línea {linea_escaneo} · {escaneo.herramienta}: "
                             f"{HERRAMIENTAS_QUE_FALLAN_VACIAS[escaneo.herramienta]}"),
                ))
                continue
            hallada = _verificacion(escaneo, pasos)
            if hallada:
                _, linea = hallada
                verificadas.append(Evidencia(
                    fuente=rel, extracto=recortar(linea),
                    detalle=(f"línea {_linea_de(texto, linea, inicio_job)} · verifica el "
                             f"reporte de {escaneo.herramienta}"),
                ))
            else:
                sin_verificar.append(Evidencia(
                    fuente=rel, extracto=recortar(aguja),
                    detalle=(f"línea {linea_escaneo} · {escaneo.herramienta} sin verificación "
                             f"de su reporte: el paso puede terminar en verde sin analizar nada"),
                ))
        if sin_verificar:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                            (sin_verificar + verificadas)[:10])
        return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto, verificadas[:10])
