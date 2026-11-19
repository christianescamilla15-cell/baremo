"""Sondas de publicación (N11): README estándar, licencia y política de seguridad.

Las sondas `documentacion` y `seguridad` ya miden que los archivos EXISTAN. Éstas miden
que sirvan:

  · README estándar: cada elemento es un sujeto. Una insignia de CI acredita sólo si
    apunta a un flujo que existe en el árbol y que corre pruebas (la de seguridad, a uno
    que invoca un escáner). Una sección acredita sólo si dice algo verificable: un
    enlace interno que resuelve, un comando dentro de un bloque de código.
  · Licencia: el texto se reconoce (huella del texto o `SPDX-License-Identifier`), las
    licencias que lo exigen llevan año y titular, y cada manifiesto de paquete declara
    la MISMA licencia que el archivo. Un texto que no se reconoce es NO_MEDIBLE: no se
    puede afirmar qué licencia es.
  · Política de seguridad: canal privado de reporte, plazo de respuesta y ningún hueco
    de plantilla («Seguridad: <proyecto>»).
"""
from __future__ import annotations

import fnmatch
import json
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
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
    sujeto_de,
)
from baremo.probes._apoyo import (
    Seccion,
    enlaces,
    lineas_de_prosa,
    lineas_en_codigo,
    marcadores_de_plantilla,
    resolver_enlace,
    secciones,
)
from baremo.probes.analisis import ESCANERES
from baremo.probes.ci import CORREDORES_DE_PRUEBAS
from baremo.probes.documentacion import PATRONES_LICENCIA, PATRONES_README, RE_ARRANQUE
from baremo.probes.seguridad import PATRONES_POLITICA, _es_de_terceros

# ==========================================================================
# documentacion.readme-estandar
# ==========================================================================

_RE_IMAGEN_MD = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
_RE_IMAGEN_HTML = re.compile(r"(?i)<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)")
_RE_INSIGNIA_FLUJO = re.compile(r"/actions/workflows/([^/?#\s]+)/badge\.svg")
_RE_LICENCIA_NOMBRE = re.compile(
    r"(?i)\b(MIT|Apache|GPL|LGPL|AGPL|BSD|MPL|ISC|Unlicense|CC0|EUPL|Boost)\b"
)
_RE_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMINIOS_DE_EJEMPLO = (
    "example.com", "example.org", "example.net", "ejemplo.com", "dominio.com", "domain.com",
    "tu-dominio", "your-domain", "correo.com", "email.com",
)


def localizar_readme(ctx: Contexto) -> Path | None:
    candidatos = ctx.buscar(PATRONES_README)
    raiz = [c for c in candidatos if "/" not in ctx.rel(c)]
    if raiz:
        return raiz[0]
    docs = [c for c in candidatos if ctx.rel(c).startswith("docs/")]
    return docs[0] if docs else None


def _enlace_que_resuelve(ctx: Contexto, readme: Path, cuerpo: list[tuple[int, str]],
                         filtro: Callable[[Path], bool] = lambda _: True,
                         ) -> tuple[int, str, Path] | None:
    for numero, destino in enlaces(lineas_de_prosa(cuerpo)):
        resuelto = resolver_enlace(ctx, readme.parent, destino)
        if resuelto is not None and filtro(resuelto):
            return numero, destino, resuelto
    return None


def _correo_valido(texto: str) -> str | None:
    for correo in _RE_CORREO.findall(texto):
        if not any(d in correo.lower() for d in _DOMINIOS_DE_EJEMPLO):
            return correo
    return None


def _criterio_arquitectura(ctx: Contexto, readme: Path, s: Seccion) -> tuple[int, str, str] | None:
    hallado = _enlace_que_resuelve(ctx, readme, s.cuerpo)
    if hallado:
        numero, destino, _ = hallado
        return numero, destino, "enlace interno que resuelve"
    for numero, linea in s.cuerpo:
        if linea.strip().lower().startswith(("```mermaid", "~~~mermaid")):
            return numero, linea, "diagrama en línea"
    return None


