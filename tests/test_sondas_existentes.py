"""Reglas clave de las cinco sondas de la 0.1.0, que no tenían prueba propia."""
from __future__ import annotations

from baremo.model import Veredicto
from conftest import medir


def _sub(check, id_sub: str):
    return next(s for s in check.subchecks if s.id == id_sub)


def test_secretos_se_buscan_por_valor_no_por_nombre(repo) -> None:
    nombres = "EnableSecretRotation: true\nSECRET_NAME=credencial-de-app\napi_key_name: catalogo\n"
    assert _sub(medir("vcs", repo({"config.yml": nombres})), "VCS_SIN_SECRETOS").veredicto is Veredicto.CUMPLE


def test_una_clave_privada_versionada_no_cumple_y_se_redacta(repo) -> None:
    # Se arma en tiempo de ejecución: el literal no debe existir en el árbol de Baremo.
    pem = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n"
    sub = _sub(medir("vcs", repo({"llave.pem.txt": pem})), "VCS_SIN_SECRETOS")
    assert sub.veredicto is Veredicto.NO_CUMPLE
    assert "MIIEvQ" not in " ".join(e.extracto for e in sub.evidencias)


def test_sin_dockerfile_el_usuario_de_la_imagen_es_no_medible(repo) -> None:
    sub = _sub(medir("entrega", repo({"src/app.py": "x = 1\n"})), "ENT_IMAGEN_NO_ROOT")
    assert sub.veredicto is Veredicto.NO_MEDIBLE


def test_imagen_que_corre_como_root_no_cumple_y_con_usuario_cumple(repo) -> None:
    root = medir("entrega", repo({"Dockerfile": "FROM python:3.12-slim\nUSER root\n"}))
    assert _sub(root, "ENT_IMAGEN_NO_ROOT").veredicto is Veredicto.NO_CUMPLE
    app = medir("entrega", repo({"Dockerfile": "FROM python:3.12-slim\nUSER app\n"}))
    assert _sub(app, "ENT_IMAGEN_NO_ROOT").veredicto is Veredicto.CUMPLE


def test_sin_pipeline_los_checks_que_dependen_de_el_son_no_medibles(repo) -> None:
    check = medir("ci", repo({"README.md": "# x\n"}))
    assert _sub(check, "CI_EXISTE_PIPELINE").veredicto is Veredicto.NO_CUMPLE
    assert {s.veredicto for s in check.subchecks if s.id != "CI_EXISTE_PIPELINE"} == {Veredicto.NO_MEDIBLE}


def test_accion_anclada_a_rama_movil_no_cumple(repo) -> None:
    movil = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@main\n      - run: pytest\n"
    assert _sub(medir("ci", repo({".github/workflows/ci.yml": movil})), "CI_ACCIONES_ANCLADAS").veredicto \
        is Veredicto.NO_CUMPLE
    anclada = movil.replace("@main", "@v4")
    assert _sub(medir("ci", repo({".github/workflows/ci.yml": anclada})), "CI_ACCIONES_ANCLADAS").veredicto \
        is Veredicto.CUMPLE


def test_el_proceso_de_excepciones_se_reconoce_en_espanol(repo) -> None:
    politica = "# Seguridad\n\nCada excepción lleva fecha de vencimiento y quién la autoriza.\n"
    sub = _sub(medir("seguridad", repo({"SECURITY.md": politica})), "SEC_PROCESO_EXCEPCIONES")
    assert sub.veredicto is Veredicto.CUMPLE


def test_una_politica_dentro_de_las_dependencias_no_cuenta(repo) -> None:
    raiz = repo({"node_modules/paquete/SECURITY.md": "# Security\nwaiver\n", "README.md": "# x\n"})
    assert _sub(medir("seguridad", raiz), "SEC_POLITICA").veredicto is Veredicto.NO_CUMPLE
