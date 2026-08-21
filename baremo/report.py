"""Reportes de Baremo: JSON estable, texto ASCII para consola y HTML autocontenido.

Los tres formatos obedecen la misma regla y por eso se escriben juntos: **lo que no
se pudo medir y lo que se dejó fuera del alcance se IMPRIME, no se omite**. Un informe
de madurez que sólo enseña el número aprobado es exactamente el defecto que este
proyecto corrige, así que aquí:

  · el cumplimiento y la cobertura salen SIEMPRE juntos, del mismo tamaño;
  · si la cobertura no alcanza el umbral, donde iría el cumplimiento dice RETENIDO
    y se explica por qué (nunca se publica un número que no es comparable);
  · cada NO_MEDIBLE aparece con su motivo — es la deuda de instrumentación, visible;
  · cada supresión (vigente o vencida) aparece con quién la autorizó y cuándo expira;
  · el alcance lista de forma explícita lo que se declaró y NO se midió ni se excluyó.

El informe de consola se emite en ASCII puro: se pliegan los acentos al final del
render para que sobreviva a cualquier terminal, a cualquier `pipe` y a cualquier
texto que una sonda haya recogido de una herramienta externa.
"""
from __future__ import annotations

import html
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from baremo.model import (
    Evidencia,
    ResultadoCheck,
    ResultadoSubcheck,
    Supresion,
    Veredicto,
)
from baremo.scoring import Nota, NotaCheck

# ---------------------------------------------------------------------------
# Identidad del esquema. El JSON es un contrato: se versiona y no se rompe.
# ---------------------------------------------------------------------------
ESQUEMA: str = "baremo/informe"
ESQUEMA_VERSION: int = 1

# Orden fijo de las columnas del informe de consola (contrato visual).
COLUMNAS: tuple[str, ...] = (
    "CHECK",
    "CUMPLE",
    "NO CUMPLE",
    "SUPRIMIDO",
    "NO MEDIBLE",
    "CUMPLIMIENTO",
    "COBERTURA",
)
_ANCHOS_FIJOS: tuple[int, ...] = (6, 9, 9, 10, 12, 9)
_ANCHO_CHECK_MIN: int = 22
_ANCHO_CHECK_MAX: int = 38
_SEPARADOR: str = "  "

# Paleta del informe HTML (tema oscuro, sin dependencias externas).
COLOR_FONDO: str = "#0b0e16"
COLOR_PANEL: str = "#131828"
COLOR_TEXTO: str = "#e6ebff"
COLOR_DIM: str = "#93a0c8"
COLOR_ACENTO: str = "#4f6bff"
COLOR_VERDE: str = "#37e5a5"
COLOR_AMBAR: str = "#ffb84f"
COLOR_ROJO: str = "#ff5c7c"
COLOR_GRIS: str = "#6b7699"

_COLOR_VEREDICTO: dict[Veredicto, str] = {
    Veredicto.CUMPLE: COLOR_VERDE,
    Veredicto.NO_CUMPLE: COLOR_ROJO,
    Veredicto.SUPRIMIDO: COLOR_AMBAR,
    Veredicto.NO_MEDIBLE: COLOR_GRIS,
}


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------
def _pct(valor: float | None, decimales: int = 0) -> str:
    """Porcentaje legible. `None` NO es 0%: es 'no disponible'."""
    if valor is None:
        return "n/d"
    return f"{valor * 100:.{decimales}f}%"


def _conteo(check: ResultadoCheck) -> dict[str, int]:
    """Conteo por veredicto de un check, con las cuatro llaves siempre presentes."""
    conteo = {v.value: 0 for v in Veredicto}
    for sub in check.subchecks:
        conteo[sub.veredicto.value] += 1
    conteo["MEDIBLES"] = len(check.medibles)
    conteo["TOTAL"] = len(check.subchecks)
    return conteo


def _indice_notas(nota: Nota) -> dict[str, NotaCheck]:
    return {n.id: n for n in nota.checks}


def _nota_para(check: ResultadoCheck, indice: Mapping[str, NotaCheck]) -> NotaCheck:
    """La NotaCheck del check; si faltara, se recalcula para no perder la fila."""
    encontrada = indice.get(check.id)
    if encontrada is not None:
        return encontrada
    c = _conteo(check)
    return NotaCheck(
        id=check.id,
        titulo=check.titulo,
        eje=check.eje,
        peso=check.peso,
        aprobados=c[Veredicto.CUMPLE.value],
        reprobados=c[Veredicto.NO_CUMPLE.value],
        suprimidos=c[Veredicto.SUPRIMIDO.value],
        no_medibles=c[Veredicto.NO_MEDIBLE.value],
    )


def _totales(checks: Sequence[ResultadoCheck]) -> dict[str, int]:
    """Totales de sub-checks a lo largo de todos los checks."""
    totales = {v.value: 0 for v in Veredicto}
    totales["MEDIBLES"] = 0
    totales["TOTAL"] = 0
    for ch in checks:
        for clave, valor in _conteo(ch).items():
            totales[clave] += valor
    return totales