def _criterio_ejecutar(ctx: Contexto, readme: Path, s: Seccion) -> tuple[int, str, str] | None:
    for numero, linea in lineas_en_codigo(s.cuerpo):
        casa = RE_ARRANQUE.search(linea)
        if casa:
            return numero, linea, f"comando «{casa.group(1)}» en un bloque de código"
    return None


def _criterio_pruebas(ctx: Contexto, readme: Path, s: Seccion) -> tuple[int, str, str] | None:
    for numero, linea in s.cuerpo:
        for nombre, patron in CORREDORES_DE_PRUEBAS:
            if patron.search(linea):
                return numero, linea, f"comando de pruebas «{nombre}»"
    hallado = _enlace_que_resuelve(ctx, readme, s.cuerpo)
    if hallado:
        numero, destino, _ = hallado
        return numero, destino, "enlace interno que resuelve"
    return None


def _criterio_seguridad(ctx: Contexto, readme: Path, s: Seccion) -> tuple[int, str, str] | None:
    hallado = _enlace_que_resuelve(ctx, readme, s.cuerpo)
    if hallado:
        numero, destino, _ = hallado
        return numero, destino, "enlace interno que resuelve"
    for numero, linea in s.cuerpo:
        correo = _correo_valido(linea)
        if correo:
            return numero, linea, "canal de reporte (correo)"
    return None


def _criterio_licencia(ctx: Contexto, readme: Path, s: Seccion) -> tuple[int, str, str] | None:
    patrones = [p.lower() for p in PATRONES_LICENCIA]
    hallado = _enlace_que_resuelve(
        ctx, readme, s.cuerpo,
        lambda r: any(fnmatch.fnmatchcase(r.name.lower(), p) for p in patrones),
    )
    if hallado:
        numero, destino, _ = hallado
        return numero, destino, "enlace al archivo de licencia"
    for numero, linea in lineas_de_prosa(s.cuerpo):
        casa = _RE_LICENCIA_NOMBRE.search(linea)
        if casa:
            return numero, linea, f"licencia nombrada «{casa.group(1)}»"
    return None


#: id de sub-check -> (elemento, patrón del título, criterio, qué se exige)
SECCIONES_README: dict[str, tuple[str, re.Pattern[str], Callable[..., tuple[int, str, str] | None], str]] = {
    "README_ARQUITECTURA": (
        "arquitectura", re.compile(r"(?i)\barquitectura\b|\barchitecture\b|\bdise[ñn]o\b|\bdesign\b"),
        _criterio_arquitectura, "un enlace interno que resuelva o un diagrama en línea"),
    "README_EJECUTAR": (
        "ejecutar", re.compile(
            r"(?i)ejecut|instala|\buso\b|\busar\b|arranque|inicio r[aá]pido|primeros pasos"
            r"|getting started|quick ?start|install|usage|\brun"),
        _criterio_ejecutar, "un comando de instalación o ejecución dentro de un bloque de código"),
    "README_PRUEBAS": (
        "pruebas", re.compile(r"(?i)\bpruebas?\b|\btests?\b|\btesting\b|\bcalidad\b|\bquality\b"),
        _criterio_pruebas, "el comando que corre las pruebas o un enlace interno que resuelva"),
    "README_SEGURIDAD": (
        "seguridad", re.compile(r"(?i)seguridad|security"),
        _criterio_seguridad, "un enlace interno que resuelva (SECURITY.md) o un canal de reporte"),
    "README_LICENCIA": (
        "licencia", re.compile(r"(?i)licencia|licen[cs]e"),
        _criterio_licencia, "un enlace al archivo de licencia o el nombre de la licencia"),
}


def _corre_pruebas(texto: str) -> bool:
    return any(p.search(texto) for _, p in CORREDORES_DE_PRUEBAS)


def _invoca_escaner(texto: str) -> bool:
    for _, patron_uses, patron_run in ESCANERES:
        if (patron_uses and patron_uses.search(texto)) or (patron_run and patron_run.search(texto)):
            return True
    return False


