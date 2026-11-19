"""Sondas de pruebas: E2E (N08), paridad contra golden files (N08b) y regla↔prueba (N03).

Las tres miden sustancia, no nombres:

  · `pruebas.e2e-presente`: una carpeta `e2e/` no acredita nada. Acredita un archivo de
    prueba E2E que declara una prueba, EJERCE el sistema desde fuera (navega una
    página, llama por HTTP o ejecuta el programa como proceso) y AFIRMA algo. Sujeto:
    cada archivo E2E.
  · `pruebas.paridad-golden`: un archivo de referencia que ninguna prueba compara es
    un oráculo huérfano. Sujeto: cada archivo golden; cumple si una prueba lo nombra
    (o nombra su carpeta) y compara por igualdad.
  · `pruebas.regla-por-prueba`: si existe `docs/reglas.md`, cada regla de su tabla
    debe apuntar a pruebas que EXISTEN (archivo y nombre de función) y que no están
    marcadas para saltarse. Sujeto: cada regla. Sin el mapa, NO_MEDIBLE: sin la lista
    de reglas no se puede afirmar nada sobre su cobertura.
"""
from __future__ import annotations

import ast
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
    sujeto_de,
)
from baremo.probes._apoyo import es_ruta_de_pruebas, lineas_de_prosa

# ==========================================================================
# pruebas.e2e-presente
# ==========================================================================

SEGMENTOS_E2E: frozenset[str] = frozenset({
    "e2e", "end-to-end", "end2end", "cypress", "playwright", "acceptance", "aceptacion",
    "aceptación",
})
_RE_NOMBRE_E2E = re.compile(r"(?i)(?:^|[._-])e2e(?:[._-]|$)|\.cy\.[cm]?[jt]sx?$|\.feature$")
EXTENSIONES_E2E: frozenset[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".go", ".java", ".cs", ".rb", ".feature",
})
_RE_CONFIG_E2E = re.compile(r"(?i)^(playwright|cypress)\.config\.[cm]?[jt]s$")

_RE_DECLARA_PRUEBA = re.compile(
    r"^\s*(?:async\s+)?def\s+test_\w*|\b(?:test|it)\s*\(\s*[\"'`]|\bfunc\s+Test\w*\s*\("
    r"|^\s*(?:Scenario|Escenario)(?:\s+Outline)?\s*:|@Test\b|\[(?:Test|Fact)\]"
)
#: (forma de ejercer el sistema desde fuera, patrón)
INTERACCIONES_E2E: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("navega una página", re.compile(
        r"\bpage\.(?:goto|click|fill|getBy\w+|locator)\(|\bcy\.(?:visit|get|request)\(|\bbrowser\.url\("
        r"|\bdriver\.get\(|\bwebdriver\.")),
    ("llama por HTTP", re.compile(
        r"\b(?:request|requests|httpx|client|api|axios)\.(?:get|post|put|patch|delete|fetch)\("
        r"|\bfetch\(\s*[\"'`]https?:|\bsupertest\(")),
    ("ejecuta el programa como proceso", re.compile(
        r"\bsubprocess\.(?:run|Popen|check_output|check_call|call)\(|\bexeca\w*\(|\bexecFile(?:Sync)?\("
        r"|\bspawn(?:Sync)?\(|\bCliRunner\(\)|\bexec\.Command\(")),
    ("ejecuta un escenario", re.compile(r"^\s*(?:When|Cuando)\b")),
)
_RE_AFIRMA = re.compile(
    r"\bassert\b|\bexpect\(|\.should\(|\bself\.assert\w+\(|\bpytest\.raises\(|\bassert\.\w+\("
    r"|^\s*(?:Then|Entonces)\b|\bt\.(?:Error|Fatal)f?\("
)


def _es_candidato_e2e(relativa: str) -> bool:
    partes = relativa.lower().split("/")
    nombre = partes[-1]
    if _RE_CONFIG_E2E.match(nombre) or nombre in ("conftest.py", "__init__.py"):
        return False
    if Path(nombre).suffix not in EXTENSIONES_E2E:
        return False
    return any(p in SEGMENTOS_E2E for p in partes[:-1]) or bool(_RE_NOMBRE_E2E.search(nombre))


