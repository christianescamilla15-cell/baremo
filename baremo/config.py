"""Configuración declarada de Baremo (`baremo.yml`).

Todo lo que cambia el número tiene que estar ESCRITO en algún lado que se pueda leer,
versionar y diferenciar. Un modelo de madurez cuyo alcance vive en la cabeza de quien
lo corre no es auditable: dos corridas con el mismo comando dan notas distintas y nadie
puede señalar por qué. Por eso el alcance, el umbral de cobertura, las convenciones de
nombres y los pesos de las sondas son DATOS, no constantes escondidas en el código.

Esquema de `baremo.yml`
-----------------------

```yaml
version: 1                                 # versión del esquema (hoy sólo 1)

alcance:
  sujetos:                                 # lo que se DECLARA medir
    - "servicios/<app>"
    - "servicios/<otra-app>"
  excluidos:                               # exclusión explícita: sujeto -> motivo
    "servicios/<app-archivada>": "Congelada; se apaga el próximo trimestre."

umbral_cobertura: 0.80                     # bajo este valor el cumplimiento NO se publica

convenciones:                              # ⚠️ configurables: NO hay regex fijo en el código
  entornos: ["dev", "qa", "prod"]          #   cada organización nombra distinto sus entornos
  rama_principal: "main"                   #   ...y su rama principal

sondas:                                    # peso por sonda; la que se omita pesa 1.0
  seguridad: 2.0
  pruebas: 1.0
```

Notas de lectura:

* Las claves desconocidas NO son un error: se registran en `Configuracion.avisos`.
  Fallar por una clave nueva convertiría cada actualización en una migración; ignorarla
  en silencio escondería una errata. El punto medio es dejar rastro.
* Si el archivo no existe se usan valores por defecto sensatos, pero queda constancia
  en `Configuracion.por_defecto`. Un reporte generado sin configuración declarada no es
  comparable con uno generado con ella, y el manifiesto debe poder decirlo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from baremo.scoring import UMBRAL_COBERTURA_POR_DEFECTO

# Nombre convencional de los dos archivos declarados del proyecto.
RUTA_CONFIG_POR_DEFECTO = Path("baremo.yml")
NOMBRE_SUPRESIONES_POR_DEFECTO = "supresiones.yml"

# Versiones del esquema que este módulo sabe leer.
VERSIONES_SOPORTADAS: tuple[int, ...] = (1,)

# Convenciones por defecto. Son un punto de partida, no una verdad: se sobrescriben
# desde el archivo porque los nombres de entorno y de rama cambian por organización.
ENTORNOS_POR_DEFECTO: tuple[str, ...] = ("dev", "qa", "prod")
RAMA_PRINCIPAL_POR_DEFECTO = "main"

_CLAVES_RAIZ = {"version", "alcance", "umbral_cobertura", "convenciones", "sondas"}
_CLAVES_ALCANCE = {"sujetos", "excluidos"}
_CLAVES_CONVENCIONES = {"entornos", "rama_principal"}


class ConfigInvalida(ValueError):
    """El archivo existe pero no se puede leer sin adivinar.

    Se prefiere fallar a interpretar: una configuración mal entendida produce un número
    que parece bueno y no lo es, que es exactamente el defecto que este proyecto ataca.
    """


@dataclass
class Convenciones:
    """Cómo nombra las cosas ESTA organización.

    Existe para que el código no cargue un regex fijo del estilo `(dev|qa|prod)`: en cuanto
    alguien llama `staging` a su preproducción, ese regex deja de encontrarla y la sonda
    reporta NO_MEDIBLE... o peor, la da por ausente. Las convenciones se declaran.
    """

    entornos: list[str] = field(default_factory=lambda: list(ENTORNOS_POR_DEFECTO))
    rama_principal: str = RAMA_PRINCIPAL_POR_DEFECTO

    def entorno_de(self, nombre: str) -> str | None:
        """Devuelve el entorno DECLARADO que aparece en `nombre`, o None.

        La comparación es sobre la lista declarada, sin patrón codificado. Ante empate
        (un nombre que contiene dos entornos) gana la coincidencia más larga, que es la
        más específica: `prod` vs `preprod`.
        """
        objetivo = nombre.lower()
        candidatos = [e for e in self.entornos if e and e.lower() in objetivo]
        if not candidatos:
            return None
        return max(candidatos, key=len)

    def es_rama_principal(self, rama: str) -> bool:
        """Compara contra la rama principal DECLARADA, no contra una lista adivinada."""
        return rama.strip() == self.rama_principal


@dataclass
class Configuracion:
    """Configuración efectiva de una corrida.

    `por_defecto` es parte del dato, no un detalle de implementación: distingue
    "se declaró medir esto" de "nadie declaró nada y la herramienta supuso".
    """

    version: int = 1
    sujetos: list[str] = field(default_factory=list)
    excluidos: dict[str, str] = field(default_factory=dict)
    umbral_cobertura: float = UMBRAL_COBERTURA_POR_DEFECTO
    convenciones: Convenciones = field(default_factory=Convenciones)
    sondas: dict[str, float] = field(default_factory=dict)

    # Procedencia: de dónde salió esta configuración.
    ruta: Path | None = None
    ruta_supresiones: Path = field(
        default_factory=lambda: Path(NOMBRE_SUPRESIONES_POR_DEFECTO)
    )
    por_defecto: bool = False

    # Todo lo que se leyó raro y no ameritó fallar. Nunca se silencia.
    avisos: list[str] = field(default_factory=list)

    def peso_de_sonda(self, nombre: str) -> float:
        """Peso declarado de una sonda; 1.0 si no se declaró."""
        return float(self.sondas.get(nombre, 1.0))

    def esta_excluido(self, sujeto: str) -> bool:
        return sujeto in self.excluidos

    def motivo_exclusion(self, sujeto: str) -> str:
        """Motivo DECLARADO de la exclusión. Sin motivo no hay exclusión válida."""
        return self.excluidos.get(sujeto, "")


def cargar_config(ruta: str | Path | None = RUTA_CONFIG_POR_DEFECTO) -> Configuracion:
    """Lee `baremo.yml` y devuelve la configuración efectiva.

    Si el archivo no existe (o `ruta` es None) devuelve valores por defecto con
    `por_defecto=True` y un aviso: la ausencia de configuración es un hecho reportable,
    no un estado neutro.

    Lanza `ConfigInvalida` cuando el archivo existe pero no se puede leer sin suponer:
    YAML roto, raíz que no es un mapa, versión desconocida, umbral fuera de [0, 1],
    exclusión sin motivo o peso de sonda no numérico.
    """
    if ruta is None:
        cfg = Configuracion(por_defecto=True)
        cfg.avisos.append(
            "No se indicó ruta de configuración: se usaron los valores por defecto."
        )
        return cfg

    ruta_config = Path(ruta)
    ruta_supresiones = ruta_config.parent / NOMBRE_SUPRESIONES_POR_DEFECTO

    if not ruta_config.is_file():
        cfg = Configuracion(
            ruta=ruta_config, ruta_supresiones=ruta_supresiones, por_defecto=True
        )
        cfg.avisos.append(
            f"No existe {ruta_config}: se usaron los valores por defecto "
            f"(umbral {UMBRAL_COBERTURA_POR_DEFECTO:.0%}, sin sujetos declarados). "
            "Sin alcance declarado la cobertura no puede detectar omisiones."
        )
        return cfg

    try:
        crudo: Any = yaml.safe_load(ruta_config.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - depende del archivo del usuario
        raise ConfigInvalida(f"{ruta_config} no es YAML válido: {exc}") from exc

    if crudo is None:
        crudo = {}
    if not isinstance(crudo, dict):
        raise ConfigInvalida(
            f"{ruta_config}: la raíz debe ser un mapa, se encontró {type(crudo).__name__}."
        )

    avisos: list[str] = []
    _avisar_claves_desconocidas(crudo, _CLAVES_RAIZ, ruta_config, "raíz", avisos)

    version = _leer_version(crudo.get("version", 1), ruta_config)
    alcance = _leer_mapa(crudo.get("alcance"), ruta_config, "alcance")
    _avisar_claves_desconocidas(alcance, _CLAVES_ALCANCE, ruta_config, "alcance", avisos)

    sujetos = _leer_sujetos(alcance.get("sujetos"), ruta_config)
    excluidos = _leer_excluidos(alcance.get("excluidos"), ruta_config)
    umbral = _leer_umbral(crudo.get("umbral_cobertura"), ruta_config)
    convenciones = _leer_convenciones(crudo.get("convenciones"), ruta_config, avisos)
    sondas = _leer_sondas(crudo.get("sondas"), ruta_config)

    # Coherencias que NO impiden puntuar pero que el reporte debe mostrar.
    for sujeto in excluidos:
        if sujeto not in sujetos:
            avisos.append(
                f"El sujeto excluido {sujeto!r} no aparece en alcance.sujetos: "
                "se excluye algo que nunca se declaró medir."
            )
    duplicados = sorted({s for s in sujetos if sujetos.count(s) > 1})
    if duplicados:
        avisos.append(
            "Sujetos declarados más de una vez (se cuentan una sola vez): "
            + ", ".join(duplicados)
        )
    if not sujetos:
        avisos.append(
            "alcance.sujetos está vacío: sin universo declarado, la cobertura sólo puede "
            "medir lo no medible, no lo omitido."
        )

    return Configuracion(
        version=version,
        sujetos=list(dict.fromkeys(sujetos)),  # sin duplicados, conservando el orden
        excluidos=excluidos,
        umbral_cobertura=umbral,
        convenciones=convenciones,
        sondas=sondas,
        ruta=ruta_config,
        ruta_supresiones=ruta_supresiones,
        por_defecto=False,
        avisos=avisos,
    )


# --------------------------------------------------------------------------------------
# Lectores por campo. Cada uno falla con el nombre del campo: un error de configuración
# tiene que decir QUÉ línea arreglar, no "configuración inválida".
# --------------------------------------------------------------------------------------

def _leer_version(valor: Any, ruta: Path) -> int:
    if not isinstance(valor, int) or isinstance(valor, bool):
        raise ConfigInvalida(f"{ruta}: 'version' debe ser un entero, se leyó {valor!r}.")
    if valor not in VERSIONES_SOPORTADAS:
        raise ConfigInvalida(
            f"{ruta}: versión de esquema {valor} desconocida "
            f"(soportadas: {', '.join(str(v) for v in VERSIONES_SOPORTADAS)}). "
            "Leerla a medias produciría un alcance distinto del declarado."
        )
    return valor


def _leer_mapa(valor: Any, ruta: Path, campo: str) -> dict[str, Any]:
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise ConfigInvalida(
            f"{ruta}: '{campo}' debe ser un mapa, se leyó {type(valor).__name__}."
        )
    return valor


def _leer_sujetos(valor: Any, ruta: Path) -> list[str]:
    if valor is None:
        return []
    if not isinstance(valor, list):
        raise ConfigInvalida(
            f"{ruta}: 'alcance.sujetos' debe ser una lista, "
            f"se leyó {type(valor).__name__}."
        )
    sujetos: list[str] = []
    for elemento in valor:
        if not isinstance(elemento, str) or not elemento.strip():
            raise ConfigInvalida(
                f"{ruta}: cada sujeto de 'alcance.sujetos' debe ser una cadena no vacía; "
                f"se leyó {elemento!r}."
            )
        sujetos.append(elemento.strip())
    return sujetos


def _leer_excluidos(valor: Any, ruta: Path) -> dict[str, str]:
    """Una exclusión SIN motivo no es una exclusión: es una omisión con permiso."""
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise ConfigInvalida(
            f"{ruta}: 'alcance.excluidos' debe ser un mapa sujeto -> motivo, "
            f"se leyó {type(valor).__name__}."
        )
    excluidos: dict[str, str] = {}
    for sujeto, motivo in valor.items():
        if not isinstance(sujeto, str) or not sujeto.strip():
            raise ConfigInvalida(
                f"{ruta}: clave inválida en 'alcance.excluidos': {sujeto!r}."
            )
        if not isinstance(motivo, str) or not motivo.strip():
            raise ConfigInvalida(
                f"{ruta}: la exclusión de {sujeto!r} no trae motivo declarado. "
                "Excluir sin motivo es reducir el alcance en silencio."
            )
        excluidos[sujeto.strip()] = motivo.strip()
    return excluidos


def _leer_umbral(valor: Any, ruta: Path) -> float:
    if valor is None:
        return UMBRAL_COBERTURA_POR_DEFECTO
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ConfigInvalida(
            f"{ruta}: 'umbral_cobertura' debe ser un número entre 0 y 1, "
            f"se leyó {valor!r}."
        )
    umbral = float(valor)
    if not 0.0 <= umbral <= 1.0:
        raise ConfigInvalida(
            f"{ruta}: 'umbral_cobertura' fuera de rango ({umbral}); "
            "se expresa como fracción, por ejemplo 0.80."
        )
    return umbral


def _leer_convenciones(valor: Any, ruta: Path, avisos: list[str]) -> Convenciones:
    mapa = _leer_mapa(valor, ruta, "convenciones")
    _avisar_claves_desconocidas(mapa, _CLAVES_CONVENCIONES, ruta, "convenciones", avisos)

    entornos_crudos = mapa.get("entornos")
    if entornos_crudos is None:
        entornos = list(ENTORNOS_POR_DEFECTO)
        if mapa:
            avisos.append(
                "No se declararon 'convenciones.entornos': se asumieron "
                f"{', '.join(ENTORNOS_POR_DEFECTO)}. Si la organización nombra distinto "
                "sus entornos, las sondas que dependen del nombre medirán de menos."
            )
    elif not isinstance(entornos_crudos, list) or not all(
        isinstance(e, str) and e.strip() for e in entornos_crudos
    ):
        raise ConfigInvalida(
            f"{ruta}: 'convenciones.entornos' debe ser una lista de cadenas no vacías."
        )
    else:
        entornos = [e.strip() for e in entornos_crudos]

    rama = mapa.get("rama_principal", RAMA_PRINCIPAL_POR_DEFECTO)
    if not isinstance(rama, str) or not rama.strip():
        raise ConfigInvalida(
            f"{ruta}: 'convenciones.rama_principal' debe ser una cadena no vacía."
        )

    return Convenciones(entornos=entornos, rama_principal=rama.strip())


def _leer_sondas(valor: Any, ruta: Path) -> dict[str, float]:
    if valor is None:
        return {}
    if not isinstance(valor, dict):
        raise ConfigInvalida(
            f"{ruta}: 'sondas' debe ser un mapa sonda -> peso, "
            f"se leyó {type(valor).__name__}."
        )
    sondas: dict[str, float] = {}
    for nombre, peso in valor.items():
        if not isinstance(nombre, str) or not nombre.strip():
            raise ConfigInvalida(f"{ruta}: nombre de sonda inválido: {nombre!r}.")
        if isinstance(peso, bool) or not isinstance(peso, (int, float)):
            raise ConfigInvalida(
                f"{ruta}: el peso de la sonda {nombre!r} debe ser numérico, "
                f"se leyó {peso!r}."
            )
        if float(peso) < 0:
            raise ConfigInvalida(
                f"{ruta}: el peso de la sonda {nombre!r} no puede ser negativo."
            )
        sondas[nombre.strip()] = float(peso)
    return sondas


def _avisar_claves_desconocidas(
    mapa: dict[str, Any],
    conocidas: set[str],
    ruta: Path,
    seccion: str,
    avisos: list[str],
) -> None:
    """Una clave desconocida suele ser una errata. No rompe la corrida, pero se ve."""
    sobrantes = sorted(k for k in mapa if k not in conocidas)
    if sobrantes:
        avisos.append(
            f"{ruta}: claves no reconocidas en {seccion} (se ignoraron): "
            + ", ".join(sobrantes)
        )
