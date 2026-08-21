"""Sonda «documentacion»: lo mínimo para que alguien más pueda operar el código.

DOC_README no cuenta caracteres brutos sino ÚTILES: un README que sólo tiene
insignias y un título ocupa mucho y no documenta nada. Contar bytes premiaría
al que pega diez insignias; contar caracteres útiles mide lo que se pretendía
medir.
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

PATRONES_README: tuple[str, ...] = ("README", "README.*")
PATRONES_LICENCIA: tuple[str, ...] = (
    "LICENSE", "LICENSE.*", "LICENSE-*", "LICENCIA", "LICENCIA.*",
    "COPYING", "COPYING.*",
)
#: Carpetas donde suelen vivir las decisiones de arquitectura.
SEGMENTOS_DECISIONES: tuple[str, ...] = (
    "decisiones", "adr", "adrs", "decisions", "architecture", "arquitectura",
)

#: Comandos que documentan cómo instalar o cómo ejecutar.
RE_ARRANQUE = re.compile(
    r"(?i)(?<![\w-])("
    r"pip\s+install|pipx\s+install|poetry\s+install|uv\s+(?:sync|pip|run)"
    r"|npm\s+(?:ci|install|run|start)|yarn\s+(?:install|start|dev)|pnpm\s+(?:install|dev)"
    r"|docker\s+(?:build|run)|docker[\s-]compose\s+up"
    r"|make\s+[\w.-]+|go\s+(?:run|build|install)|cargo\s+(?:run|build)"
    r"|dotnet\s+(?:run|build|restore)|mvn\s+[\w:.-]+|\./gradlew\s+[\w:.-]+"
    r"|python\s+-m\s+[\w.]+|python3?\s+[\w./-]+\.py|bash\s+[\w./-]+\.sh"
    r"|kubectl\s+apply|helm\s+install|terraform\s+(?:init|apply)"
    r")(?![\w-])"
)

_RE_COMENTARIO_HTML = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_IMAGEN_ENLAZADA = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)")   # insignia con enlace
_RE_IMAGEN = re.compile(r"!\[[^\]]*\]\([^)]*\)")                          # insignia simple
_RE_ENLACE = re.compile(r"\[([^\]]*)\]\([^)]*\)")                         # deja el texto, quita la URL
_RE_ETIQUETA_HTML = re.compile(r"<[^>]+>")


def caracteres_utiles(texto: str) -> int:
    """Cuenta el texto que de verdad documenta.

    Se descartan comentarios HTML, insignias (imágenes, enlazadas o no), las
    URL de los enlaces —conservando su texto—, las etiquetas HTML y los
    marcadores de encabezado. El espacio en blanco se colapsa.
    """
    limpio = _RE_COMENTARIO_HTML.sub(" ", texto)
    limpio = _RE_IMAGEN_ENLAZADA.sub(" ", limpio)
    limpio = _RE_IMAGEN.sub(" ", limpio)
    limpio = _RE_ENLACE.sub(r"\1", limpio)
    limpio = _RE_ETIQUETA_HTML.sub(" ", limpio)
    limpio = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", limpio)
    return len(" ".join(limpio.split()))


def bloques_de_codigo(texto: str) -> list[tuple[int, str]]:
    """Devuelve (número de línea, contenido) de las líneas dentro de vallas ```."""
    dentro = False
    salida: list[tuple[int, str]] = []
    for numero, linea in enumerate(texto.splitlines(), start=1):
        if linea.lstrip().startswith("```") or linea.lstrip().startswith("~~~"):
            dentro = not dentro
            continue
        if dentro:
            salida.append((numero, linea))
    return salida


