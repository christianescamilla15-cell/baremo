# ADR 0003 · Las sondas sólo leen el repositorio, sin red ni credenciales

- Estado: aceptada · Fecha: 2026-08-21 (registrada el 2026-11-19)

## Contexto
Un evaluador que consulta la nube o la forja necesita credenciales, y con credenciales cambia su
modelo de amenazas: deja de poder correr en cualquier pipeline sin permisos especiales y su
resultado depende de lo que esa credencial alcance a ver, que es justo el defecto (c) que Baremo
existe para cerrar.

## Decisión
Las sondas incluidas leen sólo el árbol de trabajo y la historia local de git (`git ls-files`,
`git rev-parse`). No usan red, no ejecutan código del repositorio evaluado e interpretan YAML con
`yaml.safe_load`. La única dependencia es PyYAML; todo lo demás es biblioteca estándar. Lo que vive
fuera del repositorio (por ejemplo, la protección real de la rama) es `NO_MEDIBLE` con un motivo
que dice qué haría falta.

## Alternativas consideradas
- Consultar la API de la forja con un token de sólo lectura: más preciso para la protección de
  rama, pero acopla la herramienta a una forja y a un secreto.

## Consecuencias
Baremo corre en cualquier máquina o pipeline sin configuración. La protección de rama se declara
como archivo versionado (`.github/rulesets/main.json`) para poder medirla. La sonda de
confidencialidad lee su lista de una variable de entorno o de un archivo local, nunca del
repositorio, y jamás imprime un término.