def _subchecks_por_veredicto(
    checks: Sequence[ResultadoCheck], veredicto: Veredicto
) -> list[tuple[ResultadoCheck, ResultadoSubcheck]]:
    return [(ch, s) for ch in checks for s in ch.subchecks if s.veredicto is veredicto]


def _a_ascii(texto: str) -> str:
    """Pliega acentos y sustituye lo que no sea ASCII.

    El informe de consola debe ser ASCII puro, y los motivos pueden venir de la
    salida de una herramienta externa: aquí se garantiza, no se confía.
    """
    plegado = unicodedata.normalize("NFKD", texto)
    plegado = "".join(c for c in plegado if not unicodedata.combining(c))
    return plegado.encode("ascii", "replace").decode("ascii")


def _iso(valor: Any) -> Any:
    """Fechas a ISO-8601; cualquier otra cosa se deja tal cual."""
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------
def _evidencia_json(ev: Evidencia) -> dict[str, str]:
    return {"fuente": ev.fuente, "extracto": ev.extracto, "detalle": ev.detalle}


def _subcheck_json(sub: ResultadoSubcheck) -> dict[str, Any]:
    return {
        "id": sub.id,
        "descripcion": sub.descripcion,
        "sujeto": sub.sujeto,
        "veredicto": sub.veredicto.value,
        "cuenta_para_cobertura": sub.cuenta_para_cobertura,
        "motivo": sub.motivo,
        "evidencias": [_evidencia_json(e) for e in sub.evidencias],
    }


def _supresion_json(sup: Supresion, hoy: date | None = None) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "subcheck_id": sup.subcheck_id,
        "sujeto": sup.sujeto,
        "justificacion": sup.justificacion,
        "vence": _iso(sup.vence),
        "autorizada_por": sup.autorizada_por,
    }
    if hoy is not None:
        datos["vigente"] = sup.vigente(hoy)
    return datos


def reporte_json(
    nota: Nota,
    checks: Sequence[ResultadoCheck],
    manifiesto: Mapping[str, Any],
    supresiones_aplicadas: Sequence[Supresion] = (),
    supresiones_vencidas: Sequence[Supresion] = (),
    *,
    supresiones_sin_efecto: Sequence[Supresion] = (),
) -> dict[str, Any]:
    """Informe completo como estructura JSON-serializable.

    Estable y versionada (`esquema` + `esquema_version`): otros sistemas la consumen.
    Incluye SIEMPRE el manifiesto, el alcance con lo omitido sin declarar, la cobertura,
    y el detalle de cada check con sus sub-checks, motivos y evidencias. El cumplimiento
    va como `null` acompañado de `motivo_retencion` cuando no es publicable — nunca se
    sustituye por un 0 ni se calla.

    `supresiones_sin_efecto` (opcional) son supresiones vigentes que no encontraron
    sub-check al cual aplicarse: se reportan para que una excepción olvidada no
    envejezca en silencio.
    """
    indice = _indice_notas(nota)
    alcance = nota.alcance
    totales = _totales(checks)

    detalle: list[dict[str, Any]] = []
    for ch in checks:
        n = _nota_para(ch, indice)
        c = _conteo(ch)
        detalle.append(
            {
                "id": ch.id,
                "titulo": ch.titulo,
                "eje": ch.eje,
                "peso": ch.peso,
                "cumplimiento": n.cumplimiento,
                "cobertura": n.cobertura,
                "conteo": {
                    "cumple": c[Veredicto.CUMPLE.value],
                    "no_cumple": c[Veredicto.NO_CUMPLE.value],
                    "suprimido": c[Veredicto.SUPRIMIDO.value],
                    "no_medible": c[Veredicto.NO_MEDIBLE.value],
                    "medibles": c["MEDIBLES"],
                    "total": c["TOTAL"],
                },
                "subchecks": [_subcheck_json(s) for s in ch.subchecks],
            }
        )

    return {
        "esquema": ESQUEMA,
        "esquema_version": ESQUEMA_VERSION,
        "manifiesto": dict(manifiesto),
        "alcance": {
            "declarado": list(alcance.declarado),
            "medido": list(alcance.medido),
            "excluido": dict(alcance.excluido),
            "omitido_sin_declarar": list(alcance.omitido_sin_declarar),
        },
        "resumen": {
            # Dos números, siempre juntos. Uno sin el otro no significa nada.
            "cumplimiento": nota.cumplimiento if nota.publicable else None,
            "cumplimiento_calculado": nota.cumplimiento,
            "cobertura": nota.cobertura,
            "umbral_cobertura": nota.umbral_cobertura,
            "publicable": nota.publicable,
            "motivo_retencion": nota.motivo_retencion,
            "totales": {
                "cumple": totales[Veredicto.CUMPLE.value],
                "no_cumple": totales[Veredicto.NO_CUMPLE.value],
                "suprimido": totales[Veredicto.SUPRIMIDO.value],
                "no_medible": totales[Veredicto.NO_MEDIBLE.value],
                "medibles": totales["MEDIBLES"],
                "subchecks": totales["TOTAL"],
                "checks": len(checks),
            },
        },
        "checks": detalle,
        "supresiones": {
            "aplicadas": [_supresion_json(s) for s in supresiones_aplicadas],
            "vencidas": [_supresion_json(s) for s in supresiones_vencidas],
            "sin_efecto": [_supresion_json(s) for s in supresiones_sin_efecto],
        },
    }


