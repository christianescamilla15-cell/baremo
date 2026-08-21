# Baremo

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
git clone https://github.com/<tu-usuario>/baremo.git
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

Perfil del repositorio evaluado. Se busca en la raíz del sujeto salvo que se pase `--config`.
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
observado. Ahí vive la proporcionalidad — 59 pilas son 59 sub-checks, no un semáforo.

Todas las sondas incluidas leen **el repositorio**: árbol de archivos, historia de la rama y
artefactos de configuración versionados. `baremo sondas` lista las que tu instalación registra.

| Eje | Check | Qué evalúa | Sujeto |
|---|---|---|---|
| `procedencia` | `rama-protegida` | La protección de la rama principal está declarada en un artefacto versionado. Sin artefacto legible → `NO_MEDIBLE`, no `NO_CUMPLE`. | rama |
| `procedencia` | `propietarios-de-codigo` | Cada directorio de primer nivel con código está cubierto por una regla de propiedad. | directorio |
| `procedencia` | `commits-con-identificador` | Tasa de commits con identificador de cambio, sobre una **ventana declarada** y contra la rama remota. | commit |
| `procedencia` | `etiquetas-de-version` | Existen etiquetas de versión y la última alcanza la punta de la rama. | repositorio |
| `entrega` | `pipeline-declarado` | La definición del pipeline está versionada en el repositorio. | definición |
| `entrega` | `etapa-de-pruebas` | El pipeline ejecuta la suite; se lee el comando, no el nombre de la etapa. | pipeline |
| `entrega` | `compuerta-antes-de-produccion` | El despliegue a producción exige aprobación o entorno protegido. | pipeline |
| `entrega` | `secretos-por-referencia` | Ningún valor sensible aparece literal en la definición. | pipeline |
| `seguridad` | `sast-en-la-cadena` | Hay una etapa de análisis estático con invocación real de la herramienta. | pipeline |
| `seguridad` | `sca-en-la-cadena` | Hay análisis de composición de dependencias. | pipeline |
| `seguridad` | `gate-bloqueante-por-severidad` | La etapa **detiene** ante severidad crítica: se lee la condición de fallo. Una etapa que sólo reporta es `NO_CUMPLE`. | pipeline |
| `seguridad` | `dependencias-fijadas` | Cada manifiesto tiene archivo de bloqueo y es coherente con él. | manifiesto |
| `iac` | `plantillas-versionadas` | Los recursos de infraestructura viven en plantillas dentro del repositorio. | plantilla |
| `iac` | `etiquetas-obligatorias` | Cada recurso declara las etiquetas del perfil **en la plantilla** (no aplicadas por fuera). | recurso |
| `iac` | `sin-secretos-en-parametros` | Ningún parámetro trae valor por defecto sensible. | parámetro |
| `iac` | `escaneo-declarado` | Existe escaneo de IaC y su veredicto se lee del reporte emitido, no del nombre del paso. | plantilla |
| `pruebas` | `suite-presente` | Existe suite de pruebas para cada paquete con código. | paquete |
| `pruebas` | `suite-en-la-cadena` | La suite se ejecuta en el pipeline, no sólo en la máquina de alguien. | pipeline |
| `pruebas` | `umbral-de-cobertura-declarado` | El umbral de cobertura de código está declarado en configuración versionada. | paquete |
| `operacion` | `runbook-presente` | Existe runbook con procedimiento de operación. | runbook |
| `operacion` | `enlaces-del-runbook` | Los enlaces internos del runbook **resuelven**. Enlaces externos no verificables → `NO_MEDIBLE`. | enlace |

Nótese el patrón que se repite: **sustancia antes que nombre**. Una etapa llamada
`security-scan` no acredita nada; acredita la invocación de la herramienta y la condición que
detiene el pipeline. Y donde la sonda no puede afirmar, dice `NO_MEDIBLE` — que cuesta cobertura,
no cumplimiento.

---

## Escribir tu propia sonda

Una sonda es una función registrada que recibe un contexto y devuelve un `ResultadoCheck`.

```python
"""Sonda de ejemplo: cada paquete con código tiene archivo de licencia."""
from __future__ import annotations

from baremo.model import Evidencia, ResultadoCheck, ResultadoSubcheck, Veredicto
from baremo.probes import Contexto, registrar


@registrar(id="operacion.licencia-por-paquete",
           titulo="Cada paquete distribuible declara su licencia",
           eje="operacion",
           peso=1.0)
def licencia_por_paquete(ctx: Contexto) -> ResultadoCheck:
    check = ResultadoCheck(
        id="operacion.licencia-por-paquete",
        titulo="Cada paquete distribuible declara su licencia",
        eje="operacion",
        peso=1.0,
    )

    paquetes = sorted(ctx.raiz.glob("*/pyproject.toml"))
    if not paquetes:
        # NO se aprueba por ausencia: no encontrar sujetos NO es cumplir.
        check.subchecks.append(ResultadoSubcheck(
            id="operacion.licencia-por-paquete",
            descripcion="No se identificó ningún paquete distribuible en el árbol",
            veredicto=Veredicto.NO_MEDIBLE,
            motivo="sin sujetos: no hay nada que afirmar ni que negar",
            sujeto="repositorio",
        ))
        return check

    for manifiesto in paquetes:
        paquete = manifiesto.parent
        licencia = next(iter(paquete.glob("LICENSE*")), None)
        if licencia is None:
            check.subchecks.append(ResultadoSubcheck(
                id="operacion.licencia-por-paquete",
                descripcion=f"El paquete {paquete.name} no declara licencia",
                veredicto=Veredicto.NO_CUMPLE,
                # La evidencia de una AUSENCIA es dónde se buscó, no un extracto.
                evidencias=[Evidencia(fuente=str(paquete),
                                      detalle="sin archivo LICENSE* en la raíz del paquete")],
                motivo="no existe archivo de licencia",
                sujeto=f"paquete:{paquete.name}",
            ))
            continue

        primera = licencia.read_text(encoding="utf-8").splitlines()[0].strip()
        check.subchecks.append(ResultadoSubcheck(
            id="operacion.licencia-por-paquete",
            descripcion=f"El paquete {paquete.name} declara licencia",
            veredicto=Veredicto.CUMPLE,
            evidencias=[Evidencia(fuente=str(licencia), extracto=primera)],
            sujeto=f"paquete:{paquete.name}",
        ))

    return check
```

Un sub-check por sujeto, evidencia en todos los caminos, y ningún `CUMPLE` que provenga de no
haber encontrado nada. `Evidencia` sin `fuente` lanza `ValueError` en construcción: es más fácil
adjuntar la evidencia que evitarla.

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

## Licencia

MIT. Ver [LICENSE](LICENSE).

Contribuciones: ver [CONTRIBUTING.md](CONTRIBUTING.md). El criterio de diseño que debe respetar
cualquier sonda nueva —evidencia obligatoria, `NO_MEDIBLE` ante la duda, nada de aprobar por
ausencia— no es negociable: es el producto.
