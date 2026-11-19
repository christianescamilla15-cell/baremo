# Seguridad

## Reportar una vulnerabilidad

Escribe a **christianescamilla15@gmail.com** con el asunto «Seguridad: Baremo». Respondo en 72 horas
hábiles y publico el arreglo con su aviso. Por favor no abras un issue público para vulnerabilidades.

## Qué revisa cada cambio

| Revisión | Herramienta | Bloquea |
|---|---|---|
| Análisis estático | CodeQL + Semgrep (`p/default`) | sí (Semgrep) |
| Dependencias, configuración e IaC | Trivy | sí, en CRITICAL/HIGH con arreglo publicado |
| Secretos en toda la historia | gitleaks | sí |
| Datos de terceros | revisión de confidencialidad | sí |
| Inventario de componentes | SBOM (syft, SPDX) | no: se publica con cada versión |
| Madurez del propio repositorio | Baremo sobre sí mismo (`baremo.yml`) | sí, bajo el mínimo o sin cobertura |

Cada revisión debe probar que analizó algo (archivos, paquetes o commits > 0); un reporte vacío
cuenta como fallo. Baremo lo verifica sobre sus propios flujos con la sonda
`entrega.check-que-analiza`.

## Excepciones vigentes

Toda excepción lleva motivo y fecha de vencimiento; vencida, deja de aplicar.

| Excepción | Dónde | Motivo | Vence |
|---|---|---|---|
| Semgrep no analiza `herramientas/verificar_reportes.py` | `.github/workflows/seguridad.yml` | Copia literal de la plantilla común; usa `xml.etree` para leer el JUnit que produce este mismo CI (entrada confiable). El arreglo va en la plantilla. | 2027-02-19 |
| `nosemgrep` en dos importaciones dinámicas de `baremo/cli.py` | el propio código | Importan la constante `PAQUETE_SONDAS` y sus submódulos listados por `pkgutil`: ninguna entrada externa. | revisión en cada cambio de `cli.py` |

Las excepciones de Trivy viven en `.trivyignore`, una por línea, con fecha y motivo.

## Modelo de amenazas y límites conocidos

Baremo **lee** el repositorio evaluado: no ejecuta su código, no instala sus dependencias e
interpreta YAML sólo con `yaml.safe_load`. Sus únicas llamadas a procesos son `git rev-parse` y
`git ls-files` sobre el sujeto. No usa red ni credenciales.

- **No evalúes repositorios no confiables con la salida a la vista de terceros.** Los archivos
  que son enlaces simbólicos se leen siguiendo el enlace, y varias sondas copian al informe un
  extracto de una línea (la primera de la licencia, la línea de un README). Un repositorio
  malicioso podría hacer que el informe muestre la primera línea de un archivo local. Los enlaces
  de Markdown sí se resuelven sólo dentro del sujeto.
- La sonda `seguridad.confidencialidad` nunca escribe en el informe el término encontrado ni la
  línea que lo contiene: sólo archivo, número de línea y número de regla.