#: id de sub-check -> (elemento, qué debe hacer el flujo, comprobación sobre su texto)
INSIGNIAS_README: dict[str, tuple[str, str, Callable[[str], bool]]] = {
    "README_INSIGNIA_CI": ("insignia-ci", "corre pruebas", _corre_pruebas),
    "README_INSIGNIA_SEGURIDAD": ("insignia-seguridad", "invoca un escáner de seguridad", _invoca_escaner),
}


@registrar("documentacion.readme-estandar")
class SondaReadmeEstandar(Sonda):
    """El README estándar tiene siete elementos, cada uno un sujeto: insignia de CI
    (apunta a un flujo existente que corre pruebas), insignia de seguridad (a un flujo
    existente que invoca un escáner) y las secciones Arquitectura, Cómo ejecutar,
    Pruebas, Seguridad y Licencia, cada una con algo verificable (enlace interno que
    resuelve, comando en un bloque de código, canal de reporte). El título se reconoce
    en español y en inglés."""

    titulo = "README estándar con insignias y secciones verificables"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "README_INSIGNIA_CI": "La insignia de CI apunta a un flujo existente que corre pruebas",
        "README_INSIGNIA_SEGURIDAD": "La insignia de seguridad apunta a un flujo existente que escanea",
        "README_ARQUITECTURA": "La sección de arquitectura apunta a la documentación",
        "README_EJECUTAR": "La sección de ejecución muestra el comando en un bloque de código",
        "README_PRUEBAS": "La sección de pruebas dice cómo correrlas o dónde están",
        "README_SEGURIDAD": "La sección de seguridad apunta a la política o al canal de reporte",
        "README_LICENCIA": "La sección de licencia nombra la licencia o enlaza el archivo",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        readme = localizar_readme(ctx)
        if readme is None:
            evidencia = evidencia_de_ausencia(ctx, ["README (raíz)", "docs/README.*"])
            return self._check([
                subcheck(id_sub, desc, Veredicto.NO_CUMPLE, self._sujeto(ctx, id_sub), [evidencia])
                for id_sub, desc in self.descripciones.items()
            ])
        texto = ctx.leer(readme)
        if texto is None:
            return self._check([
                subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, self._sujeto(ctx, id_sub),
                         motivo=(f"{ctx.rel(readme)} no pudo leerse como texto; haría falta "
                                 f"acceso de lectura al archivo."))
                for id_sub, desc in self.descripciones.items()
            ])
        resultados = [self._insignia(ctx, readme, texto, id_sub) for id_sub in INSIGNIAS_README]
        todas = secciones(texto)
        resultados += [self._seccion(ctx, readme, todas, id_sub) for id_sub in SECCIONES_README]
        return self._check(resultados)

    @staticmethod
    def _sujeto(ctx: Contexto, id_sub: str) -> str:
        elemento = (INSIGNIAS_README.get(id_sub) or SECCIONES_README[id_sub])[0]
        return sujeto_de(ctx, "readme", elemento)

    def _insignia(self, ctx: Contexto, readme: Path, texto: str, id_sub: str) -> ResultadoSubcheck:
        desc = self.descripciones[id_sub]
        _, que_hace, comprueba = INSIGNIAS_README[id_sub]
        sujeto = self._sujeto(ctx, id_sub)
        vistas: list[str] = []
        for numero, linea in enumerate(texto.splitlines(), start=1):
            for url in _RE_IMAGEN_MD.findall(linea) + _RE_IMAGEN_HTML.findall(linea):
                casa = _RE_INSIGNIA_FLUJO.search(url)
                if not casa:
                    continue
                flujo = ctx.ruta_repo / ".github" / "workflows" / casa.group(1)
                if not flujo.is_file():
                    vistas.append(f"línea {numero}: {casa.group(1)} no existe en .github/workflows/")
                    continue
                contenido = ctx.leer(flujo)
                if contenido is None:
                    vistas.append(f"línea {numero}: {casa.group(1)} ilegible")
                    continue
                if comprueba(contenido):
                    return subcheck(
                        id_sub, desc, Veredicto.CUMPLE, sujeto,
                        [evidencia_linea(ctx, readme, numero, linea,
                                         detalle=f"el flujo {ctx.rel(flujo)} existe y {que_hace}")],
                    )
                vistas.append(f"línea {numero}: {casa.group(1)} no {que_hace}")
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [Evidencia(
                fuente=ctx.rel(readme),
                extracto=(f"{len(vistas)} insignias de flujo revisadas" if vistas
                          else "ninguna insignia …/actions/workflows/<flujo>/badge.svg"),
                detalle=recortar("; ".join(vistas) or f"se exige una insignia cuyo flujo {que_hace}", 240),
            )],
        )

    def _seccion(self, ctx: Contexto, readme: Path, todas: list[Seccion], id_sub: str) -> ResultadoSubcheck:
        desc = self.descripciones[id_sub]
        elemento, patron, criterio, exige = SECCIONES_README[id_sub]
        sujeto = self._sujeto(ctx, id_sub)
        candidatas = [s for s in todas if patron.search(s.titulo)]
        for seccion in candidatas:
            hallado = criterio(ctx, readme, seccion)
            if hallado:
                numero, linea, detalle = hallado
                return subcheck(
                    id_sub, desc, Veredicto.CUMPLE, sujeto,
                    [evidencia_linea(ctx, readme, numero, linea,
                                     detalle=f"sección «{seccion.titulo}» · {detalle}")],
                )
        if candidatas:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [Evidencia(
                    fuente=ctx.rel(readme),
                    extracto=", ".join(f"«{s.titulo}» (línea {s.linea})" for s in candidatas[:3]),
                    detalle=f"la sección existe pero no tiene {exige}",
                )],
            )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [Evidencia(
                fuente=ctx.rel(readme),
                extracto=f"{len(todas)} encabezados leídos, ninguno de {elemento}",
                detalle=f"título buscado (es/en): {patron.pattern.removeprefix('(?i)')}",
            )],
        )


