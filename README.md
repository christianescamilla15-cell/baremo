# Baremo

[![ci](https://github.com/christianescamilla15-cell/baremo/actions/workflows/ci.yml/badge.svg)](https://github.com/christianescamilla15-cell/baremo/actions/workflows/ci.yml)
[![seguridad](https://github.com/christianescamilla15-cell/baremo/actions/workflows/seguridad.yml/badge.svg)](https://github.com/christianescamilla15-cell/baremo/actions/workflows/seguridad.yml)

Evaluador de madurez de ingeniería que publica **dos números** —cumplimiento y cobertura— y se
niega a publicar el primero cuando el segundo no alcanza.

> **Un modelo de madurez cuyo número mejora al mirar menos no está midiendo madurez.**

Baremo corre sobre un repositorio, emite un veredicto por cada sujeto observado, adjunta la
evidencia que lo produjo, y declara en el encabezado qué se midió, qué se excluyó y qué se
suprimió. Python 3.12, biblioteca estándar + PyYAML. Sin servicios, sin telemetría, sin cuenta.

---

## El problema

Los scorecards de madurez que se usan para gobernar plataformas comparten tres patologías. No son
errores de implementación: son decisiones de diseño que hacen que el número suba cuando la
ingeniería empeora.

### a) Agregación todo-o-nada: corregir 58 de 59 sujetos no mueve la nota

El patrón habitual colapsa todas las sub-verificaciones de un control en **un solo estado**:

```
pass   si todas pasaron          → 100 puntos
warn   si hubo mezcla            →  50 puntos
fail   si todas fallaron         →   0 puntos
```

Un eje con 8 controles vale 12.5 puntos por control. Supón el control «cada pila de
infraestructura declara las etiquetas obligatorias», con **59 pilas**:

| Estado real | Sub-verificaciones | Estado del control | Nota del eje |
|---|---|---|---|
| 1 pila correcta de 59 | 1 pass · 58 fail | `warn` (mezcla) | **93** |
| 58 pilas correctas de 59 | 58 pass · 1 fail | `warn` (mezcla) | **93** |
| 59 pilas correctas | 59 pass | `pass` | **100** |

Arreglar 57 pilas: **+0 puntos**. Arreglar la número 59: **+7 puntos**. Toda la recompensa está
en el último sujeto, así que el trabajo intermedio es invisible y nadie lo emprende. Peor: un
equipo que va en 58/59 y otro que va en 1/59 aparecen idénticos en la tabla que ve el comité.

### b) El alcance no está declarado: reducir el alcance SUBE el número

Si el denominador es «lo que la corrida alcanzó a mirar», recortar la mirada es la palanca más
barata que existe.

| Corrida | Universo real | Sujetos evaluados | Conformes | Nota |
|---|---|---|---|---|
| Enero | 12 pilas | 12 | 8 | **66 %** |
| Febrero — el manifiesto enumera 6 | 12 pilas | 6 (las sanas) | 6 | **100 %** |

Entre enero y febrero **no se tocó un solo recurso**. La nota subió 34 puntos. La variante
silenciosa de lo mismo: el verificador pagina mal y lee las primeras 10 de 48 pilas; el reporte
dice 100 % y no dice «10 de 48». Cuando el alcance no es un dato de entrada declarado, la
diferencia entre «todo bien» y «casi no miré» no aparece en ninguna parte del reporte.

### c) Ante la duda aprueban: degradar la instrumentación mejora la calificación

Cuando un control no puede medirse —credencial sin permiso, API que expira, artefacto ausente— el
modelo típico no tiene dónde ponerlo, así que lo trata como advertencia (50 puntos) o, cuando la
función no encontró nada que revisar, como aprobado.

| Eje de 5 controles | Resultado | Nota |
|---|---|---|
| 3 conformes · 2 no conformes | medido de verdad | **60** |
| 3 conformes · 2 **ilegibles** (permiso retirado) | `warn` × 2 | **80** |

Retirar un permiso de lectura vale **+20 puntos**. El incentivo está invertido de forma exacta: la
manera más rápida de subir la calificación es empeorar la capacidad de medir. Y como el reporte no
distingue «no cumple» de «no pude ver», nadie detecta la maniobra leyendo el resultado.

---

## Cómo lo resuelve Baremo

| Patología | Decisión de diseño en Baremo |
|---|---|
| Mezcla pass+fail vale lo mismo que fallar | **Puntuación proporcional**: `cumplimiento(check) = conformes / medibles`. 58 de 59 vale 98.3 %, no 50 %. |
| Un control que no pudo medirse cobra puntos | Veredicto **`NO_MEDIBLE`**: sale del numerador **y del denominador** del cumplimiento, y baja la **cobertura**. |
| «No encontré nada» se acredita como conforme | Una sonda **no aprueba por ausencia**. Sin evidencia no hay `CUMPLE`; el veredicto por defecto ante la duda es `NO_MEDIBLE`. |
| El alcance es implícito y encoger la mirada sube el número | El **alcance se declara** en `baremo.yml`. Lo declarado y no medido ni excluido cuenta como cobertura perdida: encoger la mirada **baja** el número. |
| Excluir es gratis y no se ve | Excluir exige **motivo escrito**, y el motivo se imprime en el encabezado del reporte. |
| Las excepciones viven en el código del verificador | **Supresiones declaradas** en `supresiones.yml`, con justificación, autorizador y **fecha de vencimiento**. Vencen solas y vuelven a contar. |
| Un número que mejora al mirar menos | **Regla de retención**: bajo el umbral de cobertura, el cumplimiento **no se publica**. |
| Todo veredicto es una afirmación sin respaldo | **Evidencia obligatoria**: cada veredicto lleva fuente y extracto. `Evidencia` sin `fuente` lanza excepción en construcción. |

---

## Los dos números

### Cumplimiento — sobre lo que se pudo medir

```
medibles(check)      = CUMPLE + NO_CUMPLE + SUPRIMIDO          (NO_MEDIBLE queda fuera)
cumplimiento(check)  = (CUMPLE + SUPRIMIDO) / medibles(check)   None si medibles == 0

                       Σ  peso_c · cumplimiento(c)
cumplimiento(nota) = ───────────────────────────────      sólo sobre checks con dato
                       Σ  peso_c
```

Es proporcional por construcción: cada sujeto observado mueve la aguja lo que le toca. Una
supresión **vigente** cuenta como conforme —para eso se autoriza— pero aparece listada aparte;
una supresión **vencida** deja de aplicarse sola y el sujeto vuelve a contar como lo que sea.

### Cobertura — cuánto del alcance se pudo mirar

```
                     medibles
cobertura(nota) = ──────────────────────────────────────────────────
                  medibles + no_medibles + omitidos_sin_declarar

omitidos_sin_declarar = sujetos del alcance declarado que no se midieron
                        y tampoco se excluyeron con motivo
```

Los dos sumandos del denominador son las dos formas de dejar de ver: **no pude** (`NO_MEDIBLE`) y
**ni lo intenté** (omitido). Ambas bajan la cobertura. Por eso ninguna de las dos puede subir la
nota.

### Regla de retención

```
publicable  ⟺  cumplimiento is not None  ∧  cobertura ≥ umbral_cobertura      (por defecto 0.80)
```

Si no es publicable, Baremo **no imprime el porcentaje de cumplimiento**. Imprime el motivo de
retención, la cobertura obtenida y la lista nominal de lo que faltó. No es una advertencia
decorativa: el número simplemente no está, porque un cumplimiento calculado sobre el 40 % del
alcance no es comparable con uno calculado sobre el 95 % y presentarlos en la misma columna es el
origen de toda la patología.

---

## Instalación y uso

Requisitos: Python 3.12 o superior. Única dependencia: PyYAML.

```bash
git clone https://github.com/christianescamilla15-cell/baremo.git
cd baremo
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Evaluar el repositorio actual:

```bash
baremo evaluar .
```

Opciones frecuentes:

```bash
baremo evaluar .  --config baremo.yml           # configuración explícita
baremo evaluar .  --umbral-cobertura 0.90       # sobrescribe el umbral del archivo
baremo evaluar .  --formato json --salida reporte.json
baremo sondas                                   # lista las sondas registradas y su eje
baremo evaluar . --help                         # todas las banderas
```

Códigos de salida, pensados para usarse como compuerta en un pipeline:

| Código | Significado |
|---|---|
| `0` | Nota publicable y por encima del umbral de cumplimiento |
| `1` | Nota publicable y por debajo del umbral de cumplimiento |
| `2` | **Corrida incompleta**: cobertura insuficiente, cumplimiento retenido |
| `3` | Error de configuración (alcance mal declarado, sonda inexistente, YAML inválido) |

Un pipeline que trata `2` como éxito está reintroduciendo la patología (c) por la puerta de atrás.

### Salida de consola — corrida publicable

Las dos salidas de ejemplo son ilustrativas: muestran una corrida sobre un alcance de varios
pipelines y plantillas. El catálogo real de esta versión está en [Sondas incluidas](#sondas-incluidas).

```
baremo 0.1.0 · catálogo de sondas 6 ejes / 21 checks
sujeto: .  ·  perfil: baremo.yml  ·  2026-08-21 11:04:37

ALCANCE   declarados 24 · medidos 23 · excluidos 1 · omitidos sin declarar 0
          excluido  paquete:docs-sitio  →  "sitio estático, sin cadena de construcción"
          ventana de tasas 90 días · rama de referencia origin/main

EJE           CHECK                              CUMPLE  NO_CUM  SUPR  NO_MED   CUMPL   COBERT
procedencia   rama-protegida                          1       0     0       0   100.0%   100.0%
procedencia   propietarios-de-codigo                  7       2     0       0    77.8%   100.0%
procedencia   commits-con-identificador             112       6     0       0    94.9%   100.0%
entrega       pipeline-declarado                      3       0     0       0   100.0%   100.0%
entrega       etapa-de-pruebas                        3       0     0       0   100.0%   100.0%
entrega       compuerta-antes-de-produccion           2       1     0       0    66.7%   100.0%
seguridad     sast-en-la-cadena                       0       0     1       0   100.0%   100.0%
seguridad     sca-en-la-cadena                        3       0     0       0   100.0%   100.0%
seguridad     gate-bloqueante-por-severidad           1       2     0       0    33.3%   100.0%
iac           etiquetas-obligatorias                 58       1     0       0    98.3%   100.0%
iac           sin-secretos-en-parametros             59       0     0       0   100.0%   100.0%
…

CUMPLIMIENTO   87.4 %      media ponderada sobre 21 checks con dato
COBERTURA      98.7 %      medibles 235 / (medibles 235 + no medibles 3 + omitidos 0)
                           umbral 80.0 % — PUBLICABLE

NO MEDIBLES (3)
  seguridad.dependencias-fijadas  · manifiesto:frontend  formato de bloqueo no reconocido
  operacion.enlaces-del-runbook   · enlace:tablero       destino externo, no verificable
  operacion.enlaces-del-runbook   · enlace:inventario    destino externo, no verificable

SUPRESIONES VIGENTES (1)
  seguridad.sast-en-la-cadena · sujeto pipeline:backend
    "el SAST corre en la plataforma de análisis, fuera de este repositorio"
    autoriza: equipo-de-seguridad · vence 2026-12-31 (132 días)

DEUDA — los 3 sujetos no conformes de mayor peso
  seguridad.gate-bloqueante-por-severidad · pipeline:api      la etapa reporta, no detiene
  seguridad.gate-bloqueante-por-severidad · pipeline:workers  la etapa reporta, no detiene
  entrega.compuerta-antes-de-produccion   · pipeline:workers  despliega sin aprobación

salida: 0
```

Obsérvese `iac.etiquetas-obligatorias`: **58 de 59** da 98.3 %, no «advertencia». Ese es el
ejemplo (a) resuelto.

### Salida de consola — corrida retenida

```
baremo 0.1.0 · catálogo de sondas 6 ejes / 21 checks
sujeto: .  ·  perfil: baremo.yml  ·  2026-08-21 11:19:02

ALCANCE   declarados 21 · medidos 14 · excluidos 1 · omitidos sin declarar 6
          omitidos  plantilla:datos, plantilla:computo, pipeline:workers,
                    pipeline:frontend, paquete:workers, runbook:principal

COBERTURA      58.3 %      medibles 14 / (medibles 14 + no medibles 4 + omitidos 6)
                           umbral 80.0 %

⚠ CUMPLIMIENTO RETENIDO
  Cobertura 58% por debajo del umbral 80%: el cumplimiento se retiene porque el número
  no sería comparable. Sujetos declarados que no se midieron ni se excluyeron:
  plantilla:datos, plantilla:computo, pipeline:workers, pipeline:frontend,
  paquete:workers, runbook:principal.

NO MEDIBLES (4)
  iac.etiquetas-obligatorias       · plantilla:red      no se reconoce el formato de la plantilla
  iac.sin-secretos-en-parametros   · plantilla:red      no se reconoce el formato de la plantilla
  seguridad.gate-bloqueante-por-severidad · pipeline:api  la definición no declara condición de fallo
  operacion.enlaces-del-runbook    · enlace:tablero    destino externo, no verificable

salida: 2
```

Ese `2` es todo el producto. En un scorecard tradicional esta misma corrida habría impreso un
número —probablemente alto, porque midió justo lo que estaba sano— y nadie habría sabido que se
calculó sobre poco más de la mitad del alcance.

---

## Configuración

### `baremo.yml`

Perfil del repositorio evaluado. Se indica con `--config`: sin esa bandera Baremo no lee ningún
perfil (umbral de cobertura por defecto y alcance = las rutas pasadas).
Ejemplo completo y comentado en [`examples/baremo.yml`](examples/baremo.yml).

```yaml
version: 1                      # versión del formato de configuración

proyecto: "<app>"
entorno: "<entorno>"            # el entorno es un DATO del reporte, no un supuesto

umbral_cobertura: 0.80          # bajo esto, el cumplimiento se retiene

alcance:
  declarado:                    # el universo que esta corrida se compromete a mirar
    - "repositorio:<app>"
    - "pipeline:api"
    - "plantilla:red"
  excluido:                     # excluir exige MOTIVO, y el motivo se imprime
    "paquete:docs-sitio": "sitio estático, sin cadena de construcción"

sondas:
  incluir: ["procedencia.*", "entrega.*", "seguridad.*"]
  excluir: ["iac.*"]            # lo excluido NO desaparece: cuenta contra la cobertura

pesos:                          # ponderación explícita por riesgo; 1.0 por defecto
  seguridad.gate-bloqueante-por-severidad: 3.0

supresiones: "supresiones.yml"

salida:
  formato: ["consola", "json"]
  ruta: "reportes/"
```

### `supresiones.yml`

Excepciones declaradas, **fuera del código del verificador y dentro del repositorio evaluado**.
Ejemplo comentado en [`examples/supresiones.yml`](examples/supresiones.yml).

```yaml
supresiones:
  - subcheck_id: "seguridad.sast-en-la-cadena"
    sujeto: "pipeline:backend"
    justificacion: >
      El análisis estático corre en la plataforma de análisis de la organización,
      disparado fuera de este repositorio. Baremo no puede observarlo desde el árbol
      de archivos; el resultado se consulta en el tablero de la plataforma.
    vence: 2026-12-31
    autorizada_por: "equipo-de-seguridad"
```

Cuatro propiedades que no son negociables:

1. **`vence` es obligatorio.** Una supresión sin fecha es una whitelist, y las whitelists no
   caducan nunca. La lista vencida sigue en el reporte, marcada como vencida y **contando**.
2. **`justificacion` se imprime completa.** Si el motivo no aguanta ser leído en voz alta en una
   revisión, no es un motivo.
3. **`autorizada_por` tiene nombre.** No «el equipo».
4. **Una supresión no borra el sujeto**: lo mueve a la columna `SUPR`, que se ve en la tabla y se
   lista aparte. Se sabe siempre cuánto del cumplimiento viene de cumplir y cuánto de excepción.

---

## Sondas incluidas

Una **sonda** produce un `ResultadoCheck`: un control, con un `ResultadoSubcheck` por cada sujeto
observado. Ahí vive la proporcionalidad — 59 operaciones de una API son 59 sub-checks, no un
semáforo.

Todas las sondas incluidas leen **el repositorio**: árbol de archivos y artefactos de
configuración versionados. `baremo sondas` lista las que tu instalación registra y
`baremo explicar <SUB_CHECK>` explica cada sub-check. Una prueba exige que esta tabla liste
todas las sondas registradas.

| Eje | Sonda | Qué evalúa | Sujeto |
|---|---|---|---|
| Control de versiones | `vcs` | `.gitignore` con los artefactos habituales; CODEOWNERS con reglas; ningún valor con **forma** de credencial (no se marca por nombre de variable); protección de rama declarada como archivo. Sin declaración legible → `NO_MEDIBLE`. | repositorio |
| Documentación | `documentacion` | README con caracteres **útiles** suficientes (no cuentan insignias ni URL); comando de arranque dentro de un bloque de código; registro de decisiones; licencia. | repositorio |
| Documentación | `documentacion.arquitectura-c4` | Por nivel, un diagrama C4 **real**: bloque Mermaid `C4Context`/`C4Container`/`C4Component` o vista de Structurizr, con elementos del nivel, relaciones y sin marcadores de plantilla (`<proyecto>`, `"…"`, `AAAA-MM-DD`). Una plantilla sin adaptar no cuenta. | nivel C4 |
| Documentación | `documentacion.adr` | Cada ADR numerado declara un estado reconocible y tiene contexto, decisión y consecuencias con contenido. | ADR |
| Documentación | `documentacion.readme-estandar` | Insignia de CI que apunta a un flujo **existente que corre pruebas**; insignia de seguridad a uno **que escanea**; secciones de arquitectura, ejecución, pruebas, seguridad y licencia con algo verificable (enlace interno que resuelve, comando en bloque de código). | elemento del README |
| Documentación | `documentacion.licencia` | El texto de la licencia se reconoce (huella o cabecera SPDX), lleva año y titular cuando la licencia lo exige, y cada manifiesto de paquete declara la **misma** licencia. Texto no reconocido → `NO_MEDIBLE`. | archivo y manifiesto |
| Documentación | `documentacion.politica-de-seguridad` | `SECURITY.md` con canal **privado** de reporte (no un correo de ejemplo), plazo de respuesta y sin huecos de plantilla. | canal, plazo, adaptada |
| API | `api.openapi-documentada` | Por cada spec OpenAPI/Swagger, cada operación con resumen, respuestas descritas y esquemas (`$ref` resueltos). El cumplimiento del check es el % de operaciones documentadas. Código con rutas HTTP y sin spec → `NO_CUMPLE`; repositorio sin API → `NO_MEDIBLE`. | operación |
| Entrega y operación | `entrega` | Imagen de contenedor; usuario de ejecución no privilegiado (sin Dockerfile → `NO_MEDIBLE`); comprobación de salud; infraestructura como código. | repositorio |
| Entrega y operación | `entrega.check-que-analiza` | Cada escaneo de seguridad del pipeline **prueba que analizó algo**: un paso que verifica su reporte y que puede fallar (no `continue-on-error`, no `\|\| true`), o una herramienta que falla sola con cero archivos. Sin escaneos → `NO_MEDIBLE`. | job |
| Integración continua | `ci` | Pipeline versionado; invoca un corredor de pruebas (se lee el comando, no el nombre del paso); acciones e imágenes ancladas; sin credenciales en claro. | repositorio |
| Pruebas | `pruebas.e2e-presente` | Cada archivo E2E ejerce el sistema **desde fuera** (navega, llama por HTTP o ejecuta el programa como proceso) y **afirma** algo. | archivo E2E |
| Pruebas | `pruebas.paridad-golden` | Cada archivo de referencia (golden/oráculo) lo compara por igualdad una prueba que lo nombra. Un golden que nadie compara es un oráculo huérfano. | archivo golden |
| Pruebas | `pruebas.regla-por-prueba` | Cada regla de `docs/reglas.md` apunta a pruebas que **existen** (archivo y función, Python leído por AST) y no están marcadas skip/xfail. Sin el mapa → `NO_MEDIBLE`. | regla |
| Seguridad | `seguridad` | Política publicada; proceso de excepciones (vocabulario en dos idiomas); escaneo de dependencias; análisis estático. Nunca entra a directorios de dependencias. | repositorio |
| Seguridad | `seguridad.confidencialidad` | Ningún archivo versionado menciona un término de la lista vetada (variable `CONFIDENCIAL_TERMINOS` o `~/.config/confidencial/terminos.txt`). La evidencia da archivo, línea y número de regla, **nunca el término**. Sin lista → `NO_MEDIBLE`. | repositorio |

Nótese el patrón que se repite: **sustancia antes que nombre**. Una carpeta `e2e/` no acredita
nada; acredita una prueba que ejerce el sistema y afirma. Una insignia no acredita nada; acredita
el flujo al que apunta. Y donde la sonda no puede afirmar, dice `NO_MEDIBLE` — que cuesta
cobertura, no cumplimiento.

---

## Escribir tu propia sonda

Una sonda es una clase registrada con `@registrar("<id>")` cuyo método `evaluar` recibe un
`Contexto` y devuelve un `ResultadoCheck`. Los sub-checks se construyen con `subcheck()`, que
**hace cumplir el contrato**: un `CUMPLE` o `NO_CUMPLE` sin evidencia, o un `NO_MEDIBLE` sin
motivo, lanzan `ValueError`.

```python
"""Sonda de ejemplo: cada paquete distribuible declara su licencia."""
from __future__ import annotations

from baremo.model import Evidencia, ResultadoCheck, Veredicto
from baremo.probes import Contexto, Sonda, evidencia_de_ausencia, registrar, subcheck, sujeto_de


@registrar("operacion.licencia-por-paquete")
class SondaLicenciaPorPaquete(Sonda):
    titulo = "Cada paquete distribuible declara su licencia"
    eje = "Operación"
    descripciones = {"LIC_PAQUETE": "El paquete tiene archivo de licencia"}

    def evaluar(self, ctx: Contexto) -> ResultadoCheck:
        if not ctx.repo_legible:
            return self._sin_sujeto(ctx)          # todo NO_MEDIBLE, con motivo
        paquetes = [m.parent for m in ctx.buscar(["*/pyproject.toml"])]
        if not paquetes:
            # NO se aprueba por ausencia: no encontrar sujetos NO es cumplir.
            return self._check([subcheck(
                "LIC_PAQUETE", self.descripciones["LIC_PAQUETE"], Veredicto.NO_MEDIBLE,
                sujeto_de(ctx, "paquete", "*"),
                motivo="No hay paquetes distribuibles: no hay nada que afirmar ni que negar.",
            )])
        resultado = []
        for paquete in paquetes:
            licencia = next(iter(paquete.glob("LICENSE*")), None)
            sujeto = sujeto_de(ctx, "paquete", paquete.name)
            if licencia is None:
                # La evidencia de una AUSENCIA es dónde se buscó.
                resultado.append(subcheck(
                    "LIC_PAQUETE", self.descripciones["LIC_PAQUETE"], Veredicto.NO_CUMPLE, sujeto,
                    [evidencia_de_ausencia(ctx, [f"{ctx.rel(paquete)}/LICENSE*"])],
                ))
                continue
            primera = (ctx.leer(licencia) or "").strip().splitlines()[:1] or ["(vacío)"]
            resultado.append(subcheck(
                "LIC_PAQUETE", self.descripciones["LIC_PAQUETE"], Veredicto.CUMPLE, sujeto,
                [Evidencia(fuente=ctx.rel(licencia), extracto=primera[0])],
            ))
        return self._check(resultado)
```

Un sub-check por sujeto, evidencia en todos los caminos, y ningún `CUMPLE` que provenga de no
haber encontrado nada. Las sondas del catálogo viven en [`baremo/probes/`](baremo/probes/) y cada
una tiene pruebas con sus tres caminos (`CUMPLE`, `NO_CUMPLE`, `NO_MEDIBLE`) en `tests/`.

---

## Lo que Baremo NO hace

Con la misma honestidad que le exige a sus sondas:

- **No reemplaza una auditoría.** Mide artefactos versionados, no intención, no proceso, no lo que
  ocurre cuando alguien decide saltarse el pipeline. Un repositorio impecable puede pertenecer a
  una organización que despliega a mano los viernes.
- **No verifica en la nube.** Las sondas incluidas **miran el repositorio**: árbol de archivos,
  historia y configuración versionada. No consultan el estado desplegado, no comparan lo declarado
  con lo que está corriendo, no detectan deriva. Escribir sondas que sí lo hagan es posible —el
  contrato es el mismo— pero requiere credenciales, y con credenciales cambia el modelo de
  amenaza de la herramienta. No viene de fábrica.
- **No mide eficacia, salvo donde puede leerla.** Que exista una etapa de escaneo no dice que
  encuentre nada. Baremo lee la condición de fallo cuando está declarada y responde `NO_MEDIBLE`
  cuando no; no simula un despliegue malo para ver si lo detendrían.
- **No agrega entre entornos ni entre aplicaciones.** Una corrida evalúa un sujeto. La regla de
  consolidación es una decisión de la organización y debe publicarse junto a la tabla; Baremo se
  niega a inventarla, porque el promedio silencioso entre entornos es precisamente donde se pierde
  el resultado de producción.
- **No sabe cuánto vale cada control en tu contexto.** Los pesos por defecto son 1.0. Si el gate
  bloqueante vale tres veces la existencia de un runbook, eso se declara en `baremo.yml` y queda
  versionado; Baremo no trae una jerarquía de riesgo universal porque no existe.
- **No compara corridas de catálogos distintos.** Si cambia el conjunto de sondas, cambia el
  denominador. El reporte estampa la versión del catálogo justo para que nadie ponga las dos notas
  en la misma gráfica.

---

## Arquitectura

Modelo C4 (contexto, contenedores y componentes) en Mermaid:
[docs/arquitectura/README.md](docs/arquitectura/README.md). Las decisiones que explican por qué
Baremo es como es están en [docs/adr/](docs/adr/).

## Pruebas

```bash
pip install -e ".[dev]"
pytest -q
```

La compuerta no es el porcentaje de cobertura de código sino **una prueba por regla**: el mapa
regla de negocio → prueba está en [docs/reglas.md](docs/reglas.md) y Baremo lo verifica sobre sí
mismo con `pruebas.regla-por-prueba`. Hay además pruebas de extremo a extremo de la CLI como
proceso (`tests/e2e/`) y una prueba de paridad contra un informe de referencia revisado a mano
(`tests/golden/`), con su control negativo. En el CI, Baremo se evalúa a sí mismo con
[`baremo.yml`](baremo.yml) y falla si queda por debajo de su propio umbral.

## Seguridad

Cómo reportar una vulnerabilidad y qué revisa cada cambio: [SECURITY.md](SECURITY.md). Operación y
publicación de versiones: [RUNBOOK.md](RUNBOOK.md). Historial: [CHANGELOG.md](CHANGELOG.md).

---

## Licencia

MIT. Ver [LICENSE](LICENSE).

Contribuciones: ver [CONTRIBUTING.md](CONTRIBUTING.md). El criterio de diseño que debe respetar
cualquier sonda nueva —evidencia obligatoria, `NO_MEDIBLE` ante la duda, nada de aprobar por
ausencia— no es negociable: es el producto.
