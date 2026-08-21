"""Sonda «ci»: integración continua.

Mide que exista automatización, que ejecute pruebas, que sus dependencias
(acciones e imágenes) estén ancladas y que no lleve credenciales en claro.

Regla de la casa aplicada aquí: cuando NO hay definiciones de pipeline, los
sub-checks que dependen de ellas no reprueban ni aprueban — devuelven
NO_MEDIBLE. Reprobar «pruebas en CI» a quien no tiene CI duplica el castigo del
sub-check que ya midió esa ausencia, y aprobarlo sería mentir.
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
    recortar,
    registrar,
    subcheck,
)
from baremo.probes.vcs import _es_marcador_de_posicion, _redactar, hallar_secretos

#: Dónde vive la definición de un pipeline, según la forja.
PATRONES_PIPELINE: tuple[str, ...] = (
    ".github/workflows/*.y*ml",
    ".gitlab-ci.yml",
    ".gitlab-ci.yaml",
    "Jenkinsfile",
    "Jenkinsfile.*",
    "azure-pipelines.yml",
    "azure-pipelines.yaml",
    "azure-pipelines-*.y*ml",
)

#: Invocaciones de corredores de pruebas, por ecosistema.
CORREDORES_DE_PRUEBAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pytest", re.compile(r"(?<![\w-])(?:python\s+-m\s+)?pytest(?![\w-])")),
    ("npm test", re.compile(r"(?<![\w-])(?:npm|yarn|pnpm)\s+(?:run\s+)?test(?![\w-])")),
    ("go test", re.compile(r"(?<![\w-])go\s+test(?![\w-])")),
    ("mvn test", re.compile(r"(?<![\w-])mvn\s+(?:[\w:.-]+\s+)*(?:test|verify)(?![\w-])")),
    ("dotnet test", re.compile(r"(?<![\w-])dotnet\s+test(?![\w-])")),
    ("gradle test", re.compile(r"(?<![\w-])(?:\./)?gradlew?\s+(?:[\w:.-]+\s+)*test(?![\w-])")),
    ("cargo test", re.compile(r"(?<![\w-])cargo\s+test(?![\w-])")),
    ("tox", re.compile(r"(?<![\w-])tox(?:\s|$)")),
    ("unittest", re.compile(r"(?<![\w-])python\s+-m\s+unittest(?![\w-])")),
)

#: Etiquetas que se mueven: hoy apuntan a un artefacto y mañana a otro.
ETIQUETAS_MOVILES: frozenset[str] = frozenset({
    "latest", "main", "master", "head", "edge", "stable", "dev", "develop",
    "nightly", "current", "rolling", "snapshot",
})

_RE_REFERENCIA = re.compile(
    r"^\s*(?:-\s*)?(?P<clave>uses|image|container)\s*:\s*(?P<valor>.+?)\s*$"
)
_RE_SHA = re.compile(r"^[0-9a-f]{40}$")
_RE_VERSION = re.compile(r"^v?\d+(?:\.\d+)*(?:[.\-+][A-Za-z0-9.]+)?$")

#: Nombres de clave que ACOTAN dónde mirar. La decisión sigue siendo por VALOR:
#: `apiKeyName: catalogo-de-claves` no es una credencial, y por eso el valor
#: tiene que además PARECER una credencial (ver `_parece_credencial`).
_RE_CLAVE_SENSIBLE = re.compile(
    r"(?i)^\s*(?:-\s*)?[\w.\-]*"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|private[_-]?key|client[_-]?secret)"
    r"[\w.\-]*\s*[:=]\s*(?P<valor>\S.*?)\s*$"
)


def _limpiar_valor(bruto: str) -> str:
    """Quita comentario al final y comillas alrededor."""
    valor = re.split(r"\s+#", bruto, maxsplit=1)[0].strip()
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        valor = valor[1:-1].strip()
    return valor


def _es_plantilla(valor: str) -> bool:
    """El valor lo resuelve el motor del pipeline: no se puede juzgar en estático."""
    return any(marca in valor for marca in ("${{", "${", "$(", "{{", "$["))


def _clasificar(clave: str, valor: str) -> str:
    """anclada · movil · plantilla · local — sobre una referencia del pipeline."""
    if not valor:
        return "plantilla"
    if _es_plantilla(valor):
        return "plantilla"
    if valor.startswith((".", "/")):
        return "local"          # acción del propio repositorio: viaja con el commit
    if valor.startswith("docker://"):
        clave, valor = "image", valor[len("docker://"):]

    if clave == "uses":
        if "@" not in valor:
            return "movil"      # sin referencia = rama por defecto de la acción
        ref = valor.rsplit("@", 1)[1]
        if _RE_SHA.match(ref) or ref.startswith("sha256:"):
            return "anclada"
        if ref.lower() in ETIQUETAS_MOVILES:
            return "movil"
        return "anclada" if _RE_VERSION.match(ref) else "movil"

    # imagen de contenedor
    if "@sha256:" in valor:
        return "anclada"
    ultimo = valor.rsplit("/", 1)[-1]
    if ":" not in ultimo:
        return "movil"          # sin etiqueta = :latest implícito
    etiqueta = ultimo.rsplit(":", 1)[1]
    if etiqueta.lower() in ETIQUETAS_MOVILES or etiqueta.lower().endswith("-latest"):
        return "movil"
    return "anclada"


def _parece_credencial(valor: str) -> bool:
    """Forma de credencial, no de nombre.

    Un identificador legible (`catalogo-de-claves`, `prod-api-key`) se descarta;
    una cadena larga con mezcla de mayúsculas, dígitos o base64 se conserva.
    """
    if " " in valor or len(valor) < 16:
        return False
    if re.fullmatch(r"[a-z0-9]+(?:[-_./][a-z0-9]+)+", valor):
        return False            # nombre en kebab/snake: es un identificador
    tiene_digito = any(c.isdigit() for c in valor)
    tiene_mayuscula = any(c.isupper() for c in valor)
    base64ish = bool(re.fullmatch(r"[A-Za-z0-9+/=_-]{24,}", valor))
    return base64ish or (tiene_digito and tiene_mayuscula)


@registrar("ci")
class SondaCi(Sonda):
    titulo = "Automatización de integración continua"
    eje = "Integración continua"
    peso = 1.0
    descripciones = {
        "CI_EXISTE_PIPELINE": "Hay al menos una definición de pipeline versionada",
        "CI_CORRE_PRUEBAS": "Algún pipeline invoca un corredor de pruebas",
        "CI_ACCIONES_ANCLADAS": "Las acciones e imágenes están ancladas a versión o SHA",
        "CI_SIN_SECRETOS_EN_CLARO": "Los pipelines usan referencias a secretos, no literales",
    }

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)
        pipelines = ctx.buscar(PATRONES_PIPELINE)
        return self._check([
            self._existe_pipeline(ctx, pipelines),
            self._corre_pruebas(ctx, pipelines),
            self._acciones_ancladas(ctx, pipelines),
            self._sin_secretos_en_claro(ctx, pipelines),
        ])

    # -- CI_EXISTE_PIPELINE -------------------------------------------------

    def _existe_pipeline(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "CI_EXISTE_PIPELINE", self.descripciones["CI_EXISTE_PIPELINE"]
        if not pipelines:
            return subcheck(
                id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                [evidencia_de_ausencia(ctx, list(PATRONES_PIPELINE))],
            )
        evidencias = [
            Evidencia(fuente=ctx.rel(p), extracto="definición de pipeline versionada",
                      detalle=f"{len(pipelines)} definiciones encontradas")
            for p in pipelines[:5]
        ]
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, evidencias)

    # -- CI_CORRE_PRUEBAS ---------------------------------------------------

    def _corre_pruebas(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "CI_CORRE_PRUEBAS", self.descripciones["CI_CORRE_PRUEBAS"]
        if not pipelines:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No hay definiciones de pipeline que inspeccionar. Haría falta "
                        "al menos una (workflow, .gitlab-ci.yml, Jenkinsfile o "
                        "azure-pipelines.yml) para saber si se ejecutan pruebas."),
            )
        legibles = 0
        for ruta in pipelines:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            legibles += 1
            for numero, linea in enumerate(texto.splitlines(), start=1):
                for nombre, patron in CORREDORES_DE_PRUEBAS:
                    if patron.search(linea):
                        return subcheck(
                            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
                            [evidencia_linea(ctx, ruta, numero, linea,
                                             detalle=f"corredor de pruebas «{nombre}»")],
                        )
        if legibles == 0:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("Se localizaron definiciones de pipeline pero ninguna pudo "
                        "leerse como texto. Haría falta acceso de lectura a esos archivos."),
            )
        return subcheck(
            id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
            [Evidencia(
                fuente=ctx.rel(pipelines[0]),
                extracto=f"{legibles} definiciones de pipeline leídas sin invocar pruebas",
                detalle="se buscó: " + ", ".join(n for n, _ in CORREDORES_DE_PRUEBAS),
            )],
        )

    # -- CI_ACCIONES_ANCLADAS ----------------------------------------------

    def _acciones_ancladas(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub, desc = "CI_ACCIONES_ANCLADAS", self.descripciones["CI_ACCIONES_ANCLADAS"]
        if not pipelines:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No hay definiciones de pipeline que inspeccionar; sin ellas no "
                        "hay acciones ni imágenes cuyo anclaje medir."),
            )

        moviles: list[tuple[Path, int, str, str]] = []
        plantillas: list[tuple[Path, int, str, str]] = []
        ancladas: list[tuple[Path, int, str, str]] = []
        locales = 0

        for ruta in pipelines:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            for numero, linea in enumerate(texto.splitlines(), start=1):
                casa = _RE_REFERENCIA.match(linea)
                if not casa:
                    continue
                clave = casa.group("clave")
                valor = _limpiar_valor(casa.group("valor"))
                if not valor:
                    continue
                estado = _clasificar(clave, valor)
                registro = (ruta, numero, linea, valor)
                if estado == "movil":
                    moviles.append(registro)
                elif estado == "plantilla":
                    plantillas.append(registro)
                elif estado == "local":
                    locales += 1
                else:
                    ancladas.append(registro)

        if moviles:
            evidencias = [
                evidencia_linea(ctx, r, n, l, detalle=f"«{v}» apunta a una etiqueta móvil")
                for r, n, l, v in moviles[:10]
            ]
            evidencias.append(Evidencia(
                fuente=ctx.rel(pipelines[0]),
                extracto=(f"{len(moviles)} referencias móviles, {len(ancladas)} ancladas, "
                          f"{len(plantillas)} resueltas por plantilla, {locales} locales"),
                detalle="recuento del barrido de anclaje",
            ))
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto, evidencias)

        if plantillas:
            # Todas las determinables están ancladas, pero quedan referencias que
            # resuelve el motor en ejecución. Ante la duda NO se aprueba.
            muestra = ", ".join(f"{ctx.rel(r)}:{n} «{v}»" for r, n, _, v in plantillas[:5])
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=(f"{len(plantillas)} referencias se resuelven en ejecución mediante "
                        f"expresiones del motor y no pueden juzgarse en estático ({muestra}). "
                        f"Para medirlas haría falta el valor efectivo: la bitácora de una "
                        f"ejecución o sustituir la expresión por la referencia literal."),
            )

        if not ancladas:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("Los pipelines no declaran acciones ni imágenes: no hay nada cuyo "
                        "anclaje medir. Haría falta que el pipeline declarara sus "
                        "dependencias con `uses:` o `image:`."),
            )

        evidencias = [
            evidencia_linea(ctx, r, n, l, detalle=f"«{v}» anclada")
            for r, n, l, v in ancladas[:5]
        ]
        evidencias.append(Evidencia(
            fuente=ctx.rel(pipelines[0]),
            extracto=f"{len(ancladas)} referencias ancladas, 0 móviles",
            detalle=f"{locales} referencias locales al propio repositorio, no evaluadas",
        ))
        return subcheck(id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto, evidencias)

    # -- CI_SIN_SECRETOS_EN_CLARO ------------------------------------------

    def _sin_secretos_en_claro(self, ctx: Contexto, pipelines: list[Path]) -> ResultadoSubcheck:
        id_sub = "CI_SIN_SECRETOS_EN_CLARO"
        desc = self.descripciones[id_sub]
        if not pipelines:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("No hay definiciones de pipeline que inspeccionar. Haría falta al "
                        "menos una para saber cómo se le entregan las credenciales."),
            )

        evidencias: list[Evidencia] = []
        referencias = 0
        legibles = 0
        for ruta in pipelines:
            texto = ctx.leer(ruta)
            if texto is None:
                continue
            legibles += 1
            referencias += len(re.findall(r"(?i)\$\{\{\s*secrets\.|\$\{?[A-Z0-9_]*SECRET", texto))

            # (a) valores con forma de credencial, mismo detector que la sonda vcs
            for numero, etiqueta, redactado in hallar_secretos(texto):
                evidencias.append(Evidencia(
                    fuente=ctx.rel(ruta),
                    extracto=f"{etiqueta}: {redactado}",
                    detalle=f"línea {numero} · valor redactado a propósito",
                ))

            # (b) clave sensible con literal que ADEMÁS parece credencial
            for numero, linea in enumerate(texto.splitlines(), start=1):
                casa = _RE_CLAVE_SENSIBLE.match(linea)
                if not casa:
                    continue
                valor = _limpiar_valor(casa.group("valor"))
                if not valor or _es_plantilla(valor):
                    continue        # es una referencia: exactamente lo que se pide
                if _es_marcador_de_posicion(linea, valor):
                    continue
                if not _parece_credencial(valor):
                    continue        # un nombre no es una credencial
                evidencias.append(Evidencia(
                    fuente=ctx.rel(ruta),
                    extracto=f"literal en clave sensible: {_redactar(valor)}",
                    detalle=f"línea {numero} · valor redactado a propósito",
                ))

        if evidencias:
            return subcheck(id_sub, desc, Veredicto.NO_CUMPLE, ctx.nombre_sujeto,
                            evidencias[:15])
        if legibles == 0:
            return subcheck(
                id_sub, desc, Veredicto.NO_MEDIBLE, ctx.nombre_sujeto,
                motivo=("Se localizaron definiciones de pipeline pero ninguna pudo leerse "
                        "como texto. Haría falta acceso de lectura a esos archivos."),
            )
        return subcheck(
            id_sub, desc, Veredicto.CUMPLE, ctx.nombre_sujeto,
            [Evidencia(
                fuente=ctx.rel(pipelines[0]),
                extracto=(f"{legibles} definiciones inspeccionadas · {referencias} "
                          f"referencias a un almacén de secretos · 0 literales"),
                detalle=recortar("se evaluó la FORMA del valor; una clave llamada "
                                 "apiKeyName con un nombre por valor no es un hallazgo"),
            )],
        )
