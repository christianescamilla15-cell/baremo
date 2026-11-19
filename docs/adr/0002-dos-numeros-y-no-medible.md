# ADR 0002 · Dos números, NO_MEDIBLE y regla de retención

- Estado: aceptada · Fecha: 2026-08-21 (registrada el 2026-11-19)

## Contexto
Los scorecards de madurez habituales colapsan cada control en pass/warn/fail y promedian lo que no
pudieron medir como advertencia o aprobado. Eso produce tres patologías medibles: corregir 58 de
59 sujetos no mueve la nota, recortar el alcance la sube y retirar un permiso de lectura también
la sube.

## Decisión
- La nota son dos números: **cumplimiento** = conformes / medibles (proporcional, por sub-check)
  y **cobertura** = medibles / (medibles + no medibles + omitidos sin declarar).
- Existe el veredicto `NO_MEDIBLE`: sale del numerador y del denominador del cumplimiento y baja
  la cobertura. Una supresión nunca lo tapa.
- Bajo el umbral de cobertura (0.80 por defecto) el cumplimiento **no se publica** y la CLI sale
  con 2, que ningún pipeline debe leer como éxito.

## Alternativas consideradas
- Un solo número con penalización por lo no medido: mezcla dos preguntas distintas y vuelve a
  esconder cuánto se miró.
- Tratar lo no medible como no conforme: castiga la falta de instrumentación igual que el defecto
  real y empuja a apagar el check.

## Consecuencias
Mirar menos nunca sube la nota. El precio es que un informe puede salir sin cumplimiento publicado,
y eso es intencional. La aritmética vive en `baremo/scoring.py` y sus reglas están en
`docs/reglas.md` con sus pruebas.