# ==========================================================================
# documentacion.licencia
# ==========================================================================

@dataclass(frozen=True)
class HuellaLicencia:
    spdx: str
    frases: tuple[str, ...]
    requiere_titular: bool


#: Huellas de texto, en orden: la primera que casa gana (LGPL/AGPL antes que GPL,
#: BSD-3 antes que BSD-2).
HUELLAS_LICENCIA: tuple[HuellaLicencia, ...] = (
    HuellaLicencia("MIT", ("permission is hereby granted, free of charge",
                           "the above copyright notice and this permission notice shall be included"), True),
    HuellaLicencia("Apache-2.0", ("apache license", "version 2.0"), False),
    HuellaLicencia("AGPL-3.0", ("gnu affero general public license",), False),
    HuellaLicencia("LGPL-3.0", ("gnu lesser general public license", "version 3"), False),
    HuellaLicencia("LGPL-2.1", ("gnu lesser general public license", "version 2.1"), False),
    HuellaLicencia("GPL-3.0", ("gnu general public license", "version 3"), False),
    HuellaLicencia("GPL-2.0", ("gnu general public license", "version 2"), False),
    HuellaLicencia("BSD-3-Clause", ("redistribution and use in source and binary forms",
                                    "neither the name"), True),
    HuellaLicencia("BSD-2-Clause", ("redistribution and use in source and binary forms",), True),
    HuellaLicencia("ISC", ("permission to use, copy, modify, and/or distribute this software",), True),
    HuellaLicencia("MPL-2.0", ("mozilla public license", "2.0"), False),
    HuellaLicencia("Unlicense", ("this is free and unencumbered software released into the public domain",), False),
    HuellaLicencia("CC0-1.0", ("cc0 1.0 universal",), False),
    HuellaLicencia("BSL-1.0", ("boost software license",), False),
    HuellaLicencia("EPL-2.0", ("eclipse public license", "2.0"), False),
)