# ---------------------------------------------------------------------------
# Texto (consola)
# ---------------------------------------------------------------------------
class _Tinta:
    """Colores ANSI opcionales. Con `activa=False` devuelve el texto intacto."""

    RESET = "\033[0m"
    NEGRITA = "\033[1m"
    VERDE = "\033[92m"
    ROJO = "\033[91m"
    AMBAR = "\033[93m"
    GRIS = "\033[90m"
    AZUL = "\033[94m"

    def __init__(self, activa: bool = True) -> None:
        self.activa = activa

    def __call__(self, texto: str, codigo: str) -> str:
        if not self.activa or not codigo:
            return texto
        return f"{codigo}{texto}{self.RESET}"

    def por_ratio(self, texto: str, valor: float | None, umbral: float = 0.80) -> str:
        """Verde si alcanza el umbral, ámbar si se acerca, rojo si no; gris si no hay dato."""
        if valor is None:
            return self(texto, self.GRIS)
        if valor >= umbral:
            return self(texto, self.VERDE)
        if valor >= umbral * 0.625:  # 50% cuando el umbral es 80%
            return self(texto, self.AMBAR)
        return self(texto, self.ROJO)


def _ancho_check(checks: Sequence[ResultadoCheck]) -> int:
    mayor = max((len(f"{c.id} {c.titulo}") for c in checks), default=0)
    return max(_ANCHO_CHECK_MIN, min(_ANCHO_CHECK_MAX, mayor))


def _recortar(texto: str, ancho: int) -> str:
    if len(texto) <= ancho:
        return texto
    return texto[: max(0, ancho - 3)] + "..."


def _fila(celdas: Sequence[str], ancho_check: int, tinta: _Tinta, color: str = "") -> str:
    anchos = (ancho_check, *_ANCHOS_FIJOS)
    partes: list[str] = []
    for i, (celda, ancho) in enumerate(zip(celdas, anchos, strict=True)):
        crudo = _recortar(celda, ancho)
        # El padding se aplica ANTES del color: los codigos ANSI no ocupan columnas.
        partes.append(crudo.ljust(ancho) if i == 0 else crudo.rjust(ancho))
    linea = _SEPARADOR.join(partes)
    return tinta(linea, color) if color else linea


def _envolver(texto: str, ancho: int, sangria: str = "  ") -> list[str]:
    """Ajuste de línea simple, sin dependencias."""
    palabras = texto.split()
    lineas: list[str] = []
    actual = sangria
    for palabra in palabras:
        if len(actual) + len(palabra) + 1 > ancho and actual.strip():
            lineas.append(actual.rstrip())
            actual = sangria + palabra
        else:
            actual = f"{actual} {palabra}" if actual.strip() else sangria + palabra
    if actual.strip():
        lineas.append(actual.rstrip())
    return lineas


