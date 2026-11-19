"""Utilidades privadas de las sondas: Markdown, rutas de prueba y marcadores de plantilla.

Leer Markdown con expresiones regulares tiene límites, y aquí se DECLARAN en vez de
esconderse: se reconocen encabezados ATX (`#`), bloques cercados con tres comillas
invertidas o tres tildes, y enlaces en línea `[texto](destino)`. Lo que no se
reconozca no se acredita: un documento que la sonda no sabe leer no suma.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from baremo.probes import Contexto

# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

_RE_VALLA = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+.-]*)")
_RE_ENCABEZADO = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RE_ENLACE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_RE_CODIGO_EN_LINEA = re.compile(r"`[^`]*`")


@dataclass
class Bloque:
    """Bloque de código cercado. `lineas` son (número 1-based, texto)."""
    lenguaje: str
    linea: int
    lineas: list[tuple[int, str]]


@dataclass
class Seccion:
    """Encabezado y su cuerpo, que llega hasta el siguiente encabezado de nivel igual
    o superior (las subsecciones forman parte del cuerpo)."""
    nivel: int
    titulo: str
    linea: int
    cuerpo: list[tuple[int, str]]

    @property
    def texto(self) -> str:
        return "\n".join(linea for _, linea in self.cuerpo)


def bloques_cercados(texto: str) -> list[Bloque]:
    bloques: list[Bloque] = []
    actual: Bloque | None = None
    valla = ""
    for numero, linea in enumerate(texto.splitlines(), start=1):
        casa = _RE_VALLA.match(linea)
        if actual is None:
            if casa:
                valla = casa.group(1)
                actual = Bloque(casa.group(2).lower(), numero, [])
            continue
        if casa and casa.group(1)[0] == valla[0] and len(casa.group(1)) >= len(valla) \
                and not casa.group(2):
            bloques.append(actual)
            actual = None
            continue
        actual.lineas.append((numero, linea))
    if actual is not None:          # valla sin cerrar: el contenido se conserva
        bloques.append(actual)
    return bloques


def _lineas_con_estado_de_valla(lineas: Iterable[tuple[int, str]]) -> list[tuple[int, str, bool]]:
    """(número, línea, ¿dentro de un bloque cercado?). Las vallas mismas cuentan como dentro."""
    salida: list[tuple[int, str, bool]] = []
    valla: str | None = None
    for numero, linea in lineas:
        casa = _RE_VALLA.match(linea)
        if casa:
            if valla is None:
                valla = casa.group(1)[0]
                salida.append((numero, linea, True))
                continue
            if casa.group(1)[0] == valla and not casa.group(2):
                valla = None
                salida.append((numero, linea, True))
                continue
        salida.append((numero, linea, valla is not None))
    return salida


def lineas_en_codigo(lineas: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """Líneas que están DENTRO de un bloque cercado (sin las vallas)."""
    return [(n, l) for n, l, dentro in _lineas_con_estado_de_valla(lineas)
            if dentro and not _RE_VALLA.match(l)]


def lineas_de_prosa(lineas: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """Líneas FUERA de bloques cercados, sin los fragmentos de código en línea."""
    return [(n, _RE_CODIGO_EN_LINEA.sub(" ", l))
            for n, l, dentro in _lineas_con_estado_de_valla(lineas) if not dentro]


def secciones(texto: str) -> list[Seccion]:
    lineas = texto.splitlines()
    encabezados: list[tuple[int, int, str]] = []
    for numero, linea, dentro in _lineas_con_estado_de_valla(enumerate(lineas, start=1)):
        if dentro:
            continue
        casa = _RE_ENCABEZADO.match(linea)
        if casa:
            encabezados.append((numero, len(casa.group(1)), casa.group(2).strip()))
    resultado: list[Seccion] = []
    for k, (numero, nivel, titulo) in enumerate(encabezados):
        fin = len(lineas) + 1
        for numero2, nivel2, _ in encabezados[k + 1:]:
            if nivel2 <= nivel:
                fin = numero2
                break
        cuerpo = [(n, lineas[n - 1]) for n in range(numero + 1, fin)]
        resultado.append(Seccion(nivel, titulo, numero, cuerpo))
    return resultado


def es_externo(destino: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", destino, re.IGNORECASE)) or destino.startswith("//")


def enlaces(lineas: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """(número, destino) de cada enlace en línea `[texto](destino)` (no imágenes)."""
    salida: list[tuple[int, str]] = []
    for numero, linea in lineas:
        for casa in _RE_ENLACE.finditer(linea):
            salida.append((numero, casa.group(1)))
    return salida


def resolver_enlace(ctx: Contexto, base: Path, destino: str) -> Path | None:
    """Ruta existente DENTRO del sujeto a la que apunta un enlace interno, o None."""
    if es_externo(destino):
        return None
    ruta = unquote(destino.split("#", 1)[0].split("?", 1)[0])
    if not ruta:
        return None                 # ancla a la misma página: no apunta a un documento
    candidato = (ctx.ruta_repo / ruta.lstrip("/")) if ruta.startswith("/") else (base / ruta)
    try:
        candidato = candidato.resolve()
        raiz = ctx.ruta_repo.resolve()
    except OSError:
        return None
    if candidato != raiz and raiz not in candidato.parents:
        return None                 # fuera del sujeto: no es documentación del sujeto
    return candidato if candidato.exists() else None


# --------------------------------------------------------------------------
# Marcadores de plantilla
# --------------------------------------------------------------------------
#
# Un documento copiado de una plantilla y no adaptado es peor que uno ausente: se
# lee como si documentara algo. Se reconocen tres formas de hueco:
#   · angulares de relleno: <proyecto>, <tu-usuario>, <app> (no las etiquetas HTML
#     como <br/>, ni los autoenlaces <https://…>, ni las direcciones <a@b.c>);
#   · fechas y textos de relleno: AAAA-MM-DD, YYYY-MM-DD, lorem ipsum, y TODO/TBD/FIXME
#     EN MAYÚSCULAS (en minúsculas, «todo» es una palabra común del español);
#   · descripciones que son sólo una elipsis entre comillas: "…" o "...".

ETIQUETAS_HTML: frozenset[str] = frozenset({
    "a", "abbr", "b", "big", "blockquote", "br", "center", "code", "dd", "del",
    "details", "div", "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "picture", "pre", "q",
    "s", "samp", "small", "source", "span", "strike", "strong", "sub", "summary",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "tt", "u", "ul",
    "var", "video", "wbr",
})

_RE_ANGULAR = re.compile(r"<([A-Za-zÁÉÍÓÚÑáéíóúñ][^<>\n]{0,40})>")
_RE_RELLENO = re.compile(r"(?i)(?<![\w-])(AAAA-MM-DD|YYYY-MM-DD|DD/MM/AAAA|lorem ipsum)(?![\w-])")
_RE_PENDIENTE = re.compile(r"(?<![\w-])(TODO|TBD|FIXME)(?![\w-])")
_RE_ELIPSIS = re.compile(r"[\"'“«]\s*(?:…|\.\.\.)\s*[\"'”»]")


def marcadores_de_plantilla(lineas: Iterable[tuple[int, str]]) -> list[tuple[int, str]]:
    """(número, marcador) de cada hueco de plantilla en las líneas dadas."""
    hallados: list[tuple[int, str]] = []
    for numero, linea in lineas:
        for casa in _RE_ANGULAR.finditer(linea):
            interior = casa.group(1).strip()
            primera = re.split(r"[\s/]", interior, maxsplit=1)[0].lower()
            if primera in ETIQUETAS_HTML or any(s in interior for s in ("=", "://", "@")):
                continue
            hallados.append((numero, casa.group(0)))
        for patron in (_RE_RELLENO, _RE_PENDIENTE, _RE_ELIPSIS):
            for casa in patron.finditer(linea):
                hallados.append((numero, casa.group(0)))
    return hallados


# --------------------------------------------------------------------------
# Rutas de prueba
# --------------------------------------------------------------------------

#: Carpetas cuyo contenido es código de prueba, no código que se distribuye.
SEGMENTOS_DE_PRUEBA: frozenset[str] = frozenset({
    "test", "tests", "__tests__", "spec", "specs", "testing", "e2e", "fixtures",
    "__fixtures__", "testdata", "cypress", "playwright",
})

_RE_ARCHIVO_DE_PRUEBA = re.compile(
    r"(?i)(^test_.*\.py$|_test\.(py|go)$|\.(test|spec|e2e|cy)\.[cm]?[jt]sx?$|Tests?\.(cs|java|kt)$)"
)


def es_ruta_de_pruebas(relativa: str) -> bool:
    partes = relativa.lower().split("/")
    if any(p in SEGMENTOS_DE_PRUEBA for p in partes[:-1]):
        return True
    return bool(_RE_ARCHIVO_DE_PRUEBA.search(relativa.split("/")[-1]))