_RE_SPDX = re.compile(r"SPDX-License-Identifier:\s*([\w.+-]+(?:\s+(?:OR|AND|WITH)\s+[\w.+-]+)*)")
_RE_COPYRIGHT = re.compile(
    r"(?i)^\s*copyright\s*(?:\(c\)|©)?\s*((?:19|20)\d{2})(?:\s*[-–,]\s*(?:(?:19|20)\d{2}|present))*"
    r"\s*,?\s*(?:by\s+)?(.*\S)"
)
_RE_TITULAR_DE_RELLENO = re.compile(r"(?i)[\[<{]|your name|tu nombre|fullname|copyright holders?\b")

#: Nombres de licencia en texto libre -> identificador SPDX normalizado.
ALIAS_LICENCIA: dict[str, str] = {
    "mit license": "mit", "the mit license": "mit", "expat": "mit",
    "apache 2.0": "apache-2.0", "apache-2": "apache-2.0", "apache license 2.0": "apache-2.0",
    "apache license, version 2.0": "apache-2.0", "apache software license": "apache-2.0",
    "apache2": "apache-2.0", "gplv3": "gpl-3.0", "gplv2": "gpl-2.0", "bsd license": "bsd",
    "isc license": "isc", "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "the unlicense": "unlicense", "unlicense": "unlicense",
}

#: Clasificador trove de Python -> SPDX normalizado.
TROVE_LICENCIA: dict[str, str] = {
    "mit license": "mit", "apache software license": "apache-2.0", "bsd license": "bsd",
    "isc license (iscl)": "isc", "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "gnu general public license v3 (gplv3)": "gpl-3.0",
    "gnu general public license v2 (gplv2)": "gpl-2.0",
    "gnu lesser general public license v3 (lgplv3)": "lgpl-3.0",
    "gnu affero general public license v3": "agpl-3.0", "the unlicense (unlicense)": "unlicense",
}

#: Carpetas donde un manifiesto es un ejemplo o un caso de prueba, no un paquete.
SEGMENTOS_NO_PAQUETE: frozenset[str] = frozenset({
    "test", "tests", "fixtures", "testdata", "examples", "ejemplos", "docs", "plantilla", "templates",
})


def normalizar_licencia(valor: str) -> str:
    limpio = " ".join(valor.strip().lower().split())
    limpio = ALIAS_LICENCIA.get(limpio, limpio)
    return re.sub(r"(-only|-or-later|\+)$", "", limpio)


def _identificadores(expresion: str) -> set[str]:
    partes = re.split(r"(?i)\s+(?:or|and|with)\s+|[()]", expresion)
    return {normalizar_licencia(p) for p in partes if p.strip()}


def _coinciden(declarada: str, del_archivo: str) -> bool:
    archivo = normalizar_licencia(del_archivo)
    for ident in _identificadores(declarada):
        if ident == archivo or (ident == "bsd" and archivo.startswith("bsd")):
            return True
    return False


def reconocer_licencia(texto: str) -> tuple[str, str] | None:
    """(SPDX, cómo se reconoció) o None si el texto no se reconoce."""
    casa = _RE_SPDX.search(texto)
    if casa:
        return casa.group(1).strip(), "cabecera SPDX-License-Identifier"
    plano = " ".join(texto.lower().split())
    for huella in HUELLAS_LICENCIA:
        if all(frase in plano for frase in huella.frases):
            return huella.spdx, "huella del texto de la licencia"
    return None


def _titular(texto: str) -> tuple[int, str] | None:
    for numero, linea in enumerate(texto.splitlines(), start=1):
        casa = _RE_COPYRIGHT.match(linea)
        if casa and casa.group(2).strip() and not _RE_TITULAR_DE_RELLENO.search(casa.group(2)):
            return numero, linea
    return None


