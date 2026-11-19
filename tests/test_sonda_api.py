"""Sonda `api.openapi-documentada` (N07): sujeto = operación."""
from __future__ import annotations

from baremo.model import Alcance, Veredicto
from baremo.scoring import puntuar
from conftest import medir, por_sujeto, texto_de

API = "api.openapi-documentada"

SPEC = """openapi: 3.0.3
info: {title: Facturas, version: 1.0.0}
paths:
  /facturas:
    get:
      summary: Lista las facturas del periodo
      parameters:
        - {name: periodo, in: query, schema: {type: string}}
      responses:
        "200":
          description: Facturas encontradas
          content:
            application/json:
              schema: {$ref: "#/components/schemas/Facturas"}
    post:
      summary: Registra una factura
      requestBody:
        content:
          application/json:
            schema: {$ref: "#/components/schemas/Factura"}
      responses:
        "201": {$ref: "#/components/responses/Creada"}
  /facturas/{id}:
    parameters:
      - {name: id, in: path, required: true, schema: {type: string}}
    delete:
      summary: Cancela una factura
      responses:
        "204": {description: Cancelada}
    patch:
      responses:
        "200": {description: Actualizada}
components:
  schemas:
    Factura: {type: object}
    Facturas: {type: array, items: {$ref: "#/components/schemas/Factura"}}
  responses:
    Creada:
      description: Factura creada
      content:
        application/json:
          schema: {$ref: "#/components/schemas/Factura"}
"""


def test_un_subcheck_por_operacion_y_el_cumplimiento_es_el_porcentaje(repo) -> None:
    check = medir(API, repo({"api/openapi.yaml": SPEC}))
    veredictos = por_sujeto(check)
    assert veredictos == {
        "demo/operacion:api/openapi.yaml#GET /facturas": Veredicto.CUMPLE,
        "demo/operacion:api/openapi.yaml#POST /facturas": Veredicto.CUMPLE,
        "demo/operacion:api/openapi.yaml#DELETE /facturas/{id}": Veredicto.CUMPLE,
        "demo/operacion:api/openapi.yaml#PATCH /facturas/{id}": Veredicto.NO_CUMPLE,
    }
    nota = puntuar([check], Alcance(declarado=["demo"], medido=["demo"]))
    assert nota.checks[0].cumplimiento == 0.75
    # La operación incompleta dice exactamente qué le falta.
    assert "sin summary ni description" in texto_de(check)
    assert "respuesta 200 sin content ni schema" in texto_de(check)


def test_swagger_2_respuesta_sin_schema_no_cumple(repo) -> None:
    swagger = """{"swagger": "2.0", "info": {"title": "x", "version": "1"},
 "paths": {"/pagos": {"get": {"summary": "Pagos", "parameters": [{"name": "q", "in": "query"}],
   "responses": {"200": {"description": "ok"}}}}}}"""
    check = medir(API, repo({"swagger.json": swagger}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE
    assert "parámetro «q» sin type" in texto_de(check)
    assert "respuesta 200 sin schema" in texto_de(check)


def test_referencia_a_otro_archivo_del_repo_se_resuelve(repo) -> None:
    spec = """openapi: 3.1.0
info: {title: x, version: "1"}
paths:
  /ping:
    get:
      description: Latido
      responses:
        "200": {$ref: "comunes.yaml#/Ok"}
"""
    comunes = "Ok:\n  description: Vivo\n  content:\n    text/plain:\n      schema: {type: string}\n"
    check = medir(API, repo({"openapi.yaml": spec, "comunes.yaml": comunes}))
    assert check.subchecks[0].veredicto is Veredicto.CUMPLE


def test_referencia_externa_hace_no_medible_la_operacion(repo) -> None:
    spec = """openapi: 3.0.0
info: {title: x, version: "1"}
paths:
  /ping:
    get:
      summary: Latido
      responses:
        "200": {$ref: "https://ejemplo.invalid/comunes.yaml#/Ok"}
"""
    check = medir(API, repo({"openapi.yaml": spec}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE
    assert "destino externo" in check.subchecks[0].motivo


def test_especificacion_invalida_es_no_medible(repo) -> None:
    check = medir(API, repo({"openapi.yaml": "openapi: 3.0.0\npaths: [\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE


def test_especificacion_sin_operaciones_no_cumple(repo) -> None:
    check = medir(API, repo({"openapi.yaml": "openapi: 3.0.0\ninfo: {title: x, version: '1'}\npaths: {}\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_CUMPLE


def test_api_en_el_codigo_sin_especificacion_no_cumple(repo) -> None:
    servicio = 'from fastapi import FastAPI\napp = FastAPI()\n\n@app.get("/facturas")\ndef listar():\n    return []\n'
    check = medir(API, repo({"src/servicio.py": servicio}))
    assert por_sujeto(check) == {"demo/api:contrato": Veredicto.NO_CUMPLE}
    assert check.subchecks[0].evidencias[0].fuente == "src/servicio.py"


def test_rutas_que_solo_viven_en_pruebas_no_son_una_api(repo) -> None:
    prueba = '@app.get("/x")\ndef f():\n    pass\n'
    check = medir(API, repo({"tests/test_cliente.py": prueba, "src/lib.py": "x = 1\n"}))
    assert check.subchecks[0].veredicto is Veredicto.NO_MEDIBLE


def test_repo_sin_api_es_no_medible_y_dice_por_que(repo) -> None:
    check = medir(API, repo({"src/lib.py": "def sumar(a, b):\n    return a + b\n"}))
    assert por_sujeto(check) == {"demo/api:contrato": Veredicto.NO_MEDIBLE}
    assert "no expone API" in check.subchecks[0].motivo