@registrar("pruebas.e2e-presente")
class SondaE2e(Sonda):
    """Cada archivo E2E (carpeta e2e/, cypress/, playwright/, acceptance/, o nombre
    *.e2e.*, *.cy.*, *.feature) que declara pruebas debe ejercer el sistema desde fuera
    —navegar una página, llamar por HTTP o ejecutar el programa como proceso— y afirmar
    algo. Sin archivos E2E con pruebas: NO_CUMPLE (las configuraciones sin pruebas se
    citan como evidencia)."""

    titulo = "Pruebas de extremo a extremo que ejercen y afirman"
    eje = "Pruebas"
    peso = 1.0
    descripciones = {
        "E2E_ARCHIVO": "El archivo E2E ejerce el sistema desde fuera y afirma el resultado",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        id_sub, desc = "E2E_ARCHIVO", self.descripciones["E2E_ARCHIVO"]
        subchecks: list[ResultadoSubcheck] = []
        sin_pruebas: list[str] = []
        for ruta in ctx.archivos:
            relativa = ctx.rel(ruta)
            if not _es_candidato_e2e(relativa):
                continue
            texto = ctx.leer(ruta)
            sujeto = sujeto_de(ctx, "e2e", relativa)
            if texto is None:
                subchecks.append(subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                                          motivo=f"{relativa} no pudo leerse como texto."))
                continue
            lineas = list(enumerate(texto.splitlines(), start=1))
            declara = next(((n, l) for n, l in lineas if _RE_DECLARA_PRUEBA.search(l)), None)
            if declara is None:
                sin_pruebas.append(relativa)        # apoyo (páginas, ayudantes): no es sujeto
                continue
            interaccion = next(((n, l, nombre) for n, l in lineas
                                for nombre, patron in INTERACCIONES_E2E if patron.search(l)), None)
            afirmacion = next(((n, l) for n, l in lineas if _RE_AFIRMA.search(l)), None)
            if interaccion and afirmacion:
                subchecks.append(subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto, [
                    evidencia_linea(ctx, ruta, interaccion[0], interaccion[1], detalle=interaccion[2]),
                    evidencia_linea(ctx, ruta, afirmacion[0], afirmacion[1], detalle="afirma el resultado"),
                ]))
                continue
            faltas = ([] if interaccion else ["no ejerce el sistema desde fuera (página, HTTP o proceso)"]) \
                + ([] if afirmacion else ["no afirma nada: una prueba que sólo recorre no prueba"])
            subchecks.append(subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto, [
                evidencia_linea(ctx, ruta, declara[0], declara[1], detalle="; ".join(faltas)),
            ]))
        if subchecks:
            return self._check(subchecks)
        sujeto = sujeto_de(ctx, "e2e", "suite")
        if ctx.barrido_truncado:
            return self._check([subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                motivo="El barrido se truncó: no se puede afirmar que no haya pruebas E2E.")])
        configs = [ctx.rel(r) for r in ctx.archivos if _RE_CONFIG_E2E.match(r.name.lower())]
        detalle = (f"configuración E2E sin pruebas: {', '.join(configs[:3])}" if configs else
                   f"archivos de apoyo E2E sin pruebas: {', '.join(sin_pruebas[:3])}" if sin_pruebas else
                   f"{len(ctx.archivos)} archivos inspeccionados")
        return self._check([subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
            [evidencia_de_ausencia(ctx, ["e2e/", "cypress/", "playwright/", "acceptance/",
                                         "*.e2e.*", "*.cy.*", "*.feature"], detalle=detalle)],
        )])


# ==========================================================================
# pruebas.paridad-golden
# ==========================================================================

SEGMENTOS_GOLDEN: frozenset[str] = frozenset({
    "golden", "goldens", "oraculo", "oraculos", "oráculo", "oráculos", "oracle", "oracles",
})
_RE_NOMBRE_GOLDEN = re.compile(r"(?i)(?:^|[._-])golden(?:[._-]|$)")
EXTENSIONES_CODIGO: frozenset[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".go", ".java", ".cs", ".rb", ".php", ".kt",
})
_NOMBRES_NO_GOLDEN: frozenset[str] = frozenset({".gitkeep", ".gitattributes", "readme.md", "readme"})
_RE_COMPARA = re.compile(
    r"\bassert\b[^\n]*==|\bassert\w*Equal\w*\(|\bassert_equal\(|\bassert_frame_equal\(|\.equals\("
    r"|\btoEqual\(|\btoStrictEqual\(|\btoBe\(|\btoMatchFile\(|\bfilecmp\.cmp\(|\bcmp\.Diff\("
    r"|\breflect\.DeepEqual\(|\bassert\.(?:deepStrictEqual|strictEqual|equal)\("
)