def _licencia_de_manifiesto(ruta: Path, texto: str) -> tuple[str | None, str | None, bool]:
    """(licencia declarada, archivo de licencia declarado, ¿es privado?)."""
    nombre = ruta.name.lower()
    if nombre == "package.json":
        datos = json.loads(texto)
        if not isinstance(datos, dict):
            return None, None, False
        privado = datos.get("private") is True
        licencia = datos.get("license")
        if isinstance(licencia, dict):
            licencia = licencia.get("type")
        return (str(licencia) if licencia else None), None, privado
    datos = tomllib.loads(texto)
    if nombre == "cargo.toml":
        paquete = datos.get("package") or {}
        return paquete.get("license"), paquete.get("license-file"), False
    proyecto = datos.get("project") or {}
    licencia = proyecto.get("license")
    if isinstance(licencia, str):
        return licencia, None, False
    if isinstance(licencia, dict):
        if licencia.get("file"):
            return None, str(licencia["file"]), False
        if licencia.get("text"):
            return str(licencia["text"]), None, False
    poesia = ((datos.get("tool") or {}).get("poetry") or {}).get("license")
    if poesia:
        return str(poesia), None, False
    for clasificador in proyecto.get("classifiers") or []:
        if str(clasificador).startswith("License ::"):
            nombre_trove = str(clasificador).split("::")[-1].strip().lower()
            if nombre_trove in TROVE_LICENCIA:
                return TROVE_LICENCIA[nombre_trove], None, False
    return None, None, False