def reporte_texto(
    nota: Nota,
    checks: Sequence[ResultadoCheck],
    manifiesto: Mapping[str, Any],
    supresiones_aplicadas: Sequence[Supresion] = (),
    supresiones_vencidas: Sequence[Supresion] = (),
    *,
    color: bool = True,
    supresiones_sin_efecto: Sequence[Supresion] = (),
) -> str:
    """Informe de consola en ASCII puro, con colores ANSI opcionales.

    Termina con los DOS números grandes. Si el informe no es publicable, en el lugar
    del cumplimiento imprime RETENIDO y el motivo: un informe que no midió no puede
    parecer aprobado.
    """
    t = _Tinta(color)
    indice = _indice_notas(nota)
    alcance = nota.alcance
    ancho_check = _ancho_check(checks)
    ancho_total = ancho_check + sum(_ANCHOS_FIJOS) + len(_SEPARADOR) * len(_ANCHOS_FIJOS)
    regla = "=" * ancho_total
    regla_fina = "-" * ancho_total
    lineas: list[str] = []

    # --- encabezado -------------------------------------------------------
    version = str(manifiesto.get("version", ""))
    generado = str(manifiesto.get("generado_en", ""))
    lineas.append(regla)
    lineas.append(t(f" BAREMO {version} - informe de madurez de ingenieria", t.NEGRITA))
    if generado:
        lineas.append(t(f" Generado: {generado}", t.GRIS))
    lineas.append(regla)
    lineas.append("")

    # --- alcance ----------------------------------------------------------
    lineas.append(t("ALCANCE", t.NEGRITA))
    lineas.append(f"  Declarado : {len(alcance.declarado)} sujeto(s)")
    lineas.append(f"  Medido    : {len(alcance.medido)}")
    lineas.append(f"  Excluido  : {len(alcance.excluido)} (declarado y justificado)")
    for sujeto, motivo in alcance.excluido.items():
        lineas.append(f"      - {sujeto}: {motivo}")
    omitido = alcance.omitido_sin_declarar
    if omitido:
        lineas.append(
            t(f"  OMITIDO SIN DECLARAR ({len(omitido)}): {', '.join(omitido)}", t.AMBAR)
        )
        lineas.extend(
            _envolver(
                "Estos sujetos se declararon y no se midieron ni se excluyeron: "
                "bajan la COBERTURA. Mirar menos no puede mejorar la nota.",
                ancho_total,
                "      ",
            )
        )
    else:
        lineas.append("  Omitido sin declarar: 0")
    lineas.append("")

    # --- tabla de checks --------------------------------------------------
    lineas.append(t("CHECKS", t.NEGRITA))
    lineas.append(t(_fila(COLUMNAS, ancho_check, _Tinta(False)), t.NEGRITA))
    lineas.append(regla_fina)
    if not checks:
        lineas.append(t("  (ningun check produjo resultados)", t.GRIS))
    for ch in checks:
        n = _nota_para(ch, indice)
        c = _conteo(ch)
        etiqueta = f"{ch.id} {ch.titulo}".strip()
        celdas = (
            etiqueta,
            str(c[Veredicto.CUMPLE.value]),
            str(c[Veredicto.NO_CUMPLE.value]),
            str(c[Veredicto.SUPRIMIDO.value]),
            str(c[Veredicto.NO_MEDIBLE.value]),
            _pct(n.cumplimiento),
            _pct(n.cobertura),
        )
        cruda = _fila(celdas, ancho_check, _Tinta(False))
        lineas.append(t.por_ratio(cruda, n.cumplimiento, nota.umbral_cobertura))
    lineas.append(regla_fina)
    tot = _totales(checks)
    lineas.append(
        _fila(
            (
                "TOTAL",
                str(tot[Veredicto.CUMPLE.value]),
                str(tot[Veredicto.NO_CUMPLE.value]),
                str(tot[Veredicto.SUPRIMIDO.value]),
                str(tot[Veredicto.NO_MEDIBLE.value]),
                "",
                "",
            ),
            ancho_check,
            t,
            t.NEGRITA,
        )
    )
    lineas.append("")

    # --- deuda de instrumentacion ----------------------------------------
    no_medibles = _subchecks_por_veredicto(checks, Veredicto.NO_MEDIBLE)
    if no_medibles:
        lineas.append(
            t(
                f"NO MEDIBLE ({len(no_medibles)}) - no promedia como aprobado; baja la COBERTURA",
                t.NEGRITA,
            )
        )
        for ch, sub in no_medibles[:25]:
            sujeto = sub.sujeto or "(sin sujeto)"
            motivo = sub.motivo or "sin motivo declarado por la sonda"
            lineas.append(t(f"  [{ch.id}] {sub.id} @ {sujeto}", t.GRIS))
            lineas.extend(_envolver(motivo, ancho_total, "      "))
        if len(no_medibles) > 25:
            lineas.append(t(f"  ... y {len(no_medibles) - 25} mas", t.GRIS))
        lineas.append("")

    # --- supresiones ------------------------------------------------------
    if supresiones_aplicadas or supresiones_vencidas or supresiones_sin_efecto:
        lineas.append(t("SUPRESIONES", t.NEGRITA))
        if supresiones_aplicadas:
            lineas.append(f"  VIGENTES ({len(supresiones_aplicadas)})")
            for s in supresiones_aplicadas:
                lineas.append(
                    t(
                        f"    {s.subcheck_id}  sujeto={s.sujeto or '*'}  "
                        f"vence={_iso(s.vence)}  autoriza={s.autorizada_por}",
                        t.AMBAR,
                    )
                )
                lineas.extend(_envolver(f'"{s.justificacion}"', ancho_total, "        "))
        if supresiones_vencidas:
            lineas.append(
                t(f"  VENCIDAS ({len(supresiones_vencidas)}) - vuelven a contar", t.ROJO)
            )
            for s in supresiones_vencidas:
                lineas.append(
                    t(
                        f"    {s.subcheck_id}  sujeto={s.sujeto or '*'}  "
                        f"vencio={_iso(s.vence)}  autorizo={s.autorizada_por}",
                        t.ROJO,
                    )
                )
        if supresiones_sin_efecto:
            lineas.append(
                t(
                    f"  SIN EFECTO ({len(supresiones_sin_efecto)}) - vigentes, "
                    "no aplicaron a ningun sub-check",
                    t.GRIS,
                )
            )
            for s in supresiones_sin_efecto:
                lineas.append(
                    t(f"    {s.subcheck_id}  sujeto={s.sujeto or '*'}", t.GRIS)
                )
        lineas.append("")

    # --- manifiesto -------------------------------------------------------
    lineas.append(t("MANIFIESTO", t.NEGRITA))
    lineas.append(
        t(
            f"  herramienta={manifiesto.get('herramienta', 'baremo')} "
            f"version={version} python={manifiesto.get('python', 'n/d')}",
            t.GRIS,
        )
    )
    sondas = manifiesto.get("sondas") or []
    if sondas:
        lineas.append(t(f"  sondas={len(sondas)}", t.GRIS))
        for s in sondas:
            if isinstance(s, Mapping):
                lineas.append(
                    t(
                        f"    {s.get('id', '?')}  eje={s.get('eje', '?')}  "
                        f"peso={s.get('peso', '?')}  version={s.get('version', 'no declarada')}",
                        t.GRIS,
                    )
                )
    hashes = manifiesto.get("hashes") or {}
    if isinstance(hashes, Mapping) and hashes:
        lineas.append(t("  hashes:", t.GRIS))
        for clave, valor in hashes.items():
            corto = str(valor)
            if corto.startswith("sha256:") and len(corto) > 23:
                corto = corto[:23] + "..."
            lineas.append(t(f"    {clave} = {corto}", t.GRIS))
    lineas.append("")

    # --- los dos numeros --------------------------------------------------
    lineas.append(regla)
    izq = "CUMPLIMIENTO"
    der = "COBERTURA"
    ancho_col = max(28, len(izq) + 4)
    lineas.append(t(f"  {izq.ljust(ancho_col)}{der}", t.NEGRITA))
    if nota.publicable:
        valor_izq = _pct(nota.cumplimiento, 1)
        pintado_izq = t.por_ratio(valor_izq.ljust(ancho_col), nota.cumplimiento, 0.80)
    else:
        pintado_izq = t("RETENIDO".ljust(ancho_col), t.AMBAR)
    pintado_der = t.por_ratio(_pct(nota.cobertura, 1), nota.cobertura, nota.umbral_cobertura)
    lineas.append(t(f"  {pintado_izq}{pintado_der}", t.NEGRITA))
    if not nota.publicable:
        lineas.append("")
        lineas.append(t("  ! CUMPLIMIENTO RETENIDO", t.AMBAR))
        lineas.extend(_envolver(nota.motivo_retencion, ancho_total, "    "))
    lineas.append(regla)

    return _a_ascii("\n".join(lineas) + "\n")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_CSS = f"""
*,*::before,*::after{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:{COLOR_FONDO};color:{COLOR_TEXTO};
  font:15px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
.envoltura{{max-width:1060px;margin:0 auto;padding:28px 20px 72px}}
.cabecera{{display:flex;flex-wrap:wrap;gap:10px 24px;align-items:baseline;
  justify-content:space-between;border-bottom:1px solid #222b45;padding-bottom:14px;margin-bottom:24px}}
.marca{{font-weight:700;letter-spacing:.16em;font-size:14px}}
.marca em{{font-style:normal;color:{COLOR_ACENTO}}}
.dim{{color:{COLOR_DIM}}}
.tesis{{color:{COLOR_DIM};font-size:13px;margin:0 0 22px;max-width:70ch}}
.panel{{background:{COLOR_PANEL};border:1px solid #222b45;border-radius:14px;padding:18px 20px}}
.numeros{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:16px}}
.etiqueta{{font-size:12px;letter-spacing:.18em;color:{COLOR_DIM};text-transform:uppercase}}
.valor{{font-size:clamp(36px,7vw,60px);font-weight:700;line-height:1.05;margin:8px 0 0;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}}
.valor.retenido{{font-size:clamp(26px,4.6vw,38px);color:{COLOR_AMBAR}}}
.nota-pie{{font-size:12.5px;color:{COLOR_DIM};margin-top:8px}}
.barra{{height:8px;border-radius:99px;background:#1c2340;overflow:hidden;margin-top:14px}}
.barra span{{display:block;height:100%;border-radius:99px}}
.banner{{border:1px solid {COLOR_AMBAR};border-left-width:5px;background:rgba(255,184,79,.09);
  border-radius:12px;padding:14px 18px;margin:16px 0 0}}
.banner strong{{color:{COLOR_AMBAR};letter-spacing:.1em;font-size:12.5px}}
.banner p{{margin:6px 0 0;color:{COLOR_TEXTO}}}
h2{{font-size:12.5px;letter-spacing:.18em;text-transform:uppercase;color:{COLOR_DIM};
  margin:36px 0 12px;font-weight:600}}
.check{{background:{COLOR_PANEL};border:1px solid #222b45;border-radius:12px;margin-bottom:10px;
  overflow:hidden}}
.check>summary{{cursor:pointer;list-style:none;padding:14px 18px;display:flex;flex-wrap:wrap;
  gap:8px 14px;align-items:center}}
.check>summary::-webkit-details-marker{{display:none}}
.check>summary:hover{{background:#182041}}
.check[open]>summary{{border-bottom:1px solid #222b45}}
.flecha{{color:{COLOR_DIM};font-size:11px;width:12px;display:inline-block}}
.check[open] .flecha{{transform:rotate(90deg)}}
.titulo-check{{font-weight:600;flex:1 1 240px}}
.titulo-check code{{color:{COLOR_DIM};font-weight:500;margin-right:8px}}
.eje{{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:{COLOR_DIM}}}
.cifras{{display:flex;gap:10px;flex-wrap:wrap;font-variant-numeric:tabular-nums;font-size:13px}}
.cifra b{{font-weight:700}}
.cuerpo{{padding:6px 18px 16px}}
.sub{{border-top:1px solid #1b2340;padding:12px 0}}
.sub:first-child{{border-top:none}}
.sub-cab{{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:baseline}}
.sub-id{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px}}
.sub-desc{{flex:1 1 260px;color:{COLOR_TEXTO}}}
.sujeto{{font-size:12.5px;color:{COLOR_DIM}}}
.motivo{{margin:6px 0 0;color:{COLOR_DIM};font-size:13.5px}}
.pastilla{{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.1em;
  padding:3px 9px;border-radius:99px;border:1px solid currentColor;white-space:nowrap}}
pre{{background:{COLOR_FONDO};border:1px solid #222b45;border-radius:8px;padding:10px 12px;
  overflow-x:auto;margin:6px 0 0;white-space:pre-wrap;word-break:break-word;
  font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#c9d4ff}}
.fuente{{font-size:12px;color:{COLOR_ACENTO};margin-top:10px;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #1b2340;vertical-align:top}}
th{{font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:{COLOR_DIM};font-weight:600}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}
ul.lista{{margin:0;padding-left:20px}}
ul.lista li{{margin:4px 0}}
.vacio{{color:{COLOR_DIM};font-size:13.5px;margin:0}}
footer{{margin-top:44px;border-top:1px solid #222b45;padding-top:16px;color:{COLOR_DIM};font-size:12.5px}}
footer code{{color:{COLOR_TEXTO};font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  word-break:break-all}}
footer dl{{display:grid;grid-template-columns:minmax(120px,auto) 1fr;gap:4px 16px;margin:10px 0 0}}
footer dt{{color:{COLOR_DIM}}}
footer dd{{margin:0;color:{COLOR_TEXTO};word-break:break-all}}
@media (max-width:520px){{.cifras{{width:100%}}}}
"""


