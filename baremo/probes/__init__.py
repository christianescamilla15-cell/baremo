"""Registro de sondas y utilidades compartidas por todas ellas.

Una *sonda* mide un control sobre un sujeto (un repositorio) y devuelve un
`ResultadoCheck` con sus sub-checks. Las reglas del proyecto son duras y se
aplican aquí, en el constructor `subcheck()`, no en la buena voluntad de cada
sonda:

  · Un veredicto CUMPLE o NO_CUMPLE SIN evidencia es un error de programación
    (se levanta ValueError). Una nota sin evidencia no es auditable.
  · Un veredicto NO_MEDIBLE SIN motivo es un error de programación: el motivo
    debe decir QUÉ haría falta para poder medirlo.
  · Nunca se aprueba por ausencia de evidencia. Si no se pudo mirar, el
    veredicto es NO_MEDIBLE y baja la COBERTURA, no sube el cumplimiento.

El barrido de archivos ignora siempre los directorios de dependencias y de
artefactos: aprobar un check por un archivo que vino dentro de una dependencia
es uno de los falsos positivos más caros de los scorecards tradicionales.
"""
from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import ClassVar

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto

__all__ = [
    "REGISTRO",
    "registrar",
    "Sonda",
    "Contexto",
    "DIRECTORIOS_IGNORADOS",
    "EXTENSIONES_TEXTO",
    "subcheck",
    "evidencia_linea",
    "evidencia_de_ausencia",
    "recortar",
    "lineas_que_casan",
    "sujeto_de",
]

# --------------------------------------------------------------------------
# Barrido de archivos
# --------------------------------------------------------------------------

#: Directorios que NUNCA se inspeccionan. Contienen código de terceros o
#: artefactos generados: medir ahí produce tanto falsos positivos (un secreto
#: de ejemplo dentro de una dependencia) como falsos negativos por ruido.
DIRECTORIOS_IGNORADOS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "vendor",
    "site-packages",
})

#: Extensiones que se consideran texto inspeccionable. La lista es explícita a
#: propósito: leer binarios "por si acaso" hace lento el barrido y no aporta.
EXTENSIONES_TEXTO: frozenset[str] = frozenset({
    ".bash", ".bat", ".bicep", ".c", ".cfg", ".conf", ".cpp", ".cs", ".csproj",
    ".css", ".env", ".go", ".gradle", ".groovy", ".h", ".hcl", ".html", ".ini",
    ".java", ".js", ".json", ".json5", ".jsx", ".kt", ".kts", ".md", ".mdx",
    ".php", ".pl", ".plist", ".properties", ".ps1", ".py", ".rb", ".rs",
    ".rst", ".scala", ".sh", ".sql", ".swift", ".tf", ".tfvars", ".toml",
    ".ts", ".tsx", ".txt", ".vue", ".xml", ".yaml", ".yml", ".zsh",
})

#: Archivos de texto que no tienen extensión (se comparan en minúsculas).
NOMBRES_TEXTO_SIN_EXTENSION: frozenset[str] = frozenset({
    ".env", ".gitignore", ".dockerignore", ".npmrc", ".netrc", ".renovaterc",
    "codeowners", "containerfile", "copying", "dockerfile", "gemfile",
    "jenkinsfile", "licence", "licencia", "license", "makefile", "pipfile",
    "procfile", "readme",
})

#: Tope de archivos por barrido. Si se alcanza, el barrido queda TRUNCADO y las
#: sondas que dependen de "no encontré nada" deben degradar a NO_MEDIBLE: no se
#: puede afirmar una ausencia sobre un universo que no se recorrió completo.
LIMITE_ARCHIVOS: int = 20_000

#: Tope por archivo (bytes). Por encima, no se lee.
LIMITE_BYTES_ARCHIVO: int = 2 * 1024 * 1024


def _es_texto(ruta: Path) -> bool:
    """¿Vale la pena intentar leer este archivo como texto?"""
    if ruta.suffix.lower() in EXTENSIONES_TEXTO:
        return True
    nombre = ruta.name.lower()
    if nombre in NOMBRES_TEXTO_SIN_EXTENSION:
        return True
    # Variantes por entorno (.env.local, .env.produccion): son justo donde
    # aparecen las credenciales, así que se leen aunque el sufijo sea libre.
    if nombre.startswith(".env"):
        return True
    # Dockerfile.build, Dockerfile.prod, api.Dockerfile…
    return nombre.startswith("dockerfile") or nombre.endswith(".dockerfile")


