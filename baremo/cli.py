"""Interfaz de linea de comandos de Baremo.

    baremo evaluar [rutas...] [--config baremo.yml] [--supresiones supresiones.yml]
                   [--formato texto|json|html] [--salida ARCHIVO]
                   [--umbral-cobertura F] [--minimo F] [--sin-color] [--hoy AAAA-MM-DD]
    baremo sondas
    baremo explicar <SUBCHECK_ID>

Flujo de `evaluar`:
    carga config -> resuelve sujetos -> corre TODAS las sondas del registro sobre CADA
    sujeto -> aplica supresiones -> puntua -> construye manifiesto -> reporta.

Codigos de salida (el detalle importa: es el contrato con el pipeline):
    0  informe publicable y cumplimiento >= --minimo.
    1  informe publicable pero el cumplimiento queda por debajo de --minimo.
    2  informe NO PUBLICABLE por cobertura insuficiente. No es 0 a proposito: un
       reporte que no midio no puede "pasar" en silencio. Esta es la regla que
       distingue a Baremo de un scorecard que premia mirar menos.
    3  error de operacion (config ilegible, sujeto inexistente, id desconocido).
    64 uso incorrecto de la linea de comandos (argparse), para no confundirlo con el 2.

Formato de `baremo.yml` (todo opcional):

    version: 1
    sujetos:                      # rutas a evaluar; equivalen a los argumentos posicionales
      - ./repos/servicio-a
      - nombre: <app>-web         # nombre explicito (si no, el nombre es el de la carpeta)
        ruta: ./repos/web
    alcance:
      declarado: [servicio-a, <app>-web, servicio-b]   # lo que se PRETENDE medir
      excluido:
        servicio-b: "congelado; se retira en el trimestre"
    umbral_cobertura: 0.80
    minimo: 0.70
    supresiones: ./supresiones.yml
    pesos:                        # ajuste del peso de un check concreto
      CI-01: 2.0

Formato de `supresiones.yml`:

    supresiones:
      - subcheck: CI-01.firma
        sujeto: <app>-web         # ausente o "*" = todos los sujetos
        justificacion: "..."
        vence: 2026-12-31
        autorizada_por: "<rol>"

Una supresion sólo convierte un NO_CUMPLE en SUPRIMIDO. Nunca tapa un NO_MEDIBLE:
declarar que se acepta no poder medir seria reabrir el agujero que este modelo cierra.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from baremo import __version__
from baremo.model import (
    Alcance,
    Evidencia,
    ResultadoCheck,
    ResultadoSubcheck,
    Supresion,
    Veredicto,
)
from baremo.report import reporte_html, reporte_json, reporte_texto
from baremo.scoring import UMBRAL_COBERTURA_POR_DEFECTO, Nota, puntuar

# --- codigos de salida -----------------------------------------------------
SALIDA_OK: int = 0
SALIDA_BAJO_MINIMO: int = 1
SALIDA_NO_PUBLICABLE: int = 2
SALIDA_ERROR: int = 3
SALIDA_USO: int = 64

# --- descubrimiento de sondas ---------------------------------------------
PAQUETE_SONDAS: str = "baremo.probes"
_ATRIBUTOS_REGISTRO: tuple[str, ...] = (
    "REGISTRO", "SONDAS", "REGISTRY", "PROBES", "registro", "sondas",
)
_FUNCIONES_REGISTRO: tuple[str, ...] = (
    "registro", "sondas", "todas", "todas_las_sondas", "obtener_registro",
    "cargar_registro", "listar_sondas",
)
_METODOS_EJECUCION: tuple[str, ...] = (
    "evaluar", "correr", "ejecutar", "sondear", "run", "medir",
)
_ATRIBUTOS_CATALOGO: tuple[str, ...] = (
    "subchecks", "SUBCHECKS", "catalogo", "CATALOGO", "descripciones", "DESCRIPCIONES",
)

# Directorios que no aportan a la huella de un sujeto.
_DIRS_IGNORADOS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist", "build",
    ".terraform", ".gradle", ".idea", ".vscode", "target",
})
_MAX_ARCHIVOS_HUELLA: int = 20_000


# ===========================================================================
# Sondas
# ===========================================================================
@dataclass
class SondaRegistrada:
    """Adaptador sobre una sonda del registro.

    El registro lo puebla el paquete `baremo.probes`. Aqui se normaliza para que la
    CLI no dependa de la forma exacta en que cada sonda se declare: basta con exponer
    `id`, `eje`, `peso` y una forma de ejecutarse sobre la ruta de un sujeto.
    """

    id: str
    titulo: str
    eje: str
    peso: float
    descripcion: str
    version: str
    objeto: Any = None

    def _invocable(self) -> Any:
        for nombre in _METODOS_EJECUCION:
            metodo = getattr(self.objeto, nombre, None)
            if callable(metodo):
                return metodo
        return self.objeto if callable(self.objeto) else None

    convenciones: dict = field(default_factory=dict)

    def correr(self, sujeto: str, ruta: Path) -> ResultadoCheck:
        """Ejecuta la sonda sobre un sujeto y normaliza lo que devuelva.

        Si la sonda falla, el resultado es NO_MEDIBLE con el error como motivo: una
        sonda rota baja la COBERTURA, jamas aprueba por defecto.
        """
        funcion = self._invocable()
        if funcion is None:
            return self._no_medible(
                sujeto, "la sonda registrada no expone forma de ejecutarse"
            )
        # Las sondas del registro reciben un Contexto; se mantienen los fallbacks a
        # ruta por compatibilidad con sondas de terceros mas simples.
        intentos = []
        try:
            from baremo.probes import Contexto
            intentos.append(Contexto(ruta_repo=Path(ruta), nombre_sujeto=sujeto,
                                     convenciones=dict(self.convenciones)))
        except Exception:  # noqa: BLE001 - si no hay Contexto, se prueba con la ruta
            pass
        intentos.extend([Path(ruta), str(ruta)])

        ultimo_error: Exception | None = None
        for argumento in intentos:
            try:
                crudo = funcion(argumento)
                break
            except TypeError as exc:
                ultimo_error = exc
                continue
            except Exception as exc:  # noqa: BLE001 - cualquier fallo es NO_MEDIBLE
                return self._no_medible(sujeto, f"{type(exc).__name__}: {exc}")
        else:
            return self._no_medible(
                sujeto, f"no se pudo invocar la sonda: {type(ultimo_error).__name__}: {ultimo_error}"
            )
        return self._normalizar(crudo, sujeto)

    # -- normalizacion ------------------------------------------------------
    def _envoltorio(self, subchecks: list[ResultadoSubcheck]) -> ResultadoCheck:
        return ResultadoCheck(
            id=self.id, titulo=self.titulo, eje=self.eje, peso=self.peso,
            subchecks=subchecks,
        )

    def _no_medible(self, sujeto: str, motivo: str) -> ResultadoCheck:
        return self._envoltorio([
            ResultadoSubcheck(
                id=f"{self.id}.ejecucion",
                descripcion=f"Ejecucion de la sonda {self.id}",
                veredicto=Veredicto.NO_MEDIBLE,
                evidencias=[Evidencia(fuente=f"sonda:{self.id}", extracto=motivo)],
                motivo=motivo,
                sujeto=sujeto,
            )
        ])

    def _normalizar(self, crudo: Any, sujeto: str) -> ResultadoCheck:
        if crudo is None:
            return self._no_medible(sujeto, "la sonda no devolvio resultado")
        if isinstance(crudo, ResultadoCheck):
            check = crudo
        elif isinstance(crudo, ResultadoSubcheck):
            check = self._envoltorio([crudo])
        elif isinstance(crudo, (list, tuple)):
            subchecks = [s for s in crudo if isinstance(s, ResultadoSubcheck)]
            if len(subchecks) != len(crudo):
                return self._no_medible(
                    sujeto, "la sonda devolvio elementos que no son ResultadoSubcheck"
                )
            check = self._envoltorio(subchecks)
        else:
            return self._no_medible(
                sujeto, f"la sonda devolvio un tipo no reconocido: {type(crudo).__name__}"
            )
        for sub in check.subchecks:
            if not sub.sujeto:
                sub.sujeto = sujeto
        return check


def _instanciar(objeto: Any) -> Any:
    """Si la sonda se declara como clase, se intenta instanciar sin argumentos."""
    if inspect.isclass(objeto):
        try:
            return objeto()
        except Exception:  # noqa: BLE001
            return None
    return objeto


def _parece_sonda(objeto: Any) -> bool:
    if inspect.ismodule(objeto):
        return False
    identificador = getattr(objeto, "id", None) or getattr(objeto, "ID", None)
    if not isinstance(identificador, str) or not identificador:
        return False
    if any(callable(getattr(objeto, n, None)) for n in _METODOS_EJECUCION):
        return True
    return callable(objeto) and not inspect.isclass(objeto)


def _adaptar(objeto: Any) -> SondaRegistrada | None:
    instancia = _instanciar(objeto)
    if instancia is None or not _parece_sonda(instancia):
        return None
    identificador = str(getattr(instancia, "id", "") or getattr(instancia, "ID", ""))
    titulo = str(getattr(instancia, "titulo", "") or getattr(instancia, "title", "")) or identificador
    descripcion = str(getattr(instancia, "descripcion", "") or (inspect.getdoc(instancia) or "")).strip()
    try:
        peso = float(getattr(instancia, "peso", 1.0))
    except (TypeError, ValueError):
        peso = 1.0
    return SondaRegistrada(
        id=identificador,
        titulo=titulo,
        eje=str(getattr(instancia, "eje", "") or "sin-eje"),
        peso=peso,
        descripcion=descripcion,
        # La version de la herramienta es un dato DECLARADO: si la sonda no la declara
        # se dice "no declarada" en vez de callarlo.
        version=str(getattr(instancia, "version", "") or "no declarada"),
        objeto=instancia,
    )


def descubrir_sondas() -> list[SondaRegistrada]:
    """Registro de sondas, ordenado por eje e id.

    Busca, en este orden: un atributo de registro en `baremo.probes`, una funcion que
    lo devuelva, y por ultimo un barrido de los submodulos del paquete.
    """
    try:
        # El nombre es la constante PAQUETE_SONDAS, no una entrada del usuario.
        paquete = importlib.import_module(PAQUETE_SONDAS)  # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
    except Exception:  # noqa: BLE001 - sin paquete de sondas, registro vacio
        return []

    crudas: list[Any] = []
    for nombre in _ATRIBUTOS_REGISTRO:
        valor = getattr(paquete, nombre, None)
        if isinstance(valor, (list, tuple, set)):
            crudas.extend(valor)
        elif isinstance(valor, dict):
            crudas.extend(valor.values())
        if crudas:
            break

    if not crudas:
        for nombre in _FUNCIONES_REGISTRO:
            funcion = getattr(paquete, nombre, None)
            if callable(funcion):
                try:
                    resultado = funcion()
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(resultado, dict):
                    crudas.extend(resultado.values())
                elif isinstance(resultado, (list, tuple, set)):
                    crudas.extend(resultado)
                if crudas:
                    break

    if not crudas:
        for info in pkgutil.iter_modules(list(getattr(paquete, "__path__", []))):
            if info.name.startswith("_"):
                continue
            try:
                # Submodulos del propio paquete, listados por pkgutil: no hay entrada externa.
                modulo = importlib.import_module(f"{PAQUETE_SONDAS}.{info.name}")  # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
            except Exception:  # noqa: BLE001
                continue
            for atributo in vars(modulo).values():
                if _parece_sonda(_instanciar(atributo) or atributo):
                    crudas.append(atributo)

    sondas: dict[str, SondaRegistrada] = {}
    for cruda in crudas:
        adaptada = _adaptar(cruda)
        if adaptada is not None:
            sondas.setdefault(adaptada.id, adaptada)
    return sorted(sondas.values(), key=lambda s: (s.eje, s.id))


# ===========================================================================
# Configuracion
# ===========================================================================
@dataclass
class Config:
    """Configuracion efectiva ya resuelta (CLI manda sobre el archivo)."""

    ruta: Path | None = None
    datos: dict[str, Any] = field(default_factory=dict)
    sujetos: list[tuple[str, Path]] = field(default_factory=list)
    declarado: list[str] = field(default_factory=list)
    excluido: dict[str, str] = field(default_factory=dict)
    umbral_cobertura: float = UMBRAL_COBERTURA_POR_DEFECTO
    minimo: float = 0.0
    pesos: dict[str, float] = field(default_factory=dict)
    supresiones: Path | None = None


class ErrorDeOperacion(Exception):
    """Fallo previsto: se reporta con mensaje claro y salida 3, sin traza."""


def _leer_yaml(ruta: Path) -> dict[str, Any]:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise ErrorDeOperacion(f"no se pudo leer {ruta}: {exc}") from exc
    try:
        datos = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        raise ErrorDeOperacion(f"{ruta} no es YAML valido: {exc}") from exc
    if datos is None:
        return {}
    if not isinstance(datos, dict):
        raise ErrorDeOperacion(f"{ruta} debe contener un mapa en la raiz")
    return datos


def _nombre_de_ruta(ruta: Path) -> str:
    return ruta.name or str(ruta)


def _sujetos_de_config(datos: Mapping[str, Any], base: Path) -> list[tuple[str, Path]]:
    sujetos: list[tuple[str, Path]] = []
    for entrada in datos.get("sujetos") or []:
        if isinstance(entrada, str):
            ruta = (base / entrada).resolve()
            sujetos.append((_nombre_de_ruta(ruta), ruta))
        elif isinstance(entrada, Mapping):
            cruda = entrada.get("ruta") or entrada.get("path")
            if not cruda:
                raise ErrorDeOperacion(f"sujeto sin 'ruta' en la configuracion: {entrada!r}")
            ruta = (base / str(cruda)).resolve()
            sujetos.append((str(entrada.get("nombre") or _nombre_de_ruta(ruta)), ruta))
        else:
            raise ErrorDeOperacion(f"entrada de sujeto no reconocida: {entrada!r}")
    return sujetos


def cargar_config(ruta_config: Path | None, rutas_cli: Sequence[str]) -> Config:
    """Combina el archivo de configuracion con lo indicado en la linea de comandos."""
    cfg = Config()
    base = Path.cwd()
    if ruta_config is not None:
        if not ruta_config.is_file():
            raise ErrorDeOperacion(f"no existe el archivo de configuracion: {ruta_config}")
        cfg.ruta = ruta_config.resolve()
        cfg.datos = _leer_yaml(cfg.ruta)
        base = cfg.ruta.parent

    datos = cfg.datos
    cfg.sujetos = _sujetos_de_config(datos, base)
    for cruda in rutas_cli:
        ruta = Path(cruda).resolve()
        cfg.sujetos.append((_nombre_de_ruta(ruta), ruta))

    alcance = datos.get("alcance") or {}
    if not isinstance(alcance, Mapping):
        raise ErrorDeOperacion("'alcance' debe ser un mapa")
    declarado = alcance.get("declarado") or []
    if not isinstance(declarado, list):
        raise ErrorDeOperacion("'alcance.declarado' debe ser una lista de nombres")
    cfg.declarado = [str(x) for x in declarado]

    excluido = alcance.get("excluido") or {}
    if isinstance(excluido, Mapping):
        cfg.excluido = {str(k): str(v) for k, v in excluido.items()}
    elif isinstance(excluido, list):
        # Un excluido sin motivo no es un excluido declarado: se exige el motivo.
        raise ErrorDeOperacion(
            "'alcance.excluido' debe ser un mapa sujeto -> motivo declarado"
        )

    if "umbral_cobertura" in datos:
        cfg.umbral_cobertura = float(datos["umbral_cobertura"])
    if "minimo" in datos:
        cfg.minimo = float(datos["minimo"])

    pesos = datos.get("pesos") or {}
    if isinstance(pesos, Mapping):
        cfg.pesos = {str(k): float(v) for k, v in pesos.items()}

    if datos.get("supresiones"):
        cfg.supresiones = (base / str(datos["supresiones"])).resolve()

    # Si no se declaro alcance explicito, lo declarado es lo que se pidio evaluar.
    if not cfg.declarado:
        cfg.declarado = [nombre for nombre, _ in cfg.sujetos]
    return cfg


# ===========================================================================
# Supresiones
# ===========================================================================
def _fecha(valor: Any, contexto: str) -> date:
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor.strip())
        except ValueError as exc:
            raise ErrorDeOperacion(f"fecha invalida en {contexto}: {valor!r}") from exc
    raise ErrorDeOperacion(f"falta la fecha de vencimiento en {contexto}")


def cargar_supresiones(ruta: Path | None) -> list[Supresion]:
    """Lee `supresiones.yml`. Cada supresion exige justificacion, vencimiento y autor."""
    if ruta is None:
        return []
    if not ruta.is_file():
        raise ErrorDeOperacion(f"no existe el archivo de supresiones: {ruta}")
    datos = _leer_yaml(ruta)
    crudas = datos.get("supresiones", datos.get("suppressions", []))
    if not isinstance(crudas, list):
        raise ErrorDeOperacion(f"{ruta}: 'supresiones' debe ser una lista")

    supresiones: list[Supresion] = []
    for i, entrada in enumerate(crudas, start=1):
        if not isinstance(entrada, Mapping):
            raise ErrorDeOperacion(f"{ruta}: supresion #{i} no es un mapa")
        subcheck = str(entrada.get("subcheck") or entrada.get("subcheck_id") or "").strip()
        if not subcheck:
            raise ErrorDeOperacion(f"{ruta}: supresion #{i} sin 'subcheck'")
        justificacion = str(entrada.get("justificacion") or "").strip()
        autoriza = str(entrada.get("autorizada_por") or entrada.get("autoriza") or "").strip()
        if not justificacion or not autoriza:
            # Sin justificacion ni responsable, una supresion es un silencio: se rechaza.
            raise ErrorDeOperacion(
                f"{ruta}: la supresion de '{subcheck}' exige 'justificacion' y 'autorizada_por'"
            )
        supresiones.append(
            Supresion(
                subcheck_id=subcheck,
                sujeto=str(entrada.get("sujeto") or "").strip(),
                justificacion=justificacion,
                vence=_fecha(entrada.get("vence"), f"la supresion de '{subcheck}'"),
                autorizada_por=autoriza,
            )
        )
    return supresiones


def _aplica_a(sup: Supresion, sub: ResultadoSubcheck) -> bool:
    if sup.subcheck_id != sub.id:
        return False
    return sup.sujeto in ("", "*", sub.sujeto)


def aplicar_supresiones(
    checks: Sequence[ResultadoCheck], supresiones: Sequence[Supresion], hoy: date
) -> tuple[list[Supresion], list[Supresion], list[Supresion]]:
    """Convierte NO_CUMPLE en SUPRIMIDO cuando hay una supresion vigente.

    Devuelve (aplicadas, vencidas, vigentes_sin_efecto). Un NO_MEDIBLE nunca se suprime:
    aceptar por escrito que no se puede medir seria justo el agujero que se quiere cerrar.
    """
    aplicadas: list[Supresion] = []
    sin_efecto: list[Supresion] = []
    vencidas: list[Supresion] = [s for s in supresiones if not s.vigente(hoy)]

    for sup in supresiones:
        if not sup.vigente(hoy):
            continue
        toco = False
        for check in checks:
            for sub in check.subchecks:
                if sub.veredicto is Veredicto.NO_CUMPLE and _aplica_a(sup, sub):
                    sub.veredicto = Veredicto.SUPRIMIDO
                    sub.motivo = (
                        f"SUPRIMIDO hasta {sup.vence.isoformat()} por {sup.autorizada_por}: "
                        f"{sup.justificacion}"
                        + (f" | veredicto original: {sub.motivo}" if sub.motivo else "")
                    )
                    toco = True
        (aplicadas if toco else sin_efecto).append(sup)
    return aplicadas, vencidas, sin_efecto


# ===========================================================================
# Manifiesto
# ===========================================================================
def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(65536), b""):
            h.update(bloque)
    return f"sha256:{h.hexdigest()}"


def _revision_git(ruta: Path) -> str | None:
    try:
        proceso = subprocess.run(
            ["git", "-C", str(ruta), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proceso.returncode != 0:
        return None
    revision = proceso.stdout.strip()
    return f"git:{revision}" if revision else None


def _huella_directorio(ruta: Path) -> str:
    """Huella reproducible del contenido: sha256 sobre (ruta relativa, tamano).

    No sustituye a la revision de git; es lo que queda cuando el sujeto no es un repo.
    """
    h = hashlib.sha256()
    entradas: list[str] = []
    for raiz, dirs, archivos in os.walk(ruta):
        dirs[:] = sorted(d for d in dirs if d not in _DIRS_IGNORADOS)
        for archivo in sorted(archivos):
            completa = Path(raiz) / archivo
            try:
                tamano = completa.stat().st_size
            except OSError:
                tamano = -1
            entradas.append(f"{completa.relative_to(ruta).as_posix()}:{tamano}")
            if len(entradas) >= _MAX_ARCHIVOS_HUELLA:
                break
        if len(entradas) >= _MAX_ARCHIVOS_HUELLA:
            break
    for entrada in entradas:
        h.update(entrada.encode("utf-8") + b"\n")
    return f"sha256:{h.hexdigest()}"


def construir_manifiesto(
    *,
    config: Config,
    sondas: Sequence[SondaRegistrada],
    sujetos: Sequence[tuple[str, Path]],
    supresiones: Sequence[Supresion],
    hoy: date,
) -> dict[str, Any]:
    """Datos DECLARADOS del informe: con que se midio, sobre que y en que version.

    Sin esto un numero no es comparable con el de la semana pasada.
    """
    hashes: dict[str, str] = {}
    if config.ruta is not None and config.ruta.is_file():
        hashes[config.ruta.name] = _sha256_archivo(config.ruta)
    if config.supresiones is not None and config.supresiones.is_file():
        hashes[config.supresiones.name] = _sha256_archivo(config.supresiones)

    detalle_sujetos: list[dict[str, Any]] = []
    for nombre, ruta in sujetos:
        marca = _revision_git(ruta) or _huella_directorio(ruta)
        hashes[f"sujeto:{nombre}"] = marca
        detalle_sujetos.append({"nombre": nombre, "ruta": str(ruta), "marca": marca})

    return {
        "herramienta": "baremo",
        "version": __version__,
        "esquema_manifiesto": 1,
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fecha_referencia": hoy.isoformat(),
        "python": ".".join(str(x) for x in sys.version_info[:3]),
        "config": str(config.ruta) if config.ruta else None,
        "archivo_supresiones": str(config.supresiones) if config.supresiones else None,
        "supresiones_declaradas": len(supresiones),
        "umbral_cobertura": config.umbral_cobertura,
        "minimo": config.minimo,
        "sujetos": detalle_sujetos,
        "sondas": [
            {"id": s.id, "titulo": s.titulo, "eje": s.eje, "peso": s.peso, "version": s.version}
            for s in sondas
        ],
        "hashes": hashes,
    }


# ===========================================================================
# Evaluacion
# ===========================================================================
def _nombres_unicos(sujetos: Sequence[tuple[str, Path]]) -> list[tuple[str, Path]]:
    """Desambigua nombres repetidos con la ruta, y descarta rutas duplicadas."""
    vistos: dict[Path, str] = {}
    conteo: dict[str, int] = {}
    resultado: list[tuple[str, Path]] = []
    for nombre, ruta in sujetos:
        if ruta in vistos:
            continue
        final = nombre
        if nombre in conteo:
            final = f"{nombre}({ruta.parent.name})"
            if final in conteo:
                final = str(ruta)
        conteo[final] = 1
        conteo.setdefault(nombre, 1)
        vistos[ruta] = final
        resultado.append((final, ruta))
    return resultado


def evaluar_sujetos(
    sondas: Sequence[SondaRegistrada], sujetos: Sequence[tuple[str, Path]]
) -> list[ResultadoCheck]:
    """Corre TODAS las sondas sobre CADA sujeto y funde los resultados por check.

    Los sub-checks de todos los sujetos conviven en el mismo check: por eso la nota es
    proporcional y corregir 58 de 59 sujetos sube el numero.
    """
    fundidos: dict[str, ResultadoCheck] = {}
    for nombre, ruta in sujetos:
        for sonda in sondas:
            check = sonda.correr(nombre, ruta)
            acumulado = fundidos.get(check.id)
            if acumulado is None:
                fundidos[check.id] = ResultadoCheck(
                    id=check.id, titulo=check.titulo, eje=check.eje, peso=check.peso,
                    subchecks=list(check.subchecks),
                )
            else:
                acumulado.subchecks.extend(check.subchecks)
    return list(fundidos.values())


def _construir_alcance(
    config: Config, medidos: Sequence[str]
) -> Alcance:
    return Alcance(
        declarado=list(dict.fromkeys(config.declarado)),
        medido=list(medidos),
        excluido=dict(config.excluido),
    )


# ===========================================================================
# Comandos
# ===========================================================================
def _usar_color(args: argparse.Namespace) -> bool:
    if getattr(args, "sin_color", False):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def comando_evaluar(args: argparse.Namespace) -> int:
    config = cargar_config(
        Path(args.config) if args.config else None, args.rutas or []
    )
    if args.supresiones:
        config.supresiones = Path(args.supresiones).resolve()
    if args.umbral_cobertura is not None:
        config.umbral_cobertura = float(args.umbral_cobertura)
    if args.minimo is not None:
        config.minimo = float(args.minimo)
    hoy = _fecha(args.hoy, "--hoy") if args.hoy else date.today()

    if not config.sujetos:
        raise ErrorDeOperacion(
            "no hay sujetos que evaluar: indica rutas o declaralas en la configuracion. "
            "Baremo no adivina el alcance."
        )

    sujetos = _nombres_unicos(config.sujetos)
    faltantes = [f"{n} ({r})" for n, r in sujetos if not r.is_dir()]
    if faltantes:
        raise ErrorDeOperacion("estos sujetos no existen: " + ", ".join(faltantes))

    # Lo declarado como excluido no se mide: es una omision DECLARADA y no penaliza.
    a_medir = [(n, r) for n, r in sujetos if n not in config.excluido]

    sondas = descubrir_sondas()
    checks = evaluar_sujetos(sondas, a_medir)
    for check in checks:
        if check.id in config.pesos:
            check.peso = config.pesos[check.id]

    supresiones = cargar_supresiones(config.supresiones)
    aplicadas, vencidas, sin_efecto = aplicar_supresiones(checks, supresiones, hoy)

    alcance = _construir_alcance(config, [n for n, _ in a_medir])
    nota = puntuar(checks, alcance, config.umbral_cobertura)
    manifiesto = construir_manifiesto(
        config=config, sondas=sondas, sujetos=a_medir, supresiones=supresiones, hoy=hoy,
    )

    if args.formato == "json":
        salida = json.dumps(
            reporte_json(
                nota, checks, manifiesto, aplicadas, vencidas,
                supresiones_sin_efecto=sin_efecto,
            ),
            indent=2, ensure_ascii=False,
        ) + "\n"
    elif args.formato == "html":
        salida = reporte_html(
            nota, checks, manifiesto, aplicadas, vencidas,
            supresiones_sin_efecto=sin_efecto,
        )
    else:
        salida = reporte_texto(
            nota, checks, manifiesto, aplicadas, vencidas,
            color=_usar_color(args) and not args.salida,
            supresiones_sin_efecto=sin_efecto,
        )

    if args.salida:
        destino = Path(args.salida)
        if destino.parent and not destino.parent.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(salida, encoding="utf-8")
        print(f"informe escrito en {destino}", file=sys.stderr)
    else:
        sys.stdout.write(salida)

    return _codigo_de_salida(nota, config.minimo)


def _codigo_de_salida(nota: Nota, minimo: float) -> int:
    """2 si no es publicable; 1 si no llega al minimo; 0 si pasa.

    El 2 va ANTES que el 1 a proposito: si el informe no midio lo suficiente, no hay
    nota que comparar con el minimo. Un pipeline nunca debe leer eso como aprobado.
    """
    if not nota.publicable:
        return SALIDA_NO_PUBLICABLE
    cumplimiento = nota.cumplimiento
    if cumplimiento is None or cumplimiento < minimo:
        return SALIDA_BAJO_MINIMO
    return SALIDA_OK


def comando_sondas(args: argparse.Namespace) -> int:
    sondas = descubrir_sondas()
    if not sondas:
        print("No hay sondas registradas en baremo.probes.")
        print("Sin sondas, todo queda NO MEDIBLE: la cobertura seria 0 y nada se publica.")
        return SALIDA_OK
    ancho_id = max(max(len(s.id) for s in sondas), len("SONDA"))
    ancho_eje = max(max(len(s.eje) for s in sondas), len("EJE"))
    print(f"{'SONDA'.ljust(ancho_id)}  {'EJE'.ljust(ancho_eje)}  {'PESO':>5}  VERSION  TITULO")
    print("-" * (ancho_id + ancho_eje + 40))
    for s in sondas:
        print(
            f"{s.id.ljust(ancho_id)}  {s.eje.ljust(ancho_eje)}  {s.peso:>5.2f}  "
            f"{s.version:<7}  {s.titulo}"
        )
    print(f"\n{len(sondas)} sonda(s) registrada(s).")
    return SALIDA_OK


def _catalogo_de(sonda: SondaRegistrada) -> dict[str, str]:
    """Extrae el catalogo de sub-checks que la sonda declare, si lo declara."""
    catalogo: dict[str, str] = {}
    for nombre in _ATRIBUTOS_CATALOGO:
        valor = getattr(sonda.objeto, nombre, None)
        if isinstance(valor, Mapping):
            for clave, descripcion in valor.items():
                if isinstance(descripcion, str):
                    catalogo[str(clave)] = descripcion
                else:
                    catalogo[str(clave)] = str(
                        getattr(descripcion, "descripcion", "") or descripcion
                    )
        elif isinstance(valor, (list, tuple)):
            for item in valor:
                if isinstance(item, Mapping) and item.get("id"):
                    catalogo[str(item["id"])] = str(item.get("descripcion", ""))
                elif getattr(item, "id", None):
                    catalogo[str(item.id)] = str(getattr(item, "descripcion", ""))
                elif isinstance(item, str):
                    catalogo[item] = ""
    return catalogo


def comando_explicar(args: argparse.Namespace) -> int:
    buscado = str(args.subcheck_id).strip()
    sondas = descubrir_sondas()
    conocidos: dict[str, tuple[SondaRegistrada, str]] = {}
    for sonda in sondas:
        conocidos.setdefault(sonda.id, (sonda, sonda.descripcion))
        for clave, descripcion in _catalogo_de(sonda).items():
            conocidos[clave] = (sonda, descripcion)

    encontrado = conocidos.get(buscado)
    if encontrado is None:
        for clave, valor in conocidos.items():
            if clave.lower() == buscado.lower():
                encontrado = valor
                buscado = clave
                break

    if encontrado is None:
        print(f"No hay ningun sub-check registrado con el id '{buscado}'.", file=sys.stderr)
        parecidos = difflib.get_close_matches(buscado, list(conocidos), n=5, cutoff=0.4)
        if parecidos:
            print("Quiza buscabas: " + ", ".join(parecidos), file=sys.stderr)
        else:
            print("Usa 'baremo sondas' para ver el registro.", file=sys.stderr)
        return SALIDA_ERROR

    sonda, descripcion = encontrado
    doc = (inspect.getdoc(sonda.objeto) or "").strip()
    print(f"SUB-CHECK  {buscado}")
    print(f"SONDA      {sonda.id} - {sonda.titulo}")
    print(f"EJE        {sonda.eje}")
    print(f"PESO       {sonda.peso}")
    print(f"VERSION    {sonda.version}")
    print()
    print("QUE EVALUA")
    print(f"  {descripcion or '(la sonda no declara descripcion para este sub-check)'}")
    if doc and doc != descripcion:
        print()
        print("COMO LO EVALUA")
        for linea in doc.splitlines():
            print(f"  {linea}")
    print()
    print("VEREDICTOS POSIBLES")
    print("  CUMPLE      el hecho se verifico con evidencia.")
    print("  NO_CUMPLE   el hecho se verifico y no se cumple.")
    print("  NO_MEDIBLE  no se pudo determinar. No promedia como aprobado: baja la")
    print("              cobertura, y sin cobertura el cumplimiento no se publica.")
    print("  SUPRIMIDO   excepcion declarada, con justificacion, autor y vencimiento.")
    return SALIDA_OK


# ===========================================================================
# Parser
# ===========================================================================
class _Parser(argparse.ArgumentParser):
    """Argparse sale con 2 ante un error de uso; aqui 2 significa 'no publicable'."""

    def error(self, message: str) -> Any:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(SALIDA_USO)


def construir_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="baremo",
        description=(
            "Evaluador de madurez de ingenieria. Publica DOS numeros: cumplimiento y "
            "cobertura. Sin cobertura suficiente el cumplimiento se retiene."
        ),
        epilog=(
            "Codigos de salida: 0 publicable y sobre el minimo | 1 bajo el minimo | "
            "2 NO publicable por cobertura | 3 error | 64 uso incorrecto."
        ),
    )
    parser.add_argument("--version", action="version", version=f"baremo {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True, metavar="COMANDO")

    ev = sub.add_parser("evaluar", help="evalua uno o mas repositorios", parents=[])
    ev.add_argument("rutas", nargs="*", help="rutas de los sujetos a evaluar")
    ev.add_argument("--config", metavar="ARCHIVO", help="archivo baremo.yml")
    ev.add_argument("--supresiones", metavar="ARCHIVO", help="archivo supresiones.yml")
    ev.add_argument(
        "--formato", choices=("texto", "json", "html"), default="texto",
        help="formato del informe (por defecto: texto)",
    )
    ev.add_argument("--salida", metavar="ARCHIVO", help="escribe el informe en un archivo")
    ev.add_argument(
        "--umbral-cobertura", type=float, default=None, metavar="F",
        help=f"cobertura minima para publicar el cumplimiento (por defecto: {UMBRAL_COBERTURA_POR_DEFECTO})",
    )
    ev.add_argument(
        "--minimo", type=float, default=None, metavar="F",
        help="cumplimiento minimo exigido para salir con 0 (por defecto: 0.0)",
    )
    ev.add_argument("--sin-color", action="store_true", help="desactiva los colores ANSI")
    ev.add_argument(
        "--hoy", metavar="AAAA-MM-DD",
        help="fecha de referencia para el vencimiento de las supresiones",
    )
    ev.set_defaults(funcion=comando_evaluar)

    so = sub.add_parser("sondas", help="lista las sondas registradas con su eje y peso")
    so.set_defaults(funcion=comando_sondas)

    ex = sub.add_parser("explicar", help="explica que evalua un sub-check")
    ex.add_argument("subcheck_id", metavar="SUBCHECK_ID")
    ex.set_defaults(funcion=comando_explicar)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.funcion(args))
    except ErrorDeOperacion as exc:
        print(f"baremo: {exc}", file=sys.stderr)
        return SALIDA_ERROR
    except KeyboardInterrupt:
        print("baremo: interrumpido", file=sys.stderr)
        return SALIDA_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