def _es_golden(relativa: str) -> bool:
    partes = relativa.lower().split("/")
    nombre = partes[-1]
    if nombre in _NOMBRES_NO_GOLDEN or Path(nombre).suffix in EXTENSIONES_CODIGO:
        return False
    return any(p in SEGMENTOS_GOLDEN for p in partes[:-1]) or bool(_RE_NOMBRE_GOLDEN.search(nombre))


def _archivos_de_prueba(ctx: Contexto) -> list[tuple[Path, str]]:
    salida: list[tuple[Path, str]] = []
    for ruta in ctx.archivos:
        if ruta.suffix.lower() not in EXTENSIONES_CODIGO or not es_ruta_de_pruebas(ctx.rel(ruta)):
            continue
        texto = ctx.leer(ruta)
        if texto:
            salida.append((ruta, texto))
    return salida


@registrar("pruebas.paridad-golden")
class SondaParidadGolden(Sonda):
    """Cada archivo de referencia golden (carpeta golden/, oraculo/, oracle/ o nombre
    *golden*) debe estar comparado por una prueba: un archivo de prueba que lo nombra
    (por nombre de archivo o por su carpeta, entre comillas) y que compara por igualdad.
    Un golden que ninguna prueba compara es un oráculo huérfano: NO_CUMPLE. Sin goldens:
    NO_CUMPLE con el universo inspeccionado."""

    titulo = "Paridad contra archivos de referencia (golden)"
    eje = "Pruebas"
    peso = 1.0
    descripciones = {
        "GOLDEN_COMPARADO": "Una prueba compara la salida contra el archivo de referencia",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        id_sub, desc = "GOLDEN_COMPARADO", self.descripciones["GOLDEN_COMPARADO"]
        goldens = [r for r in ctx.archivos if _es_golden(ctx.rel(r))]
        if not goldens:
            sujeto = sujeto_de(ctx, "golden", "oraculo")
            if ctx.barrido_truncado:
                return self._check([subcheck(
                    id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                    motivo="El barrido se truncó: no se puede afirmar que no haya archivos golden.")])
            return self._check([subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                [evidencia_de_ausencia(ctx, ["golden/", "oraculo/", "oracle/", "*golden*"])],
            )])
        pruebas = _archivos_de_prueba(ctx)
        return self._check([self._golden(ctx, ruta, pruebas) for ruta in goldens])

    def _golden(self, ctx: Contexto, ruta: Path, pruebas: list[tuple[Path, str]]) -> ResultadoSubcheck:
        id_sub, desc = "GOLDEN_COMPARADO", self.descripciones["GOLDEN_COMPARADO"]
        relativa = ctx.rel(ruta)
        sujeto = sujeto_de(ctx, "golden", relativa)
        carpeta = ruta.parent.name
        agujas = [re.compile(re.escape(ruta.name)), re.compile(re.escape(ruta.stem) + r"\b"),
                  re.compile(r"[\"'`/]" + re.escape(carpeta) + r"[\"'`/]")]
        nombrada_sin_comparar: list[str] = []
        for prueba, texto in pruebas:
            if prueba == ruta:
                continue
            lineas = texto.splitlines()
            mencion = next(((n, l) for n, l in enumerate(lineas, start=1)
                            if any(a.search(l) for a in agujas)), None)
            if mencion is None:
                continue
            comparacion = next(((n, l) for n, l in enumerate(lineas, start=1) if _RE_COMPARA.search(l)), None)
            if comparacion is None:
                nombrada_sin_comparar.append(ctx.rel(prueba))
                continue
            return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto, [
                evidencia_linea(ctx, prueba, mencion[0], mencion[1], detalle=f"la prueba lee {relativa}"),
                evidencia_linea(ctx, prueba, comparacion[0], comparacion[1], detalle="compara por igualdad"),
            ])
        detalle = (f"la nombran sin comparar por igualdad: {', '.join(nombrada_sin_comparar[:3])}"
                   if nombrada_sin_comparar else
                   f"{len(pruebas)} archivos de prueba revisados; ninguno nombra el archivo ni su carpeta")
        return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                        [Evidencia(fuente=relativa, extracto="oráculo huérfano: ninguna prueba lo compara",
                                   detalle=detalle)])


# ==========================================================================
# pruebas.regla-por-prueba
# ==========================================================================

MAPA_DE_REGLAS_POR_DEFECTO: str = "docs/reglas.md"
_RE_SEPARADOR_TABLA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_RE_REF_ENTRE_COMILLAS = re.compile(r"`([^`]+?::[^`]+?)`")
_RE_REF_SUELTA = re.compile(r"(?<![\w`])([\w./-]+\.\w+::[\w:\[\].-]+)")
_RE_CODIGO = re.compile(r"`[^`]*`")
_SALTOS_PYTHON: frozenset[str] = frozenset({"skip", "xfail"})


