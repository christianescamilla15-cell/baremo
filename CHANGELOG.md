# Cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/); versiones
[semánticas](https://semver.org/lang/es/). Las notas de versiones con catálogos distintos **no se
comparan**: cambia el denominador.

## [0.2.0] - 2026-11-19

### Añadido
- Once sondas nuevas, cada una con pruebas de sus tres caminos (`CUMPLE`, `NO_CUMPLE`,
  `NO_MEDIBLE`):
  - `documentacion.arquitectura-c4`: un diagrama C4 real por nivel (Mermaid o Structurizr); una
    plantilla sin adaptar no cuenta.
  - `documentacion.adr`: ADR numerados con estado, contexto, decisión y consecuencias.
  - `documentacion.readme-estandar`, `documentacion.licencia`,
    `documentacion.politica-de-seguridad`.
  - `api.openapi-documentada`: un sub-check por operación; `NO_MEDIBLE` si no hay API.
  - `pruebas.e2e-presente`, `pruebas.paridad-golden`, `pruebas.regla-por-prueba`.
  - `seguridad.confidencialidad`: términos vetados sin imprimir nunca el término.
  - `entrega.check-que-analiza`: cada escaneo prueba que analizó algo.
- `sujeto_de()` para nombrar sub-checks por elemento (`<sujeto>/<tipo>:<nombre>`).
- Pruebas del contrato de sondas, de la CLI (salidas 1, 3 y 64; supresiones), de las sondas de la
  0.1.0, E2E de la CLI como proceso y paridad contra un informe golden con control negativo.
- CI (pruebas en Python 3.12 y 3.13, autoevaluación con `baremo.yml`), flujo de seguridad
  (confidencialidad, gitleaks, CodeQL, Semgrep, Trivy, SBOM), Dependabot, CODEOWNERS, ruleset de
  la rama principal, `SECURITY.md`, `RUNBOOK.md`, modelo C4, ADR y `docs/reglas.md`.

### Cambiado
- La tabla «Sondas incluidas» del README describe el catálogo real (antes listaba 21 checks que el
  código no tenía) y el ejemplo de «Escribir tu propia sonda» usa el API real de clases.
- Dos importaciones dinámicas de `cli.py` llevan `nosemgrep` justificado.

### Notas
- El catálogo pasa de 5 a 16 sondas: las notas de 0.1.0 y 0.2.0 no se comparan.

## [0.1.0] - 2026-08-21

### Añadido
- Primera versión: puntuación proporcional, veredicto `NO_MEDIBLE`, dos números (cumplimiento y
  cobertura) con regla de retención, supresiones con vencimiento y cinco sondas (`vcs`,
  `documentacion`, `entrega`, `ci`, `seguridad`).