def _e(texto: Any) -> str:
    """Escapa para HTML. Todo lo que viene de una sonda es texto ajeno."""
    return html.escape(str(texto), quote=True)


def _color_ratio(valor: float | None, umbral: float) -> str:
    if valor is None:
        return COLOR_GRIS
    if valor >= umbral:
        return COLOR_VERDE
    if valor >= umbral * 0.625:
        return COLOR_AMBAR
    return COLOR_ROJO


def _panel_numero(
    etiqueta: str, valor: float | None, umbral: float, pie: str, retenido: bool = False
) -> str:
    if retenido:
        cuerpo = '<div class="valor retenido">RETENIDO</div>'
        ancho = 0.0
        color = COLOR_AMBAR
    else:
        color = _color_ratio(valor, umbral)
        cuerpo = f'<div class="valor" style="color:{color}">{_e(_pct(valor, 1))}</div>'
        ancho = 0.0 if valor is None else max(0.0, min(1.0, valor)) * 100
    return (
        '<div class="panel">'
        f'<div class="etiqueta">{_e(etiqueta)}</div>'
        f"{cuerpo}"
        f'<div class="barra"><span style="width:{ancho:.1f}%;background:{color}"></span></div>'
        f'<div class="nota-pie">{_e(pie)}</div>'
        "</div>"
    )