def _celdas(linea: str) -> list[str]:
    limpia = linea.strip()
    if limpia.startswith("|"):
        limpia = limpia[1:]
    if limpia.endswith("|"):
        limpia = limpia[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", limpia)]


def leer_reglas(texto: str) -> list[tuple[int, str, list[str]]]:
    """(línea, identificador de la regla, referencias archivo::prueba) por fila de tabla.

    Sólo cuentan las tablas cuya cabecera tiene una columna de prueba/test.
    """
    reglas: list[tuple[int, str, list[str]]] = []
    lineas = lineas_de_prosa(enumerate(texto.splitlines(), start=1))
    crudas = dict(enumerate(texto.splitlines(), start=1))
    en_tabla = False
    for indice, (numero, linea) in enumerate(lineas):
        if _RE_SEPARADOR_TABLA.match(linea) and indice > 0:
            cabecera = lineas[indice - 1][1]
            en_tabla = "|" in cabecera and bool(re.search(r"(?i)prueba|test", cabecera))
            continue
        if not linea.strip().startswith("|") and "|" not in linea:
            en_tabla = False
            continue
        if not en_tabla:
            continue
        cruda = crudas[numero]          # con los `code spans`: ahí viven las referencias
        celdas = _celdas(cruda)
        if not celdas or not any(celdas):
            continue
        identificador = re.sub(r"[*_`]", "", celdas[0]).strip() or f"fila {numero}"
        referencias = _RE_REF_ENTRE_COMILLAS.findall(cruda)
        sin_comillas = _RE_CODIGO.sub(" ", cruda)
        referencias += [r for r in _RE_REF_SUELTA.findall(sin_comillas) if r not in referencias]
        reglas.append((numero, identificador, [r.strip() for r in referencias]))
    return reglas



def _decorador_salta(decorador: ast.expr) -> bool:
    nodo = decorador.func if isinstance(decorador, ast.Call) else decorador
    nombre = ""
    while isinstance(nodo, ast.Attribute):
        nombre = nodo.attr if not nombre else nombre
        nodo = nodo.value
    if isinstance(nodo, ast.Name) and not nombre:
        nombre = nodo.id
    return nombre in _SALTOS_PYTHON


def _pruebas_python(texto: str) -> tuple[dict[str, bool], bool]:
    """({'func' o 'Clase::metodo': ¿se salta?}, ¿todo el módulo se salta?)."""
    arbol = ast.parse(texto)
    pruebas: dict[str, bool] = {}
    modulo_saltado = False
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                                                for t in nodo.targets):
            valores = nodo.value.elts if isinstance(nodo.value, (ast.List, ast.Tuple)) else [nodo.value]
            modulo_saltado = any(_decorador_salta(v) for v in valores)
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pruebas[nodo.name] = any(_decorador_salta(d) for d in nodo.decorator_list)
        elif isinstance(nodo, ast.ClassDef):
            clase_saltada = any(_decorador_salta(d) for d in nodo.decorator_list)
            for hijo in nodo.body:
                if isinstance(hijo, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    pruebas[f"{nodo.name}::{hijo.name}"] = clase_saltada or any(
                        _decorador_salta(d) for d in hijo.decorator_list)
    return pruebas, modulo_saltado


def resolver_referencia(ctx: Contexto, base: Path, referencia: str) -> tuple[str, str]:
    """('ok' | 'falta' | 'saltada' | 'no_medible', detalle)."""
    archivo, _, nombre = referencia.partition("::")
    nombre = re.sub(r"\[.*\]$", "", nombre.strip())
    candidatos = [ctx.ruta_repo / archivo, base / archivo]
    ruta = next((c for c in candidatos if c.is_file()), None)
    if ruta is None:
        return "falta", f"«{archivo}» no existe en el árbol"
    texto = ctx.leer(ruta)
    if texto is None:
        return "no_medible", f"«{archivo}» no pudo leerse"
    sufijo = ruta.suffix.lower()
    if sufijo == ".py":
        try:
            pruebas, modulo_saltado = _pruebas_python(texto)
        except SyntaxError as exc:
            return "no_medible", f"«{archivo}» no es Python válido ({exc.msg}, línea {exc.lineno})"
        if nombre not in pruebas:
            return "falta", f"«{archivo}» no define «{nombre}»"
        if modulo_saltado or pruebas[nombre]:
            return "saltada", f"«{referencia}» está marcada skip/xfail: existe pero no prueba"
        return "ok", referencia
    if sufijo in (".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx"):
        patron = re.compile(r"\b(x?(?:test|it))(\.(?:skip|todo|only))?\s*\(\s*([\"'`])" + re.escape(nombre) + r"\3")
        casa = patron.search(texto)
        if casa is None:
            return "falta", f"«{archivo}» no declara la prueba «{nombre}»"
        if casa.group(1).startswith("x") or casa.group(2) in (".skip", ".todo"):
            return "saltada", f"«{referencia}» está marcada skip/todo: existe pero no prueba"
        return "ok", referencia
    if sufijo == ".go":
        if re.search(r"\bfunc\s+" + re.escape(nombre) + r"\s*\(", texto):
            return "ok", referencia
        return "falta", f"«{archivo}» no define «{nombre}»"
    return "no_medible", f"no se sabe localizar pruebas en archivos {sufijo or 'sin extensión'}"


@registrar("pruebas.regla-por-prueba")
class SondaReglaPorPrueba(Sonda):
    """Lee la tabla de docs/reglas.md (regla → prueba(s) como `archivo::función`) y, por
    cada regla, exige al menos una referencia y que TODAS existan: el archivo en el árbol
    y la función en el archivo (Python por AST; JS/TS y Go por declaración), sin marca de
    skip/xfail/todo. Sin docs/reglas.md o sin reglas legibles: NO_MEDIBLE."""

    titulo = "Cada regla de negocio apunta a pruebas que existen"
    eje = "Pruebas"
    peso = 1.0
    descripciones = {
        "REGLA_CON_PRUEBA": "La regla apunta a pruebas que existen y no se saltan",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        id_sub, desc = "REGLA_CON_PRUEBA", self.descripciones["REGLA_CON_PRUEBA"]
        mapa_rel = str(ctx.convencion("mapa_de_reglas", MAPA_DE_REGLAS_POR_DEFECTO))
        mapa = ctx.ruta_repo / mapa_rel
        sujeto_mapa = sujeto_de(ctx, "reglas", mapa_rel)
        if not mapa.is_file():
            return self._check([subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_mapa,
                motivo=(f"No existe {mapa_rel}: sin la lista de reglas de negocio no se puede "
                        f"afirmar si cada una tiene prueba. Haría falta una tabla «regla → "
                        f"prueba(s)» con referencias `archivo::función`."),
            )])
        texto = ctx.leer(mapa)
        if texto is None:
            return self._check([subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_mapa,
                                         motivo=f"{mapa_rel} no pudo leerse como texto.")])
        reglas = leer_reglas(texto)
        if not reglas:
            return self._check([subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, sujeto_mapa,
                motivo=(f"{mapa_rel} existe pero no tiene ninguna tabla con columna de prueba: no "
                        f"hay reglas que medir. Haría falta una fila por regla con sus "
                        f"referencias `archivo::función`."),
            )])
        return self._check([self._regla(ctx, mapa, n, ident, refs) for n, ident, refs in reglas])

    def _regla(self, ctx: Contexto, mapa: Path, numero: int, identificador: str,
               referencias: list[str]) -> ResultadoSubcheck:
        id_sub, desc = "REGLA_CON_PRUEBA", self.descripciones["REGLA_CON_PRUEBA"]
        sujeto = sujeto_de(ctx, "regla", identificador)
        fila = (ctx.leer(mapa) or "").splitlines()[numero - 1]
        if not referencias:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                            [evidencia_linea(ctx, mapa, numero, fila,
                                             detalle="regla sin prueba: ninguna referencia archivo::función")])
        estados = [(r, *resolver_referencia(ctx, mapa.parent, r)) for r in referencias]
        malas = [(r, e, d) for r, e, d in estados if e in ("falta", "saltada")]
        if malas:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                            [evidencia_linea(ctx, mapa, numero, fila,
                                             detalle=recortar("; ".join(d for _, _, d in malas), 240))])
        dudosas = [d for _, e, d in estados if e == "no_medible"]
        if dudosas:
            return subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                            motivo=recortar("No se pudo verificar: " + "; ".join(dudosas), 300))
        return subcheck(id_sub, desc, Veredicto.CUMPLE, sujeto,
                        [evidencia_linea(ctx, mapa, numero, fila,
                                         detalle=f"{len(referencias)} prueba(s) localizadas en el árbol")])
