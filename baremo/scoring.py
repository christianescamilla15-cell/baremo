"""Puntuación de Baremo: DOS números, no uno.

  cumplimiento = Σ(peso · aprobados/medibles) / Σ(peso)     ← proporcional, no todo-o-nada
  cobertura    = medibles / (medibles + no_medibles + omitidos_sin_declarar)

Reglas de diseño, cada una cerrando un defecto medido en modelos v1:

  · PROPORCIONAL — corregir 58 de 59 sujetos debe subir la nota. En un modelo
    "mezcla = 50 puntos" el esfuerzo no se ve y se desincentiva terminar.
  · LO NO MEDIBLE NO PROMEDIA — nunca cuenta como aprobado ni como reprobado:
    baja la COBERTURA. Así, degradar la instrumentación ya no puede subir la nota.
  · SIN COBERTURA NO SE PUBLICA — bajo el umbral, el cumplimiento se retiene.
    Un número que mejora al mirar menos no mide madurez.
  · LAS SUPRESIONES SE VEN — una excepción declarada y vigente no reprueba, pero
    aparece en el reporte y expira. Una supresión vencida vuelve a contar.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from baremo.model import Alcance, ResultadoCheck, Veredicto

UMBRAL_COBERTURA_POR_DEFECTO = 0.80


@dataclass
class NotaCheck:
    id: str
    titulo: str
    eje: str
    peso: float
    aprobados: int
    reprobados: int
    suprimidos: int
    no_medibles: int

    @property
    def medibles(self) -> int:
        return self.aprobados + self.reprobados + self.suprimidos

    @property
    def cumplimiento(self) -> float | None:
        """Proporción de sujetos que cumplen. None si nada fue medible."""
        if self.medibles == 0:
            return None
        return (self.aprobados + self.suprimidos) / self.medibles

    @property
    def cobertura(self) -> float:
        total = self.medibles + self.no_medibles
        return 1.0 if total == 0 else self.medibles / total


@dataclass
class Nota:
    checks: list[NotaCheck] = field(default_factory=list)
    alcance: Alcance = field(default_factory=Alcance)
    umbral_cobertura: float = UMBRAL_COBERTURA_POR_DEFECTO

    @property
    def cumplimiento(self) -> float | None:
        """Media ponderada por peso; sólo sobre checks que midieron algo."""
        con_dato = [c for c in self.checks if c.cumplimiento is not None]
        peso_total = sum(c.peso for c in con_dato)
        if peso_total == 0:
            return None
        return sum(c.peso * c.cumplimiento for c in con_dato) / peso_total  # type: ignore[operator]

    @property
    def cobertura(self) -> float:
        """Incluye lo que se declaró medir y NO se midió: el alcance omitido pesa."""
        medibles = sum(c.medibles for c in self.checks)
        no_medibles = sum(c.no_medibles for c in self.checks)
        omitidos = len(self.alcance.omitido_sin_declarar)
        total = medibles + no_medibles + omitidos
        return 1.0 if total == 0 else medibles / total

    @property
    def publicable(self) -> bool:
        return self.cumplimiento is not None and self.cobertura >= self.umbral_cobertura

    @property
    def motivo_retencion(self) -> str:
        if self.cumplimiento is None:
            return "Ningún check pudo medirse: no hay cumplimiento que reportar."
        if self.cobertura < self.umbral_cobertura:
            faltantes = self.alcance.omitido_sin_declarar
            extra = f" Sujetos declarados que no se midieron ni se excluyeron: {', '.join(faltantes)}." if faltantes else ""
            return (
                f"Cobertura {self.cobertura:.0%} por debajo del umbral "
                f"{self.umbral_cobertura:.0%}: el cumplimiento se retiene porque el número "
                f"no sería comparable.{extra}"
            )
        return ""


def puntuar(checks: list[ResultadoCheck], alcance: Alcance,
            umbral_cobertura: float = UMBRAL_COBERTURA_POR_DEFECTO) -> Nota:
    notas: list[NotaCheck] = []
    for ch in checks:
        aprobados = sum(1 for s in ch.subchecks if s.veredicto is Veredicto.CUMPLE)
        reprobados = sum(1 for s in ch.subchecks if s.veredicto is Veredicto.NO_CUMPLE)
        suprimidos = sum(1 for s in ch.subchecks if s.veredicto is Veredicto.SUPRIMIDO)
        no_medibles = sum(1 for s in ch.subchecks if s.veredicto is Veredicto.NO_MEDIBLE)
        notas.append(NotaCheck(
            id=ch.id, titulo=ch.titulo, eje=ch.eje, peso=ch.peso,
            aprobados=aprobados, reprobados=reprobados,
            suprimidos=suprimidos, no_medibles=no_medibles,
        ))
    return Nota(checks=notas, alcance=alcance, umbral_cobertura=umbral_cobertura)
