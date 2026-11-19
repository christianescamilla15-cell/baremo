"""Sondas de arquitectura (N01): diagramas C4 reales y registro de decisiones (ADR).

Sustancia antes que nombre:

  · Una carpeta `docs/arquitectura/` no acredita nada. Acredita un diagrama C4 que
    se puede LEER: un bloque Mermaid `C4Context` / `C4Container` / `C4Component` (o
    una vista de Structurizr DSL) con elementos del nivel, al menos dos elementos y
    al menos una relación. Un diagrama con huecos de plantilla —el nombre del sistema
    entre ángulos, la descripción «…»— es una plantilla, no un diagrama: no cuenta.
  · Un archivo `0001-algo.md` no acredita una decisión. Acredita un ADR con estado
    reconocible, contexto, decisión y consecuencias, cada uno con contenido.

El sujeto de `documentacion.arquitectura-c4` es el NIVEL C4 (contexto, contenedores,
componentes): tener dos de tres niveles vale 2/3, no «advertencia». El sujeto de
`documentacion.adr` es cada ADR.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.probes import (
    Contexto,
    Sonda,
    evidencia_de_ausencia,
    recortar,
    registrar,
    subcheck,
    sujeto_de,
)
from baremo.probes._apoyo import (
    bloques_cercados,
    lineas_de_prosa,
    marcadores_de_plantilla,
    secciones,
)
from baremo.probes.documentacion import caracteres_utiles

# ==========================================================================
# documentacion.arquitectura-c4
# ==========================================================================

#: (nivel, palabra clave de Mermaid, vistas de Structurizr, tipos característicos)
NIVELES_C4: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("contexto", "C4Context", ("systemlandscape", "systemcontext"), ("Person", "System")),
    ("contenedores", "C4Container", ("container",), ("Container",)),
    ("componentes", "C4Component", ("component",), ("Component",)),
)

EXTENSIONES_MARKDOWN: tuple[str, ...] = (".md", ".mdx", ".markdown")
EXTENSIONES_MERMAID: tuple[str, ...] = (".mmd", ".mermaid")
EXTENSIONES_STRUCTURIZR: tuple[str, ...] = (".dsl",)

_RE_ELEMENTO = re.compile(
    r"^\s*(Person(?:_Ext)?|System(?:Db|Queue)?(?:_Ext)?|Container(?:Db|Queue)?(?:_Ext)?"
    r"|Component(?:Db|Queue)?(?:_Ext)?)\s*\("
)
_RE_RELACION = re.compile(
    r"^\s*(?:BiRel|Rel(?:_(?:U|D|L|R|Up|Down|Left|Right|Back|Neighbor))?)\s*\("
)

_RE_DSL_ELEMENTO = re.compile(
    r"^\s*(?:[\w.]+\s*=\s*)?(person|softwareSystem|container|component)\s+\"", re.IGNORECASE
)
_RE_DSL_RELACION = re.compile(r"->")
_RE_DSL_VISTA = re.compile(
    r"^\s*(systemLandscape\b|systemContext\s+[\w.]+|container\s+(?!\")[\w.]+|component\s+(?!\")[\w.]+)",
    re.IGNORECASE,
)


@dataclass
class Diagrama:
    nivel: str
    fuente: Path
    linea: int
    formato: str
    elementos: int = 0
    caracteristicos: int = 0
    relaciones: int = 0
    marcadores: list[tuple[int, str]] = field(default_factory=list)

    @property
    def real(self) -> bool:
        return (not self.marcadores and self.caracteristicos >= 1
                and self.elementos >= 2 and self.relaciones >= 1)

    def faltas(self) -> list[str]:
        faltas: list[str] = []
        if self.marcadores:
            muestra = ", ".join(f"«{m}» (línea {n})" for n, m in self.marcadores[:3])
            faltas.append(f"marcadores de plantilla: {muestra}")
        if self.caracteristicos < 1:
            faltas.append(f"ningún elemento propio del nivel {self.nivel}")
        if self.elementos < 2:
            faltas.append(f"{self.elementos} elemento(s); se exigen al menos 2")
        if self.relaciones < 1:
            faltas.append("ninguna relación entre elementos")
        return faltas


def _tipo_mermaid(lineas: list[tuple[int, str]]) -> tuple[str, int] | None:
    """Palabra de tipo del diagrama y su línea (salta front matter y comentarios %%)."""
    en_front_matter = False
    for indice, (numero, linea) in enumerate(lineas):
        limpia = linea.strip()
        if indice == 0 and limpia == "---":
            en_front_matter = True
            continue
        if en_front_matter:
            if limpia == "---":
                en_front_matter = False
            continue
        if not limpia or limpia.startswith("%%"):
            continue
        return limpia.split()[0], numero
    return None


def _diagrama_mermaid(ruta: Path, lineas: list[tuple[int, str]], formato: str) -> Diagrama | None:
    tipo = _tipo_mermaid(lineas)
    if tipo is None:
        return None
    palabra, numero = tipo
    for nivel, clave, _, caracteristicos in NIVELES_C4:
        if palabra != clave:
            continue
        diagrama = Diagrama(nivel=nivel, fuente=ruta, linea=numero, formato=f"{formato} {clave}")
        for _, linea in lineas:
            casa = _RE_ELEMENTO.match(linea)
            if casa:
                diagrama.elementos += 1
                if casa.group(1).startswith(caracteristicos):
                    diagrama.caracteristicos += 1
            elif _RE_RELACION.match(linea):
                diagrama.relaciones += 1
        diagrama.marcadores = marcadores_de_plantilla(lineas)
        return diagrama
    return None                     # C4Dynamic, C4Deployment u otro tipo: no es un nivel


def _diagramas_structurizr(ruta: Path, texto: str) -> list[Diagrama]:
    if not re.search(r"(?im)^\s*workspace\b", texto):
        return []
    lineas = list(enumerate(texto.splitlines(), start=1))
    conteo = {"person": 0, "softwaresystem": 0, "container": 0, "component": 0}
    relaciones = 0
    vistas: list[tuple[int, str]] = []
    en_vistas = False
    for numero, linea in lineas:
        if re.match(r"^\s*views\s*\{", linea, re.IGNORECASE):
            en_vistas = True
            continue
        if en_vistas:
            casa = _RE_DSL_VISTA.match(linea)
            if casa:
                vistas.append((numero, casa.group(1).split()[0].lower()))
            continue
        elemento = _RE_DSL_ELEMENTO.match(linea)
        if elemento:
            conteo[elemento.group(1).lower()] += 1
        relaciones += len(_RE_DSL_RELACION.findall(linea))
    marcadores = marcadores_de_plantilla(lineas)
    total = sum(conteo.values())
    propios = {
        "contexto": conteo["person"] + conteo["softwaresystem"],
        "contenedores": conteo["container"],
        "componentes": conteo["component"],
    }
    diagramas: list[Diagrama] = []
    for numero, vista in vistas:
        nivel = next(n for n, _, claves, _ in NIVELES_C4 if vista in claves)
        diagramas.append(Diagrama(
            nivel=nivel, fuente=ruta, linea=numero, formato=f"Structurizr {vista}",
            elementos=total, caracteristicos=propios[nivel], relaciones=relaciones,
            marcadores=list(marcadores),
        ))
    return diagramas


def localizar_diagramas_c4(ctx: Contexto) -> list[Diagrama]:
    diagramas: list[Diagrama] = []
    for ruta in ctx.archivos:
        sufijo = ruta.suffix.lower()
        if sufijo not in EXTENSIONES_MARKDOWN + EXTENSIONES_MERMAID + EXTENSIONES_STRUCTURIZR:
            continue
        texto = ctx.leer(ruta)
        if not texto:
            continue
        if sufijo in EXTENSIONES_MARKDOWN:
            for bloque in bloques_cercados(texto):
                if bloque.lenguaje == "mermaid":
                    diagrama = _diagrama_mermaid(ruta, bloque.lineas, "Mermaid")
                    if diagrama:
                        diagramas.append(diagrama)
        elif sufijo in EXTENSIONES_MERMAID:
            diagrama = _diagrama_mermaid(ruta, list(enumerate(texto.splitlines(), start=1)), "Mermaid")
            if diagrama:
                diagramas.append(diagrama)
        else:
            diagramas.extend(_diagramas_structurizr(ruta, texto))
    return diagramas


def _evidencia_diagrama(ctx: Contexto, d: Diagrama, detalle: str) -> Evidencia:
    return Evidencia(
        fuente=ctx.rel(d.fuente),
        extracto=(f"{d.formato} · {d.elementos} elementos ({d.caracteristicos} del nivel) "
                  f"· {d.relaciones} relaciones"),
        detalle=f"línea {d.linea} · {detalle}",
    )


@registrar("documentacion.arquitectura-c4")
class SondaArquitecturaC4(Sonda):
    """Por cada nivel C4 (contexto, contenedores, componentes) exige al menos un
    diagrama REAL: bloque Mermaid C4Context/C4Container/C4Component o vista de
    Structurizr DSL, con un elemento propio del nivel, dos elementos o más, una
    relación o más y ningún marcador de plantilla (<proyecto>, "…", AAAA-MM-DD).
    Sin diagramas en todo el árbol: NO_CUMPLE con el universo inspeccionado como
    evidencia; si el barrido se truncó, NO_MEDIBLE."""

    titulo = "Arquitectura documentada con diagramas C4 reales"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "C4_NIVEL": "El nivel C4 tiene al menos un diagrama real (no una plantilla)",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        diagramas = localizar_diagramas_c4(ctx)
        return self._check([self._nivel(ctx, nivel, diagramas) for nivel, *_ in NIVELES_C4])

    def _nivel(self, ctx: Contexto, nivel: str, diagramas: list[Diagrama]) -> ResultadoSubcheck:
        id_sub, desc = "C4_NIVEL", self.descripciones["C4_NIVEL"]
        sujeto = sujeto_de(ctx, "c4", nivel)
        del_nivel = [d for d in diagramas if d.nivel == nivel]
        reales = [d for d in del_nivel if d.real]
        if reales:
            evidencias = [_evidencia_diagrama(ctx, d, "diagrama real") for d in reales[:3]]
            descartados = [d for d in del_nivel if not d.real]
            if descartados:
                evidencias.append(Evidencia(
                    fuente=ctx.rel(descartados[0].fuente),
                    extracto=f"{len(descartados)} diagrama(s) del nivel no cuentan",
                    detalle=recortar("; ".join(descartados[0].faltas()), 200),
                ))
            return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto, evidencias)
        if del_nivel:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [_evidencia_diagrama(ctx, d, recortar("no cuenta: " + "; ".join(d.faltas()), 240))
                 for d in del_nivel[:5]],
            )
        if ctx.barrido_truncado:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"El barrido se truncó al alcanzar el tope de archivos "
                        f"({len(ctx.archivos)}): no se puede afirmar que no haya un diagrama "
                        f"de {nivel} sobre un universo incompleto."),
            )
        otros = sorted({d.nivel for d in diagramas})
        clave = next(c for n, c, *_ in NIVELES_C4 if n == nivel)
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [evidencia_de_ausencia(
                ctx, [f"bloque mermaid {clave}", f"vista Structurizr de {nivel}"],
                detalle=(f"{len(diagramas)} diagramas C4 en el árbol"
                         + (f" (niveles: {', '.join(otros)})" if otros else "")
                         + f" · {len(ctx.archivos)} archivos inspeccionados"))],
        )


# ==========================================================================
# documentacion.adr
# ==========================================================================

SEGMENTOS_ADR: frozenset[str] = frozenset({
    "adr", "adrs", "decisiones", "decisions", "decision-records", "architecture-decisions",
})
_RE_NOMBRE_ADR = re.compile(r"(?i)^(?:adr[-_]?)?(\d{3,4})[-_].+\.(?:md|markdown|rst|txt|adoc)$")
_RE_NOMBRE_ADR_SUELTO = re.compile(r"(?i)^adr[-_]?\d{3,4}[-_].+\.(?:md|markdown|rst|txt|adoc)$")

_RE_ESTADO_LINEA = re.compile(
    r"(?i)^\s*(?:[-*]\s*)?(?:\*\*|__)?(?:estado|status)(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(.+)$"
)
_RE_ESTADO_VALOR = re.compile(
    r"(?i)\b(propuest[oa]|aceptad[oa]|rechazad[oa]|obsolet[oa]|reemplazad[oa]|sustituid[oa]"
    r"|superad[oa]|vigente|borrador|deprecad[oa]|en revisi[oó]n|proposed|accepted|rejected"
    r"|deprecated|superseded|draft|amended)\b"
)
#: (nombre legible, patrón del título de la sección)
SECCIONES_ADR: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("contexto", re.compile(r"(?i)contexto|context|antecedentes|problema|problem|motivaci[oó]n|background")),
    ("decisión", re.compile(r"(?i)decisi[oó]n|decision|resoluci[oó]n|outcome")),
    ("consecuencias", re.compile(r"(?i)consecuencias|consequences|implicaciones|implications|impacto")),
)
#: Caracteres útiles mínimos para que una sección cuente como escrita.
MINIMO_SECCION_ADR: int = 20


def localizar_adrs(ctx: Contexto) -> list[Path]:
    salida: list[Path] = []
    for ruta in ctx.archivos:
        partes = ctx.rel(ruta).lower().split("/")
        nombre = ruta.name
        if any(p in nombre.lower() for p in ("plantilla", "template")):
            continue
        en_carpeta = any(p in SEGMENTOS_ADR for p in partes[:-1])
        if (en_carpeta and _RE_NOMBRE_ADR.match(nombre)) or _RE_NOMBRE_ADR_SUELTO.match(nombre):
            salida.append(ruta)
    return salida


def _estado(texto: str) -> str | None:
    for _, linea in lineas_de_prosa(enumerate(texto.splitlines(), start=1)):
        casa = _RE_ESTADO_LINEA.match(linea)
        if casa and _RE_ESTADO_VALOR.search(casa.group(1)):
            return casa.group(1).strip()
    for seccion in secciones(texto):
        if re.search(r"(?i)^(estado|status)\b", seccion.titulo):
            primera = next((l.strip() for _, l in seccion.cuerpo if l.strip()), "")
            if _RE_ESTADO_VALOR.search(primera):
                return primera
    return None


@registrar("documentacion.adr")
class SondaAdr(Sonda):
    """Cada ADR numerado (docs/adr/NNNN-*.md o adr-NNNN-*.md) debe declarar un estado
    reconocible (propuesta, aceptada, reemplazada…) y tener las secciones contexto,
    decisión y consecuencias con al menos 20 caracteres útiles cada una, sin
    marcadores de plantilla. Sin ningún ADR: NO_CUMPLE con el universo inspeccionado."""

    titulo = "Decisiones de arquitectura registradas como ADR completos"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "ADR_COMPLETO": "El ADR declara estado, contexto, decisión y consecuencias",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        adrs = localizar_adrs(ctx)
        if not adrs:
            return self._check([self._sin_adrs(ctx)])
        return self._check([self._adr(ctx, ruta) for ruta in adrs])

    def _sin_adrs(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "ADR_COMPLETO", self.descripciones["ADR_COMPLETO"]
        sujeto = sujeto_de(ctx, "adr", "registro")
        if ctx.barrido_truncado:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=("El barrido se truncó: no se puede afirmar que no existan ADR sobre "
                        "un universo incompleto."),
            )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [evidencia_de_ausencia(ctx, ["docs/adr/NNNN-*.md", "docs/decisiones/NNNN-*.md",
                                         "adr-NNNN-*.md"])],
        )

    def _adr(self, ctx: Contexto, ruta: Path) -> ResultadoSubcheck:
        id_sub, desc = "ADR_COMPLETO", self.descripciones["ADR_COMPLETO"]
        sujeto = sujeto_de(ctx, "adr", ruta.stem)
        texto = ctx.leer(ruta)
        if texto is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"{ctx.rel(ruta)} no pudo leerse como texto; haría falta acceso de "
                        f"lectura para verificar sus secciones."),
            )
        faltas: list[str] = []
        estado = _estado(texto)
        if estado is None:
            faltas.append("estado reconocible (Estado: propuesta/aceptada/reemplazada…)")
        medidas: dict[str, int] = {}
        # El título (nivel 1) abarca todo el documento: si contara, «# ADR 0003 · Decisión
        # de…» acreditaría la sección de decisión con el texto entero. Sólo cuentan los
        # encabezados de nivel 2 o más, y el título de la sección debe EMPEZAR por la
        # palabra clave («Consecuencias de la decisión» no es la sección de decisión).
        todas = [s for s in secciones(texto) if s.nivel >= 2]
        for nombre, patron in SECCIONES_ADR:
            candidatas = [s for s in todas
                          if patron.match(re.sub(r"^[\d.)\s·-]+", "", s.titulo))]
            mejor = max((caracteres_utiles(s.texto) for s in candidatas), default=-1)
            medidas[nombre] = max(mejor, 0)
            if mejor < 0:
                faltas.append(f"sección de {nombre}")
            elif mejor < MINIMO_SECCION_ADR:
                faltas.append(f"contenido en la sección de {nombre} ({mejor} caracteres útiles)")
        marcadores = marcadores_de_plantilla(lineas_de_prosa(enumerate(texto.splitlines(), start=1)))
        if marcadores:
            faltas.append("sin marcadores de plantilla: "
                          + ", ".join(f"«{m}» (línea {n})" for n, m in marcadores[:3]))
        resumen = (f"estado «{recortar(estado or 'no declarado', 40)}» · "
                   + " · ".join(f"{k} {v}" for k, v in medidas.items()) + " caracteres útiles")
        if faltas:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [Evidencia(fuente=ctx.rel(ruta), extracto=recortar(resumen),
                           detalle=recortar("falta: " + "; ".join(faltas), 240))],
            )
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=recortar(resumen),
                       detalle=f"mínimo por sección: {MINIMO_SECCION_ADR} caracteres útiles")],
        )