def _pastilla(veredicto: Veredicto) -> str:
    color = _COLOR_VEREDICTO[veredicto]
    texto = veredicto.value.replace("_", " ")
    return f'<span class="pastilla" style="color:{color}">{_e(texto)}</span>'


def _html_evidencias(evidencias: Sequence[Evidencia]) -> str:
    if not evidencias:
        return (
            '<p class="motivo">Sin evidencia adjunta: el veredicto no es auditable '
            "y debe tratarse como tal.</p>"
        )
    piezas: list[str] = []
    for ev in evidencias:
        piezas.append(f'<div class="fuente">{_e(ev.fuente)}</div>')
        if ev.extracto:
            piezas.append(f"<pre>{_e(ev.extracto)}</pre>")
        if ev.detalle:
            piezas.append(f'<p class="motivo">{_e(ev.detalle)}</p>')
    return "".join(piezas)


def _html_subcheck(sub: ResultadoSubcheck) -> str:
    sujeto = f'<span class="sujeto">{_e(sub.sujeto)}</span>' if sub.sujeto else ""
    motivo = f'<p class="motivo">{_e(sub.motivo)}</p>' if sub.motivo else ""
    return (
        '<div class="sub">'
        '<div class="sub-cab">'
        f"{_pastilla(sub.veredicto)}"
        f'<span class="sub-id">{_e(sub.id)}</span>'
        f'<span class="sub-desc">{_e(sub.descripcion)}</span>'
        f"{sujeto}"
        "</div>"
        f"{motivo}"
        f"{_html_evidencias(sub.evidencias)}"
        "</div>"
    )


