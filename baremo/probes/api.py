"""Sonda `api.openapi-documentada` (N07): cada operación de la API está documentada.

El sujeto es la OPERACIÓN (método + ruta de cada especificación OpenAPI o Swagger del
repositorio), así que el cumplimiento del check ES el porcentaje de operaciones
documentadas: 45 de 50 operaciones da 90 %, no «advertencia».

Una operación cumple cuando tiene:
  · resumen o descripción no vacíos;
  · respuestas documentadas: al menos una, cada una con descripción, y al menos una de
    éxito (2xx, 3xx o `default`);
  · esquemas: cada parámetro declara su tipo o esquema, el cuerpo de la petición declara
    esquema por tipo de contenido y cada respuesta 2xx con cuerpo (todas salvo 204/205)
    declara esquema. Las referencias `$ref` locales y a archivos del repositorio se
    resuelven; una que no se puede resolver hace a la operación NO_MEDIBLE.

Sin especificación, la sonda busca si el código EXPONE rutas HTTP (decoradores y
registros de rutas con una ruta literal; las pruebas y los ejemplos no cuentan). Si las
expone, es NO_CUMPLE: hay API y no hay contrato versionado. Si no expone nada, es
NO_MEDIBLE: no hay API que documentar, y eso no se acredita como cumplimiento.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

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
from baremo.probes._apoyo import es_externo, es_ruta_de_pruebas

METODOS: tuple[str, ...] = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
CODIGOS_SIN_CUERPO: frozenset[str] = frozenset({"204", "205"})

_RE_SPEC_YAML = re.compile(r"(?m)^(openapi|swagger)\s*:\s*[\"']?\d")
_RE_SPEC_JSON = re.compile(r"\"(openapi|swagger)\"\s*:\s*\"\d")

EXTENSIONES_CODIGO: frozenset[str] = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".go", ".java", ".kt", ".cs",
    ".rb", ".php",
})
SEGMENTOS_EJEMPLO: frozenset[str] = frozenset({"examples", "ejemplos", "samples", "muestras"})

#: (marco, patrón de la declaración de una ruta HTTP, nombres de archivo a los que se limita)
DECLARACIONES_DE_RUTA: tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...] = (
    ("decorador de ruta (FastAPI/Flask)", re.compile(
        r"^\s*@\w+(?:\.\w+)*\.(?:get|post|put|patch|delete|route|api_route|websocket)\(\s*[rbuf]?[\"']/"), ()),
    ("registro de ruta (Express/Fastify)", re.compile(
        r"\b(?:app|router|server|fastify)\.(?:get|post|put|patch|delete|all|route)\(\s*[\"'`]/"), ()),
    ("decorador de ruta (NestJS)", re.compile(r"^\s*@(?:Get|Post|Put|Patch|Delete|All)\("), ()),
    ("anotación de ruta (Spring)", re.compile(r"^\s*@(?:Get|Post|Put|Patch|Delete|Request)Mapping\b"), ()),
    ("atributo de ruta (ASP.NET)", re.compile(r"^\s*\[(?:Http(?:Get|Post|Put|Patch|Delete)|Route)\b"), ()),
    ("registro de ruta (Go)", re.compile(r"(?:\bHandleFunc|\.(?:GET|POST|PUT|PATCH|DELETE))\(\s*\"/"), ()),
    ("manejador de ruta (Next.js)", re.compile(
        r"^\s*export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|PATCH|DELETE)\s*\("),
     ("route.ts", "route.js", "route.mjs")),
    ("ruta de Django", re.compile(r"^\s*(?:re_)?path\(\s*r?[\"']"), ("urls.py",)),
)


class RefNoResuelta(Exception):
    """Una referencia $ref que no se pudo resolver dentro del repositorio."""


@dataclass
class Especificacion:
    ruta: Path
    datos: dict[str, Any]
    texto: str

    @property
    def version(self) -> int:
        return 2 if "swagger" in self.datos else 3


def _cargar(ruta: Path, texto: str) -> Any:
    if ruta.suffix.lower() == ".json":
        return json.loads(texto)
    return yaml.safe_load(texto)


def _puntero(doc: Any, puntero: str) -> Any:
    nodo = doc
    for parte in [p for p in puntero.split("/") if p]:
        parte = parte.replace("~1", "/").replace("~0", "~")
        if isinstance(nodo, dict) and parte in nodo:
            nodo = nodo[parte]
        elif isinstance(nodo, list) and parte.isdigit() and int(parte) < len(nodo):
            nodo = nodo[int(parte)]
        else:
            raise RefNoResuelta(f"#{puntero}")
    return nodo


class Resolutor:
    """Resuelve `$ref` locales (#/…) y a archivos del repositorio, con tope de saltos."""

    def __init__(self, ctx: Contexto, spec: Especificacion) -> None:
        self.ctx = ctx
        self.cache: dict[Path, Any] = {spec.ruta.resolve(): spec.datos}

    def __call__(self, nodo: Any, base: Path) -> tuple[Any, Path]:
        saltos = 0
        while isinstance(nodo, dict) and isinstance(nodo.get("$ref"), str):
            saltos += 1
            ref = nodo["$ref"]
            if saltos > 25:
                raise RefNoResuelta(f"{ref} (cadena de referencias demasiado larga o cíclica)")
            archivo, _, puntero = ref.partition("#")
            if archivo:
                if es_externo(archivo):
                    raise RefNoResuelta(f"{ref} (referencia a un destino externo)")
                base = (base.parent / archivo).resolve()
                if base not in self.cache:
                    texto = self.ctx.leer(base) if base.is_file() else None
                    if texto is None:
                        raise RefNoResuelta(f"{ref} (archivo ausente o ilegible)")
                    try:
                        self.cache[base] = _cargar(base, texto)
                    except (ValueError, yaml.YAMLError) as exc:
                        raise RefNoResuelta(f"{ref} ({exc.__class__.__name__})") from exc
            nodo = _puntero(self.cache[base.resolve()], puntero)
        return nodo, base


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def evaluar_operacion(op: dict[str, Any], metodo: str, params_ruta: list[Any],
                      spec: Especificacion, resolver: Resolutor) -> list[str]:
    """Faltas de documentación de una operación (lista vacía = documentada)."""
    faltas: list[str] = []
    base = spec.ruta.resolve()
    if not (_texto(op.get("summary")) or _texto(op.get("description"))):
        faltas.append("sin summary ni description")

    for crudo in list(params_ruta) + list(op.get("parameters") or []):
        param, _ = resolver(crudo, base)
        if not isinstance(param, dict):
            faltas.append("parámetro ilegible")
            continue
        nombre = param.get("name", "?")
        if spec.version == 2:
            if param.get("in") == "body":
                if "schema" not in param:
                    faltas.append(f"cuerpo «{nombre}» sin schema")
            elif "type" not in param:
                faltas.append(f"parámetro «{nombre}» sin type")
        elif "schema" not in param and "content" not in param:
            faltas.append(f"parámetro «{nombre}» sin schema")

    if spec.version == 3 and "requestBody" in op:
        cuerpo, base_cuerpo = resolver(op["requestBody"], base)
        contenido = cuerpo.get("content") if isinstance(cuerpo, dict) else None
        if not isinstance(contenido, dict) or not contenido:
            faltas.append("requestBody sin content")
        else:
            for tipo, medio in contenido.items():
                if not isinstance(medio, dict) or "schema" not in medio:
                    faltas.append(f"requestBody {tipo} sin schema")

    respuestas = op.get("responses")
    if not isinstance(respuestas, dict) or not respuestas:
        faltas.append("sin respuestas documentadas")
        return faltas
    exitos = [str(c) for c in respuestas if str(c)[:1] in ("2", "3") or str(c) == "default"]
    if not exitos:
        faltas.append("ninguna respuesta de éxito (2xx, 3xx o default)")
    for codigo, crudo in respuestas.items():
        codigo = str(codigo)
        respuesta, _ = resolver(crudo, base)
        if not isinstance(respuesta, dict):
            faltas.append(f"respuesta {codigo} ilegible")
            continue
        if not _texto(respuesta.get("description")):
            faltas.append(f"respuesta {codigo} sin description")
        if not codigo.startswith("2") or codigo in CODIGOS_SIN_CUERPO or metodo in ("head", "options"):
            continue
        if spec.version == 2:
            if "schema" not in respuesta:
                faltas.append(f"respuesta {codigo} sin schema")
            continue
        contenido = respuesta.get("content")
        if not isinstance(contenido, dict) or not contenido:
            faltas.append(f"respuesta {codigo} sin content ni schema")
            continue
        for tipo, medio in contenido.items():
            if not isinstance(medio, dict) or "schema" not in medio:
                faltas.append(f"respuesta {codigo} {tipo} sin schema")
    return faltas


def localizar_especificaciones(ctx: Contexto) -> tuple[list[Especificacion], list[tuple[Path, str]]]:
    """(especificaciones válidas, [(ruta, error)] de las que parecen spec y no se leen)."""
    validas: list[Especificacion] = []
    rotas: list[tuple[Path, str]] = []
    for ruta in ctx.archivos:
        sufijo = ruta.suffix.lower()
        if sufijo not in (".yaml", ".yml", ".json"):
            continue
        texto = ctx.leer(ruta)
        if not texto:
            continue
        patron = _RE_SPEC_JSON if sufijo == ".json" else _RE_SPEC_YAML
        if not patron.search(texto[:20000]):
            continue
        try:
            datos = _cargar(ruta, texto)
        except (ValueError, yaml.YAMLError) as exc:
            rotas.append((ruta, recortar(f"{exc.__class__.__name__}: {exc}", 200)))
            continue
        if isinstance(datos, dict) and ("openapi" in datos or "swagger" in datos):
            validas.append(Especificacion(ruta, datos, texto))
    return validas, rotas


def localizar_rutas_en_codigo(ctx: Contexto) -> list[tuple[Path, int, str, str]]:
    halladas: list[tuple[Path, int, str, str]] = []
    for ruta in ctx.archivos:
        if ruta.suffix.lower() not in EXTENSIONES_CODIGO:
            continue
        relativa = ctx.rel(ruta)
        partes = relativa.lower().split("/")
        if es_ruta_de_pruebas(relativa) or any(p in SEGMENTOS_EJEMPLO for p in partes[:-1]):
            continue
        texto = ctx.leer(ruta)
        if not texto:
            continue
        for numero, linea in enumerate(texto.splitlines(), start=1):
            for marco, patron, nombres in DECLARACIONES_DE_RUTA:
                if nombres and ruta.name.lower() not in nombres:
                    continue
                if patron.search(linea):
                    halladas.append((ruta, numero, linea, marco))
                    break
            if len(halladas) >= 50:
                return halladas
    return halladas


def _linea_de_ruta(texto: str, ruta_api: str) -> int:
    patron = re.compile(r"^\s*[\"']?" + re.escape(ruta_api) + r"[\"']?\s*:")
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if patron.match(linea):
            return numero
    return 1


@registrar("api.openapi-documentada")
class SondaOpenApi(Sonda):
    """Por cada especificación OpenAPI/Swagger del repositorio y cada operación (método
    + ruta): resumen o descripción, respuestas con descripción y al menos una de éxito,
    y esquemas en parámetros, cuerpo y respuestas 2xx con cuerpo. El cumplimiento del
    check es el porcentaje de operaciones documentadas. Sin especificación: NO_CUMPLE
    si el código declara rutas HTTP, NO_MEDIBLE si el repositorio no expone API."""

    titulo = "API documentada operación por operación (OpenAPI)"
    eje = "API"
    peso = 1.0
    descripciones = {
        "API_OPERACION": "La operación tiene resumen, respuestas documentadas y esquemas",
        "API_CONTRATO": "La API que expone el código tiene una especificación OpenAPI versionada",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        specs, rotas = localizar_especificaciones(ctx)
        subchecks: list[ResultadoSubcheck] = []
        for ruta, error in rotas:
            subchecks.append(subcheck(
                "API_OPERACION", self.descripciones["API_OPERACION"], Veredicto.NO_MEDIBLE,
                sujeto_de(ctx, "especificacion", ctx.rel(ruta)),
                motivo=(f"{ctx.rel(ruta)} parece una especificación OpenAPI pero no se pudo "
                        f"interpretar ({error}); haría falta un documento válido para contar "
                        f"sus operaciones."),
            ))
        for spec in specs:
            subchecks.extend(self._especificacion(ctx, spec))
        if specs or rotas:
            return self._check(subchecks)
        return self._check([self._sin_especificacion(ctx)])

    def _especificacion(self, ctx: Contexto, spec: Especificacion) -> list[ResultadoSubcheck]:
        id_sub, desc = "API_OPERACION", self.descripciones["API_OPERACION"]
        rel = ctx.rel(spec.ruta)
        rutas = spec.datos.get("paths")
        if not isinstance(rutas, dict) or not rutas:
            return [subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, sujeto_de(ctx, "especificacion", rel),
                [Evidencia(fuente=rel, extracto="la especificación no declara operaciones",
                           detalle="«paths» vacío o ausente: no documenta ninguna operación")],
            )]
        resolver = Resolutor(ctx, spec)
        evaluadas: list[tuple[str, str, int, list[str] | None, str]] = []
        for ruta_api, item in rutas.items():
            try:
                item, _ = resolver(item, spec.ruta.resolve())
            except RefNoResuelta as exc:
                evaluadas.append((ruta_api, "*", _linea_de_ruta(spec.texto, str(ruta_api)), None, str(exc)))
                continue
            if not isinstance(item, dict):
                continue
            params_ruta = item.get("parameters") or []
            for metodo in METODOS:
                op = item.get(metodo)
                if not isinstance(op, dict):
                    continue
                linea = _linea_de_ruta(spec.texto, str(ruta_api))
                try:
                    faltas = evaluar_operacion(op, metodo, params_ruta, spec, resolver)
                    evaluadas.append((str(ruta_api), metodo, linea, faltas, ""))
                except RefNoResuelta as exc:
                    evaluadas.append((str(ruta_api), metodo, linea, None, str(exc)))

        medidas = [e for e in evaluadas if e[3] is not None]
        documentadas = sum(1 for e in medidas if not e[3])
        resumen = (f"{documentadas}/{len(medidas)} operaciones documentadas "
                   f"({100 * documentadas / len(medidas):.0f} %)" if medidas else "0 operaciones medibles")
        resultado: list[ResultadoSubcheck] = []
        for ruta_api, metodo, linea, faltas, error in evaluadas:
            sujeto = sujeto_de(ctx, "operacion", f"{rel}#{metodo.upper()} {ruta_api}")
            if faltas is None:
                resultado.append(subcheck(
                    id_sub, desc, Veredicto.NO_MEDIBLE, sujeto,
                    motivo=(f"No se pudo resolver la referencia {error} en {rel}: sin el "
                            f"documento referido no se puede afirmar qué documenta la operación."),
                ))
            elif faltas:
                resultado.append(subcheck(
                    id_sub, desc, Veredicto.NO_CUMPLE, sujeto,
                    [Evidencia(fuente=rel, extracto=recortar("; ".join(faltas), 200),
                               detalle=f"línea {linea} · {resumen}")],
                ))
            else:
                resultado.append(subcheck(
                    id_sub, desc, Veredicto.CUMPLE, sujeto,
                    [Evidencia(fuente=rel,
                               extracto=f"{metodo.upper()} {ruta_api}: resumen, respuestas y esquemas",
                               detalle=f"línea {linea} · {resumen}")],
                ))
        return resultado

    def _sin_especificacion(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "API_CONTRATO", self.descripciones["API_CONTRATO"]
        sujeto = sujeto_de(ctx, "api", "contrato")
        rutas = localizar_rutas_en_codigo(ctx)
        if rutas:
            evidencias = [evidencia_linea(ctx, r, n, l, detalle=f"{marco}: el código expone una ruta HTTP")
                          for r, n, l, marco in rutas[:5]]
            evidencias.append(evidencia_de_ausencia(
                ctx, ["*.yaml/*.yml/*.json con «openapi:» o «swagger:» en la raíz del documento"],
                detalle=f"{len(rutas)} declaraciones de ruta en el código, ninguna especificación"))
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, sujeto, evidencias)
        if ctx.barrido_truncado:
            motivo = ("El barrido se truncó: no se puede afirmar que el repositorio no tenga "
                      "especificación ni rutas HTTP sobre un universo incompleto.")
        else:
            motivo = (f"El repositorio no expone API: ninguna especificación OpenAPI/Swagger y "
                      f"ninguna declaración de ruta HTTP en el código ({len(ctx.archivos)} "
                      f"archivos inspeccionados, sin contar pruebas ni ejemplos). No hay "
                      f"operaciones que documentar; si la API existe en otro repositorio, se "
                      f"mide allí.")
        return subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, sujeto, motivo=motivo)
