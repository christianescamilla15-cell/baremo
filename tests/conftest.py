"""Apoyo común de las pruebas.

Dos garantías para TODAS las pruebas:
  · La sonda de confidencialidad nunca lee la lista real de términos de la máquina: se
    borra la variable de entorno y la lista local apunta a un archivo inexistente. Sin
    esto, el mismo informe daría CUMPLE en una laptop y NO_MEDIBLE en el CI, y el
    golden dejaría de ser un oráculo.
  · Los repositorios de prueba se construyen en un directorio temporal, nunca dentro de
    este árbol: Baremo se evalúa a sí mismo y un repositorio de ejemplo dentro de
    `tests/` le daría crédito por archivos que no son suyos.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from baremo.model import ResultadoCheck, Veredicto
from baremo.probes import REGISTRO, Contexto


@pytest.fixture(autouse=True)
def _sin_lista_real_de_terminos(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from baremo.probes import confidencialidad

    monkeypatch.delenv("CONFIDENCIAL_TERMINOS", raising=False)
    monkeypatch.setattr(confidencialidad, "LISTA_LOCAL", tmp_path / "no-existe" / "terminos.txt")


def construir(raiz: Path, archivos: dict[str, str | bytes]) -> Path:
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenido, bytes):
            ruta.write_bytes(contenido)
        else:
            ruta.write_text(contenido, encoding="utf-8")
    return raiz


@pytest.fixture
def repo(tmp_path: Path) -> Callable[[dict[str, str | bytes]], Path]:
    """Construye un repositorio de prueba con los archivos dados y devuelve su raíz."""
    raiz = tmp_path / "demo"
    raiz.mkdir()
    return lambda archivos: construir(raiz, archivos)


def medir(id_sonda: str, raiz: Path, nombre: str = "demo") -> ResultadoCheck:
    return REGISTRO[id_sonda]().evaluar(Contexto(ruta_repo=raiz, nombre_sujeto=nombre))


def por_sujeto(check: ResultadoCheck) -> dict[str, Veredicto]:
    return {s.sujeto: s.veredicto for s in check.subchecks}


def texto_de(check: ResultadoCheck) -> str:
    """Todo lo que el check publicaría: descripciones, motivos y evidencias."""
    partes: list[str] = []
    for s in check.subchecks:
        partes += [s.descripcion, s.motivo, s.sujeto]
        for e in s.evidencias:
            partes += [e.fuente, e.extracto, e.detalle]
    return "\n".join(partes)


#: Bytes que `Contexto.leer` trata como binario (NUL al inicio): archivo «ilegible».
BINARIO: bytes = b"\x00\x01\x02 no es texto"
