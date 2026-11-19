# Arquitectura · Baremo

Modelo C4: contexto → contenedores → componentes. Los diagramas son texto (Mermaid), se versionan
con el código y Baremo los verifica sobre sí mismo con la sonda `documentacion.arquitectura-c4`.
Las decisiones que explican esta forma están en [../adr/](../adr/).

## 1. Contexto

Baremo es una herramienta de línea de comandos sin servicio ni red: la corre una persona o un
pipeline sobre un repositorio y devuelve un informe y un código de salida.

```mermaid
C4Context
  title Contexto · Baremo
  Person(ingeniero, "Ingeniería o auditoría", "Mide la madurez de un repositorio y lee el informe")
  System(baremo, "Baremo", "Evaluador de madurez que publica cumplimiento y cobertura")
  System_Ext(ci, "Pipeline de CI", "GitHub Actions u otro: usa el código de salida como compuerta")
  System_Ext(repo, "Repositorio evaluado", "Árbol de trabajo, historia de git, baremo.yml y supresiones.yml")
  System_Ext(lista, "Lista de términos vetados", "Secreto CONFIDENCIAL_TERMINOS o archivo local; nunca en el repo")
  Rel(ingeniero, baremo, "Corre baremo evaluar / sondas / explicar", "CLI")
  Rel(ci, baremo, "Invoca y lee el código de salida 0/1/2/3", "proceso")
  Rel(baremo, repo, "Lee archivos, git ls-files y git rev-parse", "sistema de archivos")
  Rel(baremo, lista, "Lee las expresiones de la lista", "variable de entorno o archivo")
```

## 2. Contenedores

Un solo proceso de Python 3.12 con una dependencia (PyYAML). Los «contenedores» son las piezas
desplegables por separado: la CLI, el catálogo de sondas (paquete importable, extensible por
terceros) y los archivos que entran y salen.

```mermaid
C4Container
  title Contenedores · Baremo
  Person(ingeniero, "Ingeniería o auditoría")
  System_Ext(repo, "Repositorio evaluado", "Árbol de trabajo y git")
  System_Boundary(b, "Baremo") {
    Container(cli, "CLI baremo", "Python 3.12 · argparse", "evaluar, sondas, explicar; códigos de salida")
    Container(sondas, "Catálogo de sondas", "Python · paquete baremo.probes", "16 sondas registradas; una por control")
    Container(motor, "Puntuación e informes", "Python · scoring.py y report.py", "Dos números, regla de retención, texto/JSON/HTML")
    ContainerDb(perfil, "Perfil y supresiones", "YAML · baremo.yml y supresiones.yml", "Alcance declarado, pesos, excepciones con vencimiento")
    ContainerDb(informe, "Informe", "JSON/HTML/texto", "Veredicto y evidencia por sub-check, manifiesto de la corrida")
  }
  Rel(ingeniero, cli, "Ejecuta", "terminal")
  Rel(cli, perfil, "Lee", "yaml.safe_load")
  Rel(cli, sondas, "Descubre en REGISTRO y ejecuta sobre cada sujeto")
  Rel(sondas, repo, "Lee archivos y git ls-files", "sólo lectura")
  Rel(cli, motor, "Entrega los checks con supresiones aplicadas")
  Rel(motor, informe, "Escribe")
```

## 3. Componentes del catálogo de sondas

```mermaid
C4Component
  title Componentes · catálogo de sondas (baremo.probes)
  Container(cli, "CLI baremo", "cli.py", "SondaRegistrada adapta cada sonda; una sonda que falla es NO_MEDIBLE")
  Container_Boundary(probes, "baremo.probes") {
    Component(registro, "Registro y contrato", "probes/__init__.py", "registrar(), Contexto, subcheck() rechaza veredictos sin evidencia y NO_MEDIBLE sin motivo")
    Component(apoyo, "Apoyo de lectura", "probes/_apoyo.py", "Markdown, enlaces internos, marcadores de plantilla, rutas de prueba")
    Component(base, "Sondas 0.1.0", "vcs, documentacion, entrega, ci, seguridad", "Un sub-check por hecho del repositorio")
    Component(doc, "Sondas de documentación", "arquitectura.py y publicacion.py", "C4 por nivel, ADR, README estándar, licencia, política")
    Component(prueba, "Sondas de pruebas", "pruebas.py", "E2E, paridad golden, regla por prueba (AST)")
    Component(otras, "API, análisis y confidencialidad", "api.py, analisis.py, confidencialidad.py", "Operaciones OpenAPI, escaneos que prueban que miraron, términos vetados")
  }
  Rel(cli, registro, "Lee REGISTRO y construye el Contexto")
  Rel(base, registro, "Construye sub-checks con")
  Rel(doc, apoyo, "Lee Markdown con")
  Rel(doc, registro, "Construye sub-checks con")
  Rel(prueba, registro, "Construye sub-checks con")
  Rel(otras, registro, "Construye sub-checks con")
```

## Notas

- `baremo/config.py`, `baremo/manifiesto.py` y `baremo/supresiones.py` existen como API de
  biblioteca, pero la CLI no los usa: `cli.py` tiene su propia carga de configuración, manifiesto
  y aplicación de supresiones. Las pruebas de reglas de la CLI (`tests/test_cli_reglas.py`)
  ejercen el camino que usa el producto.
- Todo sub-check por elemento se nombra `<sujeto>/<tipo>:<nombre>` (`sujeto_de`), para que en
  una corrida con varios repositorios una supresión no tape el elemento homónimo de otro.