@registrar("documentacion")
class SondaDocumentacion(Sonda):
    titulo = "Documentación mínima operable"
    eje = "Documentación"
    peso = 1.0
    descripciones = {
        "DOC_README": "Existe un README con contenido útil suficiente",
        "DOC_ARRANQUE": "El README documenta cómo instalar o ejecutar",
        "DOC_DECISIONES": "Hay registro de decisiones de arquitectura",
        "DOC_LICENCIA": "Existe archivo de licencia",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        readme = self._localizar_readme(ctx)
        return self._check([
            self._readme(ctx, readme),
            self._arranque(ctx, readme),
            self._decisiones(ctx),
            self._licencia(ctx),
        ])

    # -- localización -------------------------------------------------------

    def _localizar_readme(self, ctx: Contexto) -> Path | None:
        candidatos = ctx.buscar(PATRONES_README)
        raiz = [c for c in candidatos if "/" not in ctx.rel(c)]
        if raiz:
            return raiz[0]
        docs = [c for c in candidatos if ctx.rel(c).startswith("docs/")]
        return docs[0] if docs else None

    # -- DOC_README ---------------------------------------------------------

    def _readme(self, ctx: Contexto, readme: Path | None) -> ResultadoSubcheck:
        id_sub, desc = "DOC_README", self.descripciones["DOC_README"]
        minimo = int(ctx.convencion("min_caracteres_readme", 400))  # type: ignore[arg-type]
        if readme is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, ["README (raíz)", "docs/README.*"])],
            )
        texto = ctx.leer(readme)
        if texto is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("El README existe pero no pudo leerse como texto (binario, "
                        "ilegible o por encima del tope de tamaño). Haría falta acceso "
                        "de lectura al archivo."),
            )
        utiles = caracteres_utiles(texto)
        evidencia = Evidencia(
            fuente=ctx.rel(readme),
            extracto=f"{utiles} caracteres útiles de {len(texto)} totales",
            detalle=(f"umbral declarado: {minimo} · no cuentan insignias, comentarios "
                     f"HTML ni las URL de los enlaces"),
        )
        veredicto = Veredicto.CUMPLE if utiles > minimo else Veredicto.NO_CUMPLE
        return subcheck(id_sub, desc, veredicto, ctx.nombre_sujeto, [evidencia])

    # -- DOC_ARRANQUE -------------------------------------------------------

    def _arranque(self, ctx: Contexto, readme: Path | None) -> ResultadoSubcheck:
        id_sub, desc = "DOC_ARRANQUE", self.descripciones["DOC_ARRANQUE"]
        if readme is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No hay README donde buscar las instrucciones de instalación o "
                        "ejecución. Haría falta publicar uno con un bloque de código que "
                        "muestre los comandos."),
            )
        texto = ctx.leer(readme)
        if texto is None:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("El README no pudo leerse como texto; haría falta acceso de "
                        "lectura al archivo para buscar los comandos de arranque."),
            )
        bloques = bloques_de_codigo(texto)
        for numero, linea in bloques:
            casa = RE_ARRANQUE.search(linea)
            if casa:
                return subcheck(
                    id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                    [evidencia_linea(ctx, readme, numero, linea,
                                     detalle=f"comando «{casa.group(1)}» dentro de un bloque de código")],
                )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [Evidencia(
                fuente=ctx.rel(readme),
                extracto=f"{len(bloques)} líneas dentro de bloques de código, ninguna con comandos de arranque",
                detalle="se exige el comando dentro de un bloque de código: copiable y sin ambigüedad",
            )],
        )

    # -- DOC_DECISIONES -----------------------------------------------------

    def _decisiones(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "DOC_DECISIONES", self.descripciones["DOC_DECISIONES"]
        registros: list[Path] = []
        for ruta in ctx.archivos:
            relativa = ctx.rel(ruta).lower()
            partes = relativa.split("/")
            if len(partes) < 2 or ruta.suffix.lower() not in (".md", ".rst", ".txt", ".adoc"):
                continue
            carpetas = partes[:-1]
            if any(segmento in carpetas for segmento in SEGMENTOS_DECISIONES):
                registros.append(ruta)
                continue
            # Convención de nombre: adr-0007-…, 0007-…
            nombre = partes[-1]
            if re.match(r"^(?:adr[-_])?\d{3,4}[-_]", nombre) and "docs" in carpetas:
                registros.append(ruta)

        if not registros:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(
                    ctx, [f"docs/{s}/" for s in SEGMENTOS_DECISIONES] + ["docs/NNNN-*.md"])],
            )
        evidencias = [
            Evidencia(fuente=ctx.rel(r),
                      extracto=(ctx.leer(r) or "").strip().splitlines()[0]
                      if (ctx.leer(r) or "").strip() else "(registro vacío)",
                      detalle=f"{len(registros)} registros de decisión encontrados")
            for r in registros[:5]
        ]
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, evidencias)

    # -- DOC_LICENCIA -------------------------------------------------------

    def _licencia(self, ctx: Contexto) -> ResultadoSubcheck:
        id_sub, desc = "DOC_LICENCIA", self.descripciones["DOC_LICENCIA"]
        candidatos = [c for c in ctx.buscar(PATRONES_LICENCIA)
                      if "/" not in ctx.rel(c) or ctx.rel(c).startswith("docs/")]
        if not candidatos:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, list(PATRONES_LICENCIA))],
            )
        ruta = candidatos[0]
        texto = ctx.leer(ruta) or ""
        primera = next((l.strip() for l in texto.splitlines() if l.strip()), "(archivo vacío)")
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
            [Evidencia(fuente=ctx.rel(ruta), extracto=primera,
                       detalle=f"{len(texto)} caracteres de licencia")],
        )