def _html_check(check: ResultadoCheck, nota_check: NotaCheck, umbral: float) -> str:
    c = _conteo(check)
    abrir = " open" if c[Veredicto.NO_CUMPLE.value] or c[Veredicto.NO_MEDIBLE.value] else ""
    cifras = (
        f'<span class="cifra" style="color:{COLOR_VERDE}">'
        f'<b>{c[Veredicto.CUMPLE.value]}</b> cumple</span>'
        f'<span class="cifra" style="color:{COLOR_ROJO}">'
        f'<b>{c[Veredicto.NO_CUMPLE.value]}</b> no cumple</span>'
        f'<span class="cifra" style="color:{COLOR_AMBAR}">'
        f'<b>{c[Veredicto.SUPRIMIDO.value]}</b> suprimido</span>'
        f'<span class="cifra" style="color:{COLOR_GRIS}">'
        f'<b>{c[Veredicto.NO_MEDIBLE.value]}</b> no medible</span>'
    )
    color_cump = _color_ratio(nota_check.cumplimiento, 0.80)
    color_cob = _color_ratio(nota_check.cobertura, umbral)
    return (
        f'<details class="check"{abrir}>'
        "<summary>"
        '<span class="flecha">&#9654;</span>'
        f'<span class="titulo-check"><code>{_e(check.id)}</code>{_e(check.titulo)}</span>'
        f'<span class="eje">{_e(check.eje)} &middot; peso {_e(check.peso)}</span>'
        f'<span class="cifras">{cifras}</span>'
        f'<span class="cifra" style="color:{color_cump}">'
        f"<b>{_e(_pct(nota_check.cumplimiento))}</b> cumpl.</span>"
        f'<span class="cifra" style="color:{color_cob}">'
        f"<b>{_e(_pct(nota_check.cobertura))}</b> cob.</span>"
        "</summary>"
        f'<div class="cuerpo">'
        + ("".join(_html_subcheck(s) for s in check.subchecks) or
           '<p class="vacio">Este check no produjo sub-checks.</p>')
        + "</div></details>"
    )


def _html_alcance(nota: Nota) -> str:
    a = nota.alcance
    omitido = a.omitido_sin_declarar
    filas = [
        '<table><tbody>',
        f'<tr><th>Declarado</th><td class="num">{len(a.declarado)}</td>'
        f'<td>{_e(", ".join(a.declarado)) or "&mdash;"}</td></tr>',
        f'<tr><th>Medido</th><td class="num">{len(a.medido)}</td>'
        f'<td>{_e(", ".join(a.medido)) or "&mdash;"}</td></tr>',
        f'<tr><th>Excluido</th><td class="num">{len(a.excluido)}</td><td>'
        + (
            "".join(
                f"<div>{_e(s)} &mdash; <span class='dim'>{_e(m)}</span></div>"
                for s, m in a.excluido.items()
            )
            or "&mdash;"
        )
        + "</td></tr>",
        f'<tr><th style="color:{COLOR_AMBAR}">Omitido sin declarar</th>'
        f'<td class="num">{len(omitido)}</td><td>'
        + (
            f'<span style="color:{COLOR_AMBAR}">{_e(", ".join(omitido))}</span>'
            if omitido
            else "&mdash;"
        )
        + "</td></tr>",
        "</tbody></table>",
    ]
    aviso = (
        f'<p class="nota-pie" style="color:{COLOR_AMBAR}">Lo omitido sin declarar baja la '
        "cobertura: reducir el alcance no puede mejorar la nota.</p>"
        if omitido
        else ""
    )
    return f'<div class="panel">{"".join(filas)}{aviso}</div>'


def _tabla_supresiones(supresiones: Sequence[Supresion], columna_fecha: str) -> str:
    if not supresiones:
        return '<p class="vacio">Ninguna.</p>'
    filas = "".join(
        "<tr>"
        f"<td><code>{_e(s.subcheck_id)}</code></td>"
        f"<td>{_e(s.sujeto or '*')}</td>"
        f"<td>{_e(_iso(s.vence))}</td>"
        f"<td>{_e(s.autorizada_por)}</td>"
        f"<td>{_e(s.justificacion)}</td>"
        "</tr>"
        for s in supresiones
    )
    return (
        '<div class="panel"><table><thead><tr>'
        "<th>Sub-check</th><th>Sujeto</th>"
        f"<th>{_e(columna_fecha)}</th><th>Autoriza</th><th>Justificacion</th>"
        f"</tr></thead><tbody>{filas}</tbody></table></div>"
    )


