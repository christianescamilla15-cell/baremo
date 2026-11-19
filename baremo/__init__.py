"""Baremo - evaluador de madurez de ingenieria.

Tesis: un modelo de madurez cuyo numero mejora al mirar menos no esta midiendo madurez.

De ahi las cuatro decisiones que definen el paquete:
  1. Ante la duda NO se aprueba: existe el veredicto NO_MEDIBLE y no promedia.
  2. La nota son DOS numeros - cumplimiento y cobertura. Sin cobertura suficiente el
     cumplimiento se RETIENE, no se publica.
  3. Alcance, version de la herramienta y supresiones son datos DECLARADOS y visibles.
  4. La puntuacion es PROPORCIONAL: corregir 58 de 59 sujetos sube la nota.

Uso como biblioteca:

    from baremo import puntuar, reporte_json, Alcance

Uso como herramienta:

    baremo evaluar ./repo --formato html --salida informe.html
"""
from __future__ import annotations

__version__ = "0.2.0"

from baremo.model import (
    Alcance,
    Evidencia,
    ResultadoCheck,
    ResultadoSubcheck,
    Supresion,
    Veredicto,
)
from baremo.report import (
    ESQUEMA,
    ESQUEMA_VERSION,
    reporte_html,
    reporte_json,
    reporte_texto,
)
from baremo.scoring import (
    UMBRAL_COBERTURA_POR_DEFECTO,
    Nota,
    NotaCheck,
    puntuar,
)

__all__ = [
    "__version__",
    # modelo
    "Alcance",
    "Evidencia",
    "ResultadoCheck",
    "ResultadoSubcheck",
    "Supresion",
    "Veredicto",
    # puntuacion
    "Nota",
    "NotaCheck",
    "UMBRAL_COBERTURA_POR_DEFECTO",
    "puntuar",
    # reportes
    "ESQUEMA",
    "ESQUEMA_VERSION",
    "reporte_html",
    "reporte_json",
    "reporte_texto",
]
