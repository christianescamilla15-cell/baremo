# ADR 0001 · Registrar las decisiones de arquitectura

- Estado: aceptada · Fecha: 2026-11-19

## Contexto
Las decisiones importantes de Baremo (por qué dos números, por qué existe `NO_MEDIBLE`, por qué las
sondas sólo leen el repositorio) vivían en el README y en los comentarios del código, mezcladas con
la explicación de uso. Quien llega al repositorio no puede distinguir qué es una decisión y qué es
un detalle de implementación.

## Decisión
Cada decisión que cambie la estructura, una dependencia mayor, la aritmética de la nota o el
contrato de las sondas se registra como ADR numerado en `docs/adr/`, con estado, contexto,
decisión, alternativas y consecuencias. Baremo verifica sus propios ADR con la sonda
`documentacion.adr`.

## Consecuencias
Quien llegue al repositorio entiende por qué Baremo es como es, no sólo cómo es. Un cambio que
contradiga un ADR aceptado debe reemplazarlo con uno nuevo, y el anterior pasa a «reemplazada».