def _html_manifiesto(manifiesto: Mapping[str, Any]) -> str:
    partes: list[str] = ["<dl>"]
    for etiqueta, clave in (
        ("Herramienta", "herramienta"),
        ("Version", "version"),
        ("Generado", "generado_en"),
        ("Python", "python"),
        ("Umbral cobertura", "umbral_cobertura"),
        ("Minimo exigido", "minimo"),
    ):
        if clave in manifiesto:
            partes.append(f"<dt>{_e(etiqueta)}</dt><dd>{_e(manifiesto[clave])}</dd>")
    sondas = manifiesto.get("sondas") or []
    if sondas:
        detalle = "".join(
            f"<div>{_e(s.get('id', '?'))} &middot; eje {_e(s.get('eje', '?'))} "
            f"&middot; peso {_e(s.get('peso', '?'))} &middot; version "
            f"{_e(s.get('version', 'no declarada'))}</div>"
            for s in sondas
            if isinstance(s, Mapping)
        )
        partes.append(f"<dt>Sondas ({len(sondas)})</dt><dd>{detalle}</dd>")
    hashes = manifiesto.get("hashes") or {}
    if isinstance(hashes, Mapping) and hashes:
        detalle = "".join(
            f"<div>{_e(k)} = <code>{_e(v)}</code></div>" for k, v in hashes.items()
        )
        partes.append(f"<dt>Hashes</dt><dd>{detalle}</dd>")
    partes.append("</dl>")
    return "".join(partes)


def reporte_html(
    nota: Nota,
    checks: Sequence[ResultadoCheck],
    manifiesto: Mapping[str, Any],
    supresiones_aplicadas: Sequence[Supresion] = (),
    supresiones_vencidas: Sequence[Supresion] = (),
    *,
    titulo: str = "Baremo - informe de madurez",
    supresiones_sin_efecto: Sequence[Supresion] = (),
) -> str:
    """Pagina HTML autocontenida (CSS embebido, sin CDNs), tema oscuro.

    Arriba, los dos numeros lado a lado. Si el cumplimiento esta retenido, en su lugar
    aparece RETENIDO y un banner ambar con el motivo. Cada check es colapsable y muestra
    sus sub-checks con veredicto, motivo y evidencias.
    """
    indice = _indice_notas(nota)
    retenido = not nota.publicable

    banner = ""
    if retenido:
        banner = (
            '<div class="banner"><strong>CUMPLIMIENTO RETENIDO</strong>'
            f"<p>{_e(nota.motivo_retencion)}</p></div>"
        )

    panel_cumplimiento = _panel_numero(
        "Cumplimiento",
        nota.cumplimiento,
        0.80,
        "Proporcional: cada sujeto corregido cuenta.",
        retenido=retenido,
    )
    panel_cobertura = _panel_numero(
        "Cobertura",
        nota.cobertura,
        nota.umbral_cobertura,
        f"Umbral para publicar: {_pct(nota.umbral_cobertura)}.",
    )

    cuerpo_checks = (
        "".join(_html_check(ch, _nota_para(ch, indice), nota.umbral_cobertura) for ch in checks)
        or '<p class="vacio">Ningun check produjo resultados.</p>'
    )

    sin_efecto = (
        "<h2>Supresiones vigentes sin efecto</h2>"
        + _tabla_supresiones(supresiones_sin_efecto, "Vence")
        if supresiones_sin_efecto
        else ""
    )

    generado = _e(manifiesto.get("generado_en", ""))
    version = _e(manifiesto.get("version", ""))

    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(titulo)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="envoltura">
  <header class="cabecera">
    <div class="marca">BAREMO <em>v{version}</em></div>
    <div class="dim">{generado}</div>
  </header>

  <p class="tesis">Un modelo de madurez cuyo numero mejora al mirar menos no esta midiendo
  madurez. Por eso este informe publica <strong>dos</strong> numeros: el cumplimiento nunca
  se muestra sin la cobertura que lo sostiene.</p>

  <section class="numeros">{panel_cumplimiento}{panel_cobertura}</section>
  {banner}

  <h2>Alcance</h2>
  {_html_alcance(nota)}

  <h2>Checks</h2>
  {cuerpo_checks}

  <h2>Supresiones aplicadas (vigentes)</h2>
  {_tabla_supresiones(supresiones_aplicadas, "Vence")}

  <h2>Supresiones vencidas &mdash; vuelven a contar</h2>
  {_tabla_supresiones(supresiones_vencidas, "Vencio")}
  {sin_efecto}

  <footer>
    <strong>Manifiesto</strong>
    {_html_manifiesto(manifiesto)}
  </footer>
</div>
</body>
</html>
"""
