# Contribuir a Baremo

Gracias por el interés. Este documento es corto a propósito: lo único largo es el criterio de
diseño, porque es el producto.

---

## Entorno y pruebas

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m unittest discover -s tests -v     # toda la suite
python -m unittest tests.test_scoring -v    # un módulo
```

Dependencias: Python 3.12+, biblioteca estándar y PyYAML. Nada más — ni en el paquete ni en las
pruebas. Una propuesta que agregue una dependencia tiene que justificar por qué el problema no se
resuelve con la estándar; casi siempre se resuelve.

Una contribución se acepta con la suite en verde y con **pruebas nuevas para el comportamiento
nuevo**. Para una sonda, el mínimo es un caso de repositorio conforme, uno no conforme y **uno que
no se puede medir** — el tercero es el que suele faltar y es el que protege la tesis.

---

## Añadir una sonda

1. Crea el módulo en `baremo/probes/` (uno por eje, o uno por sonda si es grande).
2. Declara una clase que herede de `Sonda` y regístrala con `@registrar("<eje>.<check>")`; su
   método `evaluar(ctx)` devuelve un `ResultadoCheck`.
3. Emite **un sub-check por cada sujeto observado**, construido con `subcheck()` (que rechaza un
   veredicto sin evidencia o un `NO_MEDIBLE` sin motivo) y nombrado con `sujeto_de()`.
4. Documenta la sonda en la tabla de `README.md` (eje · sonda · qué evalúa · sujeto); una prueba
   falla si una sonda registrada no aparece ahí.
5. Agrega las pruebas: conforme, no conforme, no medible. Si la sonda materializa una regla de
   negocio, agrégala a `docs/reglas.md` con sus pruebas.

El ejemplo mínimo completo está en la sección «Escribir tu propia sonda» del `README.md`.

Sobre la granularidad: **un sub-check por sujeto, no uno por control**. Es lo que hace que la
puntuación sea proporcional. Si tu sonda emite un solo sub-check para 59 recursos, acabas de
reintroducir el todo-o-nada que Baremo existe para corregir.

---

## Criterio de diseño — no negociable

Cualquier sonda nueva debe respetar estas cuatro reglas. Una propuesta que las rompa se rechaza
aunque el código sea impecable, porque el defecto no estaría en el código.

### 1. Evidencia obligatoria

Todo veredicto lleva al menos una `Evidencia` con `fuente` (ruta, comando, consulta) y, cuando
existe, `extracto` con el fragmento exacto observado. El modelo lo fuerza: `Evidencia` sin
`fuente` lanza `ValueError` en construcción.

La evidencia de una **ausencia** también existe, y es *dónde se buscó*: `fuente` = el directorio o
el archivo inspeccionado, `detalle` = el patrón que no apareció. «No lo encontré» sin decir dónde
buscaste no es medición, es opinión.

Quien lea el reporte debe poder reproducir el veredicto sin ejecutar Baremo.

### 2. `NO_MEDIBLE` ante la duda

Si la sonda no puede **afirmar** el hecho, el veredicto es `NO_MEDIBLE`, con `motivo` escrito. No
`CUMPLE`, no `NO_CUMPLE`.

Va a `NO_MEDIBLE`:

- el artefacto que debería leerse no existe o no es legible;
- el formato no se reconoce y sólo se podría adivinar;
- el hecho depende de un sistema fuera del alcance de la sonda;
- una operación falló (permiso, tiempo agotado, error de análisis).

`NO_MEDIBLE` **no promedia**: sale del numerador y del denominador del cumplimiento y baja la
cobertura. Esto es lo que impide que degradar la instrumentación suba la nota, y por eso no puede
haber un camino en el que un fallo técnico termine disfrazado de veredicto de negocio. Un error de
lectura y un control ausente son cosas distintas y se reportan distinto.

También: un fallo técnico **no es** `NO_CUMPLE`. Reprobar a alguien porque tu sonda no supo leer
el archivo es el mismo defecto con el signo cambiado.

### 3. Nada de aprobar por ausencia

No encontrar sujetos **no es cumplir**. Si la sonda busca pipelines y no hay ninguno, el resultado
es `NO_MEDIBLE` con motivo «sin sujetos», nunca un `CUMPLE` vacío que sume 100 %.

Corolario, **sustancia antes que nombre**: acredita por contenido y usa el nombre como pista, no
como prueba. Una etapa llamada `security-scan` no acredita un escaneo; lo acredita la invocación
de la herramienta y la condición que detiene la cadena. Un archivo llamado `runbook.md` no acredita
un runbook; lo acredita que sus enlaces resuelvan.

Y nada de *fallbacks* por búsqueda de texto que puedan empatar con un artefacto distinto del
buscado: si el artefacto canónico no está, el resultado es ausente, nunca «encontré algo parecido».

### 4. La sonda no decide el alcance

El alcance lo declara el perfil evaluado (`baremo.yml`), no el código de la sonda. En particular:

- **Sin listas de exclusión incrustadas.** Ninguna sonda «se salta» recursos por nombre. Toda
  exención vive en `alcance.excluido` con motivo, o en `supresiones.yml` con vencimiento y
  autorizador.
- **Sin muestreo silencioso.** Si por límites hay que muestrear, el criterio se declara, el
  muestreo es determinista (orden estable o semilla fija) y los sujetos no muestreados se emiten
  como `NO_MEDIBLE`. El reporte tiene que poder decir «10 de 48», no «100 %».
- **Sujetos estables.** El identificador del sujeto (`"<tipo>:<nombre>"`) debe ser el mismo entre
  corridas. Si cambia, la tendencia deja de significar algo y una regresión se lee como un sujeto
  nuevo.
- **Ventanas explícitas.** Toda sonda que mida una tasa declara su ventana temporal y su rama de
  referencia en el perfil, y la imprime. Una tasa sin ventana no es reproducible.

---

## Cambios en el modelo o en la puntuación

`baremo/model.py` y `baremo/scoring.py` son el contrato. Un cambio ahí mueve todas las notas
históricas, así que:

- explica en el PR **qué defecto medido** cierra el cambio, con un ejemplo numérico;
- agrega la prueba que falla antes y pasa después;
- si cambia el catálogo de sondas o la aritmética, sube la versión: las corridas de versiones
  distintas **no se comparan** y el reporte lo estampa para que nadie las grafique juntas.

Un cambio que suba las notas sin que haya cambiado ningún sistema evaluado es, por definición, el
síntoma que Baremo existe para detectar. Si tu PR hace eso, dilo en la descripción y explica por
qué esta vez está bien.

---

## Estilo

- Comentarios y documentación en español; identificadores en español, coherentes con el modelo.
- Tipado en todo lo público (`from __future__ import annotations` en cada módulo).
- Dominio genérico en ejemplos, pruebas y documentación: `<app>`, `<entorno>`, «la organización».
  Nada de nombres de empresas, clientes, proveedores, sistemas internos ni personas — ni en los
  datos de prueba.
- Un commit por cambio lógico, con el porqué en el mensaje. El qué ya está en el diff.

Al contribuir aceptas que tu aportación se publique bajo la licencia MIT del proyecto.