def _recorrer(raiz: Path, limite: int) -> Iterator[Path]:
    """Recorre `raiz` podando los directorios ignorados."""
    for base, dirs, nombres in os.walk(raiz, followlinks=False):
        dirs[:] = sorted(
            d for d in dirs
            if d not in DIRECTORIOS_IGNORADOS and not d.endswith(".egg-info")
        )
        for nombre in sorted(nombres):
            yield Path(base) / nombre
            limite -= 1
            if limite <= 0:
                return


def recortar(texto: str, largo: int = 160) -> str:
    """Deja el extracto en una sola línea y de tamaño razonable."""
    plano = " ".join(texto.split())
    return plano if len(plano) <= largo else plano[: largo - 1] + "…"


def lineas_que_casan(texto: str, patron: re.Pattern[str]) -> list[tuple[int, str]]:
    """Devuelve (número de línea 1-based, línea) de cada coincidencia."""
    salida: list[tuple[int, str]] = []
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if patron.search(linea):
            salida.append((numero, linea))
    return salida


# --------------------------------------------------------------------------
# Contexto de evaluación
# --------------------------------------------------------------------------

@dataclass
class Contexto:
    """Todo lo que una sonda necesita para medir un sujeto.

    `convenciones` permite a la organización declarar sus propios umbrales sin
    tocar código (y, sobre todo, DEJARLOS VISIBLES en el reporte).
    """
    ruta_repo: Path
    nombre_sujeto: str
    convenciones: dict[str, object] = field(default_factory=dict)
    hoy: date = field(default_factory=date.today)

    _archivos: list[Path] | None = field(default=None, init=False, repr=False, compare=False)
    _truncado: bool = field(default=False, init=False, repr=False, compare=False)

    # -- estado del barrido -------------------------------------------------

    @property
    def repo_legible(self) -> bool:
        return self.ruta_repo.is_dir()

    @property
    def archivos(self) -> list[Path]:
        """Archivos del sujeto (memoizado, con los directorios ignorados podados)."""
        if self._archivos is None:
            encontrados = list(_recorrer(self.ruta_repo, LIMITE_ARCHIVOS)) if self.repo_legible else []
            self._truncado = len(encontrados) >= LIMITE_ARCHIVOS
            self._archivos = encontrados
        return self._archivos

    @property
    def barrido_truncado(self) -> bool:
        """True si se alcanzó el tope: entonces NO se puede afirmar una ausencia."""
        _ = self.archivos
        return self._truncado

    @property
    def archivos_texto(self) -> list[Path]:
        return [a for a in self.archivos if _es_texto(a)]

    # -- utilidades ---------------------------------------------------------

    def rel(self, ruta: Path) -> str:
        """Ruta relativa al sujeto, en formato posix. La raíz se reporta como '.'."""
        try:
            return ruta.resolve().relative_to(self.ruta_repo.resolve()).as_posix()
        except (ValueError, OSError):
            return ruta.as_posix()

    def buscar(self, patrones: Sequence[str]) -> list[Path]:
        """Archivos que casan con alguno de los patrones.

        Un patrón CON '/' se compara contra la ruta relativa; SIN '/', contra el
        nombre del archivo. La comparación no distingue mayúsculas.
        """
        salida: list[Path] = []
        for archivo in self.archivos:
            relativa = self.rel(archivo).lower()
            nombre = archivo.name.lower()
            for patron in patrones:
                pat = patron.lower()
                objetivo = relativa if "/" in pat else nombre
                if fnmatch.fnmatchcase(objetivo, pat):
                    salida.append(archivo)
                    break
        return salida

    def leer(self, ruta: Path) -> str | None:
        """Lee un archivo de texto. None si es demasiado grande, binario o ilegible."""
        try:
            if ruta.stat().st_size > LIMITE_BYTES_ARCHIVO:
                return None
            crudo = ruta.read_bytes()
        except OSError:
            return None
        if b"\x00" in crudo[:8192]:
            return None
        return crudo.decode("utf-8", errors="replace")

    def convencion(self, clave: str, por_defecto: object) -> object:
        return self.convenciones.get(clave, por_defecto)


# --------------------------------------------------------------------------
# Constructores de resultados (aquí viven las reglas duras)
# --------------------------------------------------------------------------

def subcheck(
    id_sub: str,
    descripcion: str,
    veredicto: Veredicto,
    sujeto: str,
    evidencias: Sequence[Evidencia] = (),
    motivo: str = "",
) -> ResultadoSubcheck:
    """Construye un sub-check exigiendo el contrato del proyecto."""
    evs = list(evidencias)
    if veredicto in (Veredicto.CUMPLE, Veredicto.NO_CUMPLE) and not evs:
        raise ValueError(
            f"{id_sub}: un veredicto {veredicto.value} sin evidencia no es auditable"
        )
    if veredicto is Veredicto.NO_MEDIBLE and not motivo:
        raise ValueError(
            f"{id_sub}: NO_MEDIBLE exige un motivo que diga qué haría falta para medirlo"
        )
    return ResultadoSubcheck(
        id=id_sub,
        descripcion=descripcion,
        veredicto=veredicto,
        evidencias=evs,
        motivo=motivo,
        sujeto=sujeto,
    )