@registrar("documentacion.licencia")
class SondaLicencia(Sonda):
    """El archivo de licencia de la raíz se reconoce (huella del texto o cabecera
    SPDX); MIT, BSD e ISC exigen además una línea de copyright con año y titular que
    no sea de relleno. Cada manifiesto de paquete (pyproject.toml, package.json,
    Cargo.toml, en la raíz o un nivel abajo, no privado) declara la misma licencia que
    el archivo. Texto no reconocido: NO_MEDIBLE."""

    titulo = "Licencia reconocible y coherente con los manifiestos"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "LICENCIA_ARCHIVO": "El archivo de licencia se reconoce y declara titular cuando lo exige",
        "LICENCIA_MANIFIESTO": "El manifiesto del paquete declara la misma licencia que el archivo",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        candidatos = [c for c in ctx.buscar(PATRONES_LICENCIA) if "/" not in ctx.rel(c)]
        candidatos += [c for c in ctx.buscar(PATRONES_LICENCIA) if ctx.rel(c).startswith("docs/")
                       and ctx.rel(c).count("/") == 1]
        archivo = candidatos[0] if candidatos else None
        resultado, spdx = self._archivo(ctx, archivo)
        subchecks = [resultado]
        for manifiesto in self._manifiestos(ctx):
            sub = self._manifiesto(ctx, manifiesto, archivo, spdx)
            if sub is not None:
                subchecks.append(sub)
        return self._check(subchecks)

    def _manifiestos(self, ctx: Contexto) -> list[Path]:
        salida: list[Path] = []
        for ruta in ctx.buscar(("pyproject.toml", "package.json", "Cargo.toml")):
            partes = ctx.rel(ruta).lower().split("/")
            if len(partes) > 2 or any(p in SEGMENTOS_NO_PAQUETE for p in partes[:-1]):
                continue
            salida.append(ruta)
        return salida

    def _archivo(self, ctx: Contexto, ruta: Path | None) -> tuple[ResultadoSubcheck, str | None]:
        id_sub, desc = "LICENCIA_ARCHIVO", self.descripciones["LICENCIA_ARCHIVO"]
        sujeto = sujeto_de(ctx, "licencia", "archivo")
        if ruta is None:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                            [evidencia_de_ausencia(ctx, list(PATRONES_LICENCIA),
                                                   detalle="en la raíz y en docs/")]), None
        texto = ctx.leer(ruta)
        if texto is None:
            return subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                            motivo=f"{ctx.rel(ruta)} no pudo leerse como texto."), None
        reconocida = reconocer_licencia(texto)
        if reconocida is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"El texto de {ctx.rel(ruta)} no corresponde a ninguna licencia "
                        f"conocida ({', '.join(h.spdx for h in HUELLAS_LICENCIA)}) y no "
                        f"declara SPDX-License-Identifier: no se puede afirmar qué licencia "
                        f"es. Haría falta el texto íntegro de la licencia o la cabecera SPDX."),
            ), None
        spdx, como = reconocida
        huella = next((h for h in HUELLAS_LICENCIA if h.spdx == spdx), None)
        if huella and huella.requiere_titular:
            titular = _titular(texto)
            if titular is None:
                return subcheck(
                    id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                    [Evidencia(fuente=ctx.rel(ruta), extracto=f"{spdx} reconocida por {como}",
                               detalle=("la licencia exige «Copyright (c) <año> <titular>» y no "
                                        "hay una línea con año y titular reales"))],
                ), spdx
            numero, linea = titular
            return subcheck(
                id_sub, desc, Veredicto.CUMPLE, sujeto,
                [Evidencia(fuente=ctx.rel(ruta), extracto=f"{spdx} reconocida por {como}",
                           detalle="licencia reconocida"),
                 evidencia_linea(ctx, ruta, numero, linea, detalle="año y titular")],
            ), spdx
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=f"{spdx} reconocida por {como}",
                       detalle=f"{len(texto)} caracteres")],
        ), spdx

    def _manifiesto(self, ctx: Contexto, ruta: Path, archivo: Path | None,
                    spdx: str | None) -> ResultadoSubcheck | None:
        id_sub, desc = "LICENCIA_MANIFIESTO", self.descripciones["LICENCIA_MANIFIESTO"]
        rel = ctx.rel(ruta)
        sujeto = sujeto_de(ctx, "licencia", rel)
        texto = ctx.leer(ruta)
        if texto is None:
            return subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                            motivo=f"{rel} no pudo leerse como texto.")
        try:
            declarada, archivo_declarado, privado = _licencia_de_manifiesto(ruta, texto)
        except (ValueError, tomllib.TOMLDecodeError) as exc:
            return subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                            motivo=recortar(f"{rel} no se pudo interpretar: {exc}", 240))
        if privado:
            return None             # paquete privado: no se distribuye, no es sujeto
        if declarada is None and archivo_declarado is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [Evidencia(fuente=rel, extracto="el manifiesto no declara licencia",
                           detalle="quien instala el paquete no ve bajo qué licencia lo recibe")],
            )
        if archivo_declarado is not None:
            destino = (ruta.parent / archivo_declarado)
            veredicto = Veredicto.CUMPLE if destino.is_file() else Veredicto.NO_CUMPLE
            return subcheck(
                id_sub, desc, veredicto, sujeto,
                [Evidencia(fuente=rel, extracto=f"license = {{ file = \"{archivo_declarado}\" }}",
                           detalle="el archivo declarado existe" if destino.is_file()
                           else "el archivo declarado no existe")],
            )
        if spdx is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo=(f"{rel} declara «{declarada}», pero no hay archivo de licencia "
                        f"reconocido contra el cual compararla."),
            )
        assert declarada is not None
        evidencias = [Evidencia(fuente=rel, extracto=f"declara «{declarada}»",
                                detalle=f"el archivo {ctx.rel(archivo) if archivo else '?'} es {spdx}")]
        veredicto = Veredicto.CUMPLE if _coinciden(declarada, spdx) else Veredicto.NO_CUMPLE
        return subcheck(id_sub, desc, veredicto, sujeto, evidencias)


# ==========================================================================
# documentacion.politica-de-seguridad
# ==========================================================================

_RE_URL_REPORTE = re.compile(
    r"https?://\S*(?:/security/advisories|/security\b|hackerone\.com|bugcrowd\.com|huntr\.(?:dev|com)"
    r"|intigriti\.com|openbugbounty)\S*", re.IGNORECASE,
)
_RE_PLAZO = re.compile(
    r"(?i)\b(\d{1,3})\s*(horas?|hrs?|hours?|d[ií]as?|days?|semanas?|weeks?)\b"
)


