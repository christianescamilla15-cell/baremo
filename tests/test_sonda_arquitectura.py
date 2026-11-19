"""Sondas `documentacion.arquitectura-c4` y `documentacion.adr` (N01)."""
from __future__ import annotations

import pytest

import baremo.probes
from baremo.model import Veredicto
from conftest import BINARIO, medir, por_sujeto, texto_de

C4 = "documentacion.arquitectura-c4"
ADR = "documentacion.adr"

CONTEXTO_REAL = """```mermaid
C4Context
  title Contexto · Facturador
  Person(contador, "Contador", "Concilia facturas<br/>cada mes")
  System(facturador, "Facturador", "Emite y concilia CFDI")
  System_Ext(sat, "Autoridad fiscal", "Valida comprobantes")
  Rel(contador, facturador, "Usa", "HTTPS")
  Rel(facturador, sat, "Timbra", "SOAP")
```
"""
CONTENEDORES_REAL = """```mermaid
C4Container
  title Contenedores · Facturador
  Person(contador, "Contador")
  System_Boundary(b, "Facturador") {
    Container(api, "API", "Python · FastAPI", "Reglas de conciliación")
    ContainerDb(bd, "Base", "PostgreSQL", "Facturas y pagos")
  }
  Rel(contador, api, "Usa", "JSON/HTTPS")
  Rel(api, bd, "Lee y escribe")
```
"""
COMPONENTES_REAL = """```mermaid
C4Component
  title Componentes de la API
  Container_Boundary(api, "API") {
    Component(rutas, "Rutas", "FastAPI", "Valida la entrada")
    Component(conciliador, "Conciliador", "Python", "Cruza facturas y pagos")
  }
  Rel(rutas, conciliador, "Invoca")
```
"""
#: La plantilla común tal cual: nombre del sistema entre ángulos y descripciones «…».
CONTENEDORES_PLANTILLA = """```mermaid
C4Container
  title Contenedores · <proyecto>
  Person(usuario, "Usuario")
  System_Boundary(b, "<proyecto>") {
    Container(web, "Front", "React", "…")
    Container(api, "API", "Python · FastAPI", "…")
  }
  Rel(usuario, web, "Usa", "HTTPS")
  Rel(web, api, "Llama", "JSON/HTTPS")
```
"""


# --------------------------------------------------------------------------- C4

def test_c4_tres_niveles_reales_cumplen(repo) -> None:
    raiz = repo({"docs/arquitectura/README.md": "# Arquitectura\n\n" + CONTEXTO_REAL
                 + CONTENEDORES_REAL + COMPONENTES_REAL})
    check = medir(C4, raiz)
    assert por_sujeto(check) == {
        "demo/c4:contexto": Veredicto.CUMPLE,
        "demo/c4:contenedores": Veredicto.CUMPLE,
        "demo/c4:componentes": Veredicto.CUMPLE,
    }
    assert all(s.evidencias[0].fuente == "docs/arquitectura/README.md" for s in check.subchecks)


def test_c4_diagrama_de_plantilla_no_cumple(repo) -> None:
    raiz = repo({"docs/arquitectura/README.md": CONTEXTO_REAL + CONTENEDORES_PLANTILLA})
    check = medir(C4, raiz)
    veredictos = por_sujeto(check)
    assert veredictos["demo/c4:contexto"] is Veredicto.CUMPLE
    assert veredictos["demo/c4:contenedores"] is Veredicto.NO_CUMPLE
    assert "«<proyecto>»" in texto_de(check)


def test_c4_es_proporcional_por_nivel(repo) -> None:
    raiz = repo({"docs/c4.md": CONTEXTO_REAL})
    veredictos = por_sujeto(medir(C4, raiz))
    assert list(veredictos.values()).count(Veredicto.CUMPLE) == 1
    assert veredictos["demo/c4:componentes"] is Veredicto.NO_CUMPLE


def test_c4_diagrama_sin_relaciones_no_cuenta(repo) -> None:
    sin_relaciones = "```mermaid\nC4Context\n  Person(a, \"A\")\n  System(s, \"S\")\n```\n"
    check = medir(C4, repo({"docs/c4.md": sin_relaciones}))
    assert por_sujeto(check)["demo/c4:contexto"] is Veredicto.NO_CUMPLE
    assert "ninguna relación" in texto_de(check)


def test_c4_sin_diagramas_no_cumple_con_evidencia_de_ausencia(repo) -> None:
    check = medir(C4, repo({"README.md": "# Proyecto\n\nSin arquitectura.\n"}))
    assert set(por_sujeto(check).values()) == {Veredicto.NO_CUMPLE}
    assert all("buscado sin resultado" in s.evidencias[0].extracto for s in check.subchecks)


def test_c4_structurizr_cuenta_por_vistas(repo) -> None:
    dsl = """workspace {
  model {
    usuario = person "Contador"
    sistema = softwareSystem "Facturador" {
      api = container "API" {
        conciliador = component "Conciliador"
      }
    }
    usuario -> api "Usa"
  }
  views {
    systemContext sistema "contexto" { include * }
    container sistema "contenedores" { include * }
    component api "componentes" { include * }
  }
}
"""
    assert set(por_sujeto(medir(C4, repo({"docs/arquitectura.dsl": dsl}))).values()) == {Veredicto.CUMPLE}


