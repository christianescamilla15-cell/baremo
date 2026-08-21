"""Modelo de dominio de Baremo.

Tres inversiones respecto de un scorecard tradicional:
  1. Ante la duda NO se aprueba: existe el veredicto NO_MEDIBLE y se reporta aparte.
  2. La nota son DOS números — cumplimiento y cobertura. Sin cobertura suficiente,
     el cumplimiento no se publica.
  3. Alcance, versión y excepciones son datos DECLARADOS y visibles, no implícitos.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date


class Veredicto(str, enum.Enum):
    CUMPLE = "CUMPLE"
    NO_CUMPLE = "NO_CUMPLE"
    NO_MEDIBLE = "NO_MEDIBLE"       # no se pudo determinar: NO promedia como aprobado
    SUPRIMIDO = "SUPRIMIDO"         # excepción declarada, con justificación y vencimiento


@dataclass(frozen=True)
class Evidencia:
    """Todo veredicto debe poder mostrar QUÉ lo produjo."""
    fuente: str                     # ruta de archivo, endpoint, comando…
    extracto: str = ""              # el fragmento exacto observado
    detalle: str = ""

    def __post_init__(self) -> None:
        if not self.fuente:
            raise ValueError("una evidencia sin fuente no es evidencia")


@dataclass
class ResultadoSubcheck:
    """Unidad atómica: un hecho verificable sobre un sujeto."""
    id: str
    descripcion: str
    veredicto: Veredicto
    evidencias: list[Evidencia] = field(default_factory=list)
    motivo: str = ""
    sujeto: str = ""                # sobre qué se evaluó (repo, stack, pipeline…)

    @property
    def cuenta_para_cobertura(self) -> bool:
        return self.veredicto is not Veredicto.NO_MEDIBLE


@dataclass
class Supresion:
    """Excepción declarada. Nunca desaparece del reporte: se muestra como tal."""
    subcheck_id: str
    sujeto: str
    justificacion: str
    vence: date
    autorizada_por: str

    def vigente(self, hoy: date) -> bool:
        return hoy <= self.vence


@dataclass
class ResultadoCheck:
    """Agrupa sub-checks de un mismo control."""
    id: str
    titulo: str
    eje: str
    peso: float = 1.0
    subchecks: list[ResultadoSubcheck] = field(default_factory=list)

    @property
    def medibles(self) -> list[ResultadoSubcheck]:
        return [s for s in self.subchecks if s.cuenta_para_cobertura]

    @property
    def no_medibles(self) -> list[ResultadoSubcheck]:
        return [s for s in self.subchecks if not s.cuenta_para_cobertura]


@dataclass
class Alcance:
    """Lo que se pretendía medir vs. lo que efectivamente se midió.

    Existe porque el defecto más caro del modelo original era invisible: al reducir el
    alcance el número SUBÍA. Aquí la cobertura es un control de primera clase.
    """
    declarado: list[str] = field(default_factory=list)
    medido: list[str] = field(default_factory=list)
    excluido: dict[str, str] = field(default_factory=dict)   # sujeto -> motivo declarado

    @property
    def omitido_sin_declarar(self) -> list[str]:
        return [s for s in self.declarado
                if s not in self.medido and s not in self.excluido]