def sujeto_de(ctx: Contexto, tipo: str, nombre: str) -> str:
    """Sujeto de un sub-check por ELEMENTO: `<sujeto>/<tipo>:<nombre>`.

    Las sondas que emiten un sub-check por elemento (una operación, una regla, un
    nivel C4) nombran así al elemento. Lleva el nombre del sujeto delante porque en
    una corrida con varios repositorios los sub-checks de todos conviven en el mismo
    check, y una supresión declarada para `api/operacion:GET /x` de un repositorio
    no debe tapar la del otro.
    """
    return f"{ctx.nombre_sujeto}/{tipo}:{nombre}"


def evidencia_linea(ctx: Contexto, ruta: Path, numero: int, linea: str,
                    detalle: str = "") -> Evidencia:
    """Evidencia puntual: archivo, número de línea y el fragmento visto."""
    ubicacion = f"línea {numero}"
    return Evidencia(
        fuente=ctx.rel(ruta),
        extracto=recortar(linea.strip()),
        detalle=f"{ubicacion} · {detalle}" if detalle else ubicacion,
    )


def evidencia_de_ausencia(ctx: Contexto, buscado: Sequence[str],
                          detalle: str = "") -> Evidencia:
    """Evidencia de que se buscó y no había nada.

    Es evidencia de PRIMERA CLASE: deja escrito el universo inspeccionado, de
    modo que "no encontré" sea verificable y no una opinión.
    """
    return Evidencia(
        fuente=ctx.rel(ctx.ruta_repo) or ".",
        extracto="buscado sin resultado: " + ", ".join(buscado),
        detalle=detalle or f"{len(ctx.archivos)} archivos inspeccionados",
    )


# --------------------------------------------------------------------------
# Registro de sondas
# --------------------------------------------------------------------------

class Sonda:
    """Base de toda sonda. `evaluar` mide el sujeto y devuelve un ResultadoCheck."""

    id: ClassVar[str] = ""
    titulo: ClassVar[str] = ""
    eje: ClassVar[str] = ""
    peso: ClassVar[float] = 1.0
    #: Versión de la sonda. Es un dato DECLARADO: sin él, dos corridas con
    #: reglas distintas producen números que nadie puede comparar.
    version: ClassVar[str] = "1.0.0"
    #: id de sub-check -> descripción. Es también el catálogo que el reporte
    #: puede mostrar sin ejecutar nada.
    descripciones: ClassVar[dict[str, str]] = {}

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:  # pragma: no cover - contrato
        raise NotImplementedError

    # -- ayudas para las subclases -----------------------------------------

    def _check(self, subchecks: list[ResultadoSubcheck]) -> ResultadoCheck:
        return ResultadoCheck(
            id=self.id, titulo=self.titulo, eje=self.eje,
            peso=self.peso, subchecks=subchecks,
        )

    def _sin_sujeto(self, ctx: Contexto) -> ResultadoCheck:
        """Sujeto ilegible: todo NO_MEDIBLE. Jamás se aprueba por no poder mirar."""
        motivo = (
            f"La ruta declarada del sujeto ({ctx.ruta_repo}) no es un directorio "
            f"legible. Para medir haría falta un árbol de trabajo accesible "
            f"(clon completo) del sujeto '{ctx.nombre_sujeto}'."
        )
        return self._check([
            subcheck(id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto, motivo=motivo)
            for id_sub, desc in self.descripciones.items()
        ])


#: id de sonda -> clase. Lo consume la capa de ejecución/reporte.
REGISTRO: dict[str, type[Sonda]] = {}


def registrar(id_sonda: str) -> Callable[[type[Sonda]], type[Sonda]]:
    """Decorador que da de alta una sonda en el REGISTRO con su id."""
    def _decorador(cls: type[Sonda]) -> type[Sonda]:
        if id_sonda in REGISTRO:
            raise ValueError(f"la sonda '{id_sonda}' ya estaba registrada")
        cls.id = id_sonda
        REGISTRO[id_sonda] = cls
        return cls
    return _decorador


# Importar al FINAL: los módulos hermanos hacen `from baremo.probes import Sonda`
# y para entonces el paquete ya tiene definidos el registro y las utilidades.
from baremo.probes import ci, documentacion, entrega, seguridad, vcs  # noqa: E402,F401
from baremo.probes import (  # noqa: E402,F401
    arquitectura,
    analisis,
)