@registrar("documentacion.politica-de-seguridad")
class SondaPoliticaSeguridad(Sonda):
    """SECURITY.md (raíz, .github/ o docs/) debe ofrecer un canal PRIVADO de reporte
    (correo que no sea de ejemplo o enlace a avisos de seguridad / programa de
    recompensas), comprometer un plazo de respuesta (número y unidad de tiempo) y no
    conservar marcadores de plantilla. Tres sujetos: canal, plazo, adaptada."""

    titulo = "Política de seguridad con canal privado y plazo"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "POLITICA_CANAL": "La política ofrece un canal privado para reportar vulnerabilidades",
        "POLITICA_PLAZO": "La política compromete un plazo de respuesta",
        "POLITICA_ADAPTADA": "La política no conserva marcadores de plantilla",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        politicas = [p for p in ctx.buscar(PATRONES_POLITICA) if not _es_de_terceros(ctx.rel(p))]
        sujetos = {"POLITICA_CANAL": "canal", "POLITICA_PLAZO": "plazo",
                   "POLITICA_ADAPTADA": "adaptada"}
        if not politicas:
            evidencia = evidencia_de_ausencia(ctx, list(PATRONES_POLITICA))
            return self._check([
                subcheck(i, d, Veredicto.NO_CUMPLE, sujeto_de(ctx, "politica", sujetos[i]), [evidencia])
                for i, d in self.descripciones.items()
            ])
        ruta = politicas[0]
        texto = ctx.leer(ruta)
        if texto is None:
            return self._check([
                subcheck(i, d, Veredicto.NO_MEDIBLE, sujeto_de(ctx, "politica", sujetos[i]),
                         motivo=f"{ctx.rel(ruta)} no pudo leerse como texto.")
                for i, d in self.descripciones.items()
            ])
        lineas = list(enumerate(texto.splitlines(), start=1))
        return self._check([
            self._canal(ctx, ruta, lineas, sujeto_de(ctx, "politica", "canal")),
            self._plazo(ctx, ruta, lineas, sujeto_de(ctx, "politica", "plazo")),
            self._adaptada(ctx, ruta, lineas, sujeto_de(ctx, "politica", "adaptada")),
        ])

    def _canal(self, ctx: Contexto, ruta: Path, lineas: list[tuple[int, str]], sujeto: str) -> ResultadoSubcheck:
        id_sub, desc = "POLITICA_CANAL", self.descripciones["POLITICA_CANAL"]
        for numero, linea in lineas:
            correo = _correo_valido(linea)
            if correo or _RE_URL_REPORTE.search(linea):
                return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto,
                                [evidencia_linea(ctx, ruta, numero, linea,
                                                 detalle="canal privado de reporte")])
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=f"{len(lineas)} líneas leídas sin canal privado",
                       detalle=("se buscó un correo que no sea de ejemplo o un enlace a avisos de "
                                "seguridad / programa de recompensas; un issue público no es privado"))],
        )

    def _plazo(self, ctx: Contexto, ruta: Path, lineas: list[tuple[int, str]], sujeto: str) -> ResultadoSubcheck:
        id_sub, desc = "POLITICA_PLAZO", self.descripciones["POLITICA_PLAZO"]
        for numero, linea in lineas_de_prosa(lineas):
            casa = _RE_PLAZO.search(linea)
            if casa:
                return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto,
                                [evidencia_linea(ctx, ruta, numero, linea,
                                                 detalle=f"plazo «{casa.group(0)}»")])
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=f"{len(lineas)} líneas leídas sin plazo",
                       detalle="se buscó un número con unidad de tiempo (horas, días, semanas)")],
        )

    def _adaptada(self, ctx: Contexto, ruta: Path, lineas: list[tuple[int, str]], sujeto: str) -> ResultadoSubcheck:
        id_sub, desc = "POLITICA_ADAPTADA", self.descripciones["POLITICA_ADAPTADA"]
        marcadores = marcadores_de_plantilla(lineas_de_prosa(lineas))
        if marcadores:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [evidencia_linea(ctx, ruta, n, dict(lineas)[n], detalle=f"marcador de plantilla «{m}»")
                 for n, m in marcadores[:5]],
            )
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=f"{len(lineas)} líneas revisadas, 0 marcadores",
                       detalle="se buscaron <relleno>, AAAA-MM-DD, TODO/TBD/FIXME y descripciones «…»")],
        )