def test_c4_barrido_truncado_es_no_medible(repo, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = repo({"a.txt": "a", "b.txt": "b", "docs/c4.md": CONTEXTO_REAL})
    monkeypatch.setattr(baremo.probes, "LIMITE_ARCHIVOS", 1)
    assert set(por_sujeto(medir(C4, raiz)).values()) == {Veredicto.NO_MEDIBLE}


def test_c4_sujeto_ilegible_es_no_medible(tmp_path) -> None:
    check = medir(C4, tmp_path / "no-existe")
    assert [s.veredicto for s in check.subchecks] == [Veredicto.NO_MEDIBLE]


# --------------------------------------------------------------------------- ADR

ADR_COMPLETO = """# ADR 0002 · Decisión de usar PostgreSQL

- Estado: aceptada · Fecha: 2026-11-19

## Contexto
Las conciliaciones necesitan transacciones y consultas por rango de fechas.

## Decisión
Usamos PostgreSQL 16 como única base de datos del servicio.

## Consecuencias
Las pruebas de integración levantan PostgreSQL en un contenedor efímero.
"""


def test_adr_completo_cumple(repo) -> None:
    check = medir(ADR, repo({"docs/adr/0002-postgresql.md": ADR_COMPLETO}))
    assert por_sujeto(check) == {"demo/adr:0002-postgresql": Veredicto.CUMPLE}
    assert "aceptada" in check.subchecks[0].evidencias[0].extracto


def test_adr_formato_madr_en_ingles_cumple(repo) -> None:
    madr = """# Use PostgreSQL

Status: accepted

## Context and Problem Statement
We need transactions and range queries over invoice dates.

## Decision Outcome
Chosen option: PostgreSQL 16, because it covers both needs.

### Consequences
Integration tests start PostgreSQL in a throwaway container.
"""
    assert por_sujeto(medir(ADR, repo({"docs/decisions/0003-use-postgresql.md": madr}))) == {
        "demo/adr:0003-use-postgresql": Veredicto.CUMPLE}


def test_adr_sin_consecuencias_no_cumple(repo) -> None:
    incompleto = ADR_COMPLETO.split("## Consecuencias")[0]
    check = medir(ADR, repo({"docs/adr/0002-postgresql.md": incompleto}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "consecuencias" in check.subchecks[0].evidencias[0].detalle


def test_adr_el_titulo_no_acredita_la_seccion_de_decision(repo) -> None:
    """«# ADR · Decisión de…» abarca el documento entero: no es la sección de decisión."""
    sin_seccion = ADR_COMPLETO.replace("## Decisión\n", "")
    check = medir(ADR, repo({"docs/adr/0002-postgresql.md": sin_seccion}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE


def test_adr_copiado_de_la_plantilla_no_cumple(repo) -> None:
    plantilla = ADR_COMPLETO.replace("2026-11-19", "AAAA-MM-DD")
    check = medir(ADR, repo({"docs/adr/0001-registrar-decisiones.md": plantilla}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "AAAA-MM-DD" in check.subchecks[0].evidencias[0].detalle


def test_adr_sin_estado_no_cumple(repo) -> None:
    sin_estado = ADR_COMPLETO.replace("- Estado: aceptada · Fecha: 2026-11-19\n", "")
    assert medir(ADR, repo({"docs/adr/0002-x.md": sin_estado})).subchecks[0].veredicto is Veredicto.NO_CUMPLE


def test_adr_un_subcheck_por_adr(repo) -> None:
    raiz = repo({"docs/adr/0002-a.md": ADR_COMPLETO, "docs/adr/0003-b.md": "# ADR 0003\n",
                 "docs/adr/README.md": "# Índice\n", "docs/adr/0000-plantilla.md": "# ADR NNNN\n"})
    assert por_sujeto(medir(ADR, raiz)) == {
        "demo/adr:0002-a": Veredicto.CUMPLE, "demo/adr:0003-b": Veredicto.NO_CUMPLE}


def test_sin_adrs_no_cumple(repo) -> None:
    check = medir(ADR, repo({"README.md": "# x\n"}))
    assert por_sujeto(check) == {"demo/adr:registro": Veredicto.NO_CUMPLE}


def test_adr_ilegible_es_no_medible(repo) -> None:
    check = medir(ADR, repo({"docs/adr/0002-binario.md": BINARIO}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
    assert check.subchecks[0].motivo


def test_sin_adrs_y_barrido_truncado_es_no_medible(repo, monkeypatch: pytest.MonkeyPatch) -> None:
    raiz = repo({"a.txt": "a", "b.txt": "b"})
    monkeypatch.setattr(baremo.probes, "LIMITE_ARCHIVOS", 1)
    assert medir(ADR, raiz).subchecks[0].veredicto is Veredicto.NO_MEDIBLE
