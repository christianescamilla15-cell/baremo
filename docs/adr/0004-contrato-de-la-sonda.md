# ADR 0004 · El contrato de la sonda se hace cumplir en el constructor

- Estado: aceptada · Fecha: 2026-11-19

## Contexto
Las reglas de diseño de Baremo (evidencia en todo veredicto, `NO_MEDIBLE` con motivo, nada de
aprobar por ausencia, un sub-check por sujeto) son la diferencia entre una nota auditable y una
opinión. Si dependen de la disciplina de quien escribe cada sonda, la sonda número veinte las
romperá sin que nadie lo note.

## Decisión
- Toda sonda es una clase registrada con `@registrar("<eje>.<check>")` y construye sus sub-checks
  con `subcheck()`, que lanza `ValueError` ante un `CUMPLE`/`NO_CUMPLE` sin evidencia o un
  `NO_MEDIBLE` sin motivo.
- Las sondas que miden elementos (operaciones, reglas, niveles C4, ADR) emiten un sub-check por
  elemento y lo nombran con `sujeto_de()` como `<sujeto>/<tipo>:<nombre>`.
- Pruebas transversales recorren el registro completo: un sujeto ilegible da todo `NO_MEDIBLE` y
  un repositorio vacío no produce ningún `CUMPLE`. Otra prueba exige que el README liste cada sonda.

## Alternativas consideradas
- Sondas como funciones sueltas con metadatos en el decorador: era lo que describía el README de la
  0.1.0, pero el código ya usaba clases y la divergencia pasó desapercibida, que es justo lo que
  esta decisión evita.

## Consecuencias
Una sonda nueva que intente aprobar sin evidencia falla en sus propias pruebas, no en producción.
El nombre del sujeto es estable entre corridas, así que las supresiones y la tendencia funcionan
por elemento.
