"""
Tests del login de Xubio desde la aplicacion: estado de sesion y renovacion.

El bot de Playwright no corre aca: renovar_sesion se reemplaza por un fake,
igual que en el resto de la suite no se toca la red. El .env tampoco: las
funciones del servicio escriben en RUTA_ENV, que estos tests apuntan a un
archivo temporal de prueba, nunca al .env real del backend.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.services import sesion_xubio as servicio_sesion

cliente_test = TestClient(app)


@pytest.fixture
def env_temporal(tmp_path, monkeypatch):
    """Apunta el servicio a un .env de prueba en vez del real del backend."""
    env = tmp_path / ".env"
    env.write_text(
        "XUBIO_WEB_TOKEN=\nXUBIO_WEB_COOKIE=\n"
        "XUBIO_EMAIL=\nXUBIO_PASSWORD=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(servicio_sesion, "RUTA_ENV", env)
    return env


def test_estado_sesion_sin_nada(env_temporal, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")

    respuesta = cliente_test.get("/api/xubio/sesion")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"configurada": False, "credenciales": False}


def test_estado_sesion_con_token_y_credenciales(env_temporal, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    env_temporal.write_text(
        "XUBIO_WEB_TOKEN=\nXUBIO_EMAIL=tito@estudio.com.ar\n"
        "XUBIO_PASSWORD=secreta\n",
        encoding="utf-8",
    )

    respuesta = cliente_test.get("/api/xubio/sesion")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"configurada": True, "credenciales": True}


def test_estado_sesion_cookie_alcanza_sola(env_temporal, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")

    respuesta = cliente_test.get("/api/xubio/sesion")

    assert respuesta.status_code == 200
    assert respuesta.json()["configurada"] is True


def test_login_guarda_credenciales_y_renueva(env_temporal, monkeypatch):
    capturado = {}

    async def renovar_fake(email, password, headless):
        capturado["email"] = email
        capturado["password"] = password
        capturado["headless"] = headless
        return {"token": True, "cookie": False}

    monkeypatch.setattr(servicio_sesion, "renovar_sesion", renovar_fake)

    respuesta = cliente_test.post(
        "/api/xubio/login",
        json={"email": "  tito@estudio.com.ar  ", "password": "secreta"},
    )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"exito": True, "sesion": {"token": True, "cookie": False}}
    # El email se guarda y se manda al bot sin los espacios de los bordes.
    assert capturado == {
        "email": "tito@estudio.com.ar",
        "password": "secreta",
        "headless": False,
    }
    # Las credenciales quedaron en el .env de prueba, escritas con utf-8.
    guardado = env_temporal.read_text(encoding="utf-8")
    assert "XUBIO_EMAIL=tito@estudio.com.ar" in guardado
    assert "XUBIO_PASSWORD=secreta" in guardado


def test_login_guarda_lo_que_capturo_el_bot(env_temporal, monkeypatch):
    async def renovar_fake(email, password, headless):
        return {"token": True, "cookie": True}

    monkeypatch.setattr(servicio_sesion, "renovar_sesion", renovar_fake)

    respuesta = cliente_test.post(
        "/api/xubio/login",
        json={"email": "a@b.com", "password": "x"},
    )

    assert respuesta.status_code == 200
    guardado = env_temporal.read_text(encoding="utf-8")
    # escribir_env reemplaza la linea en su lugar, sin duplicarla.
    assert sum(1 for l in guardado.splitlines() if l.startswith("XUBIO_WEB_COOKIE=")) == 1


def test_login_cuando_el_bot_falla_devuelve_502(env_temporal, monkeypatch):
    async def renovar_fake(email, password, headless):
        raise RuntimeError("el login pidio un link por email")

    monkeypatch.setattr(servicio_sesion, "renovar_sesion", renovar_fake)

    respuesta = cliente_test.post(
        "/api/xubio/login",
        json={"email": "a@b.com", "password": "x"},
    )

    assert respuesta.status_code == 502
    assert "No se pudo renovar la sesión de Xubio" in respuesta.json()["detail"]


def test_login_sin_credenciales_devuelve_400(env_temporal):
    respuesta = cliente_test.post("/api/xubio/login", json={"email": "  ", "password": ""})

    assert respuesta.status_code == 400
    # No llego a escribir nada en el .env ni a correr el bot.
    assert "XUBIO_EMAIL=" in env_temporal.read_text(encoding="utf-8")
    assert "XUBIO_EMAIL=tito" not in env_temporal.read_text(encoding="utf-8")


def test_salir_de_xubio_borra_token_y_cookie_sin_tocar_credenciales(env_temporal, monkeypatch):
    env_temporal.write_text(
        "XUBIO_WEB_TOKEN=309-token\nXUBIO_WEB_COOKIE=sesion=abc\n"
        "XUBIO_EMAIL=tito@estudio.com.ar\nXUBIO_PASSWORD=secreta\n",
        encoding="utf-8",
    )
    # La sesion arranca activa en memoria, como si uvicorn hubiera leido el .env.
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")

    respuesta = cliente_test.delete("/api/xubio/sesion")

    assert respuesta.status_code == 200
    # Sin sesion pero con las credenciales: el login puede renovar de nuevo.
    assert respuesta.json() == {"configurada": False, "credenciales": True}
    guardado = env_temporal.read_text(encoding="utf-8")
    # Las claves de sesion quedaron vacias en su lugar (sin duplicar lineas) y
    # las credenciales intactas.
    assert "XUBIO_WEB_TOKEN=\n" in guardado
    assert "XUBIO_WEB_COOKIE=\n" in guardado
    assert "XUBIO_EMAIL=tito@estudio.com.ar" in guardado
    # El cliente lee la config en cada request: tambien se vacio en memoria, no
    # hace falta reiniciar uvicorn para que el 503 de afiliados vuelva.
    assert config.settings.XUBIO_WEB_TOKEN == ""
    assert config.settings.XUBIO_WEB_COOKIE == ""


def test_cerrar_sesion_olvida_tambien_las_credenciales(env_temporal, monkeypatch):
    env_temporal.write_text(
        "XUBIO_WEB_TOKEN=309-token\nXUBIO_WEB_COOKIE=sesion=abc\n"
        "XUBIO_EMAIL=tito@estudio.com.ar\nXUBIO_PASSWORD=secreta\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")

    respuesta = cliente_test.delete("/api/xubio/sesion?olvidar_credenciales=true")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"configurada": False, "credenciales": False}
    guardado = env_temporal.read_text(encoding="utf-8")
    # Las credenciales ya no estan; las claves quedaron vacias en su lugar.
    assert "XUBIO_EMAIL=tito" not in guardado
    assert "XUBIO_PASSWORD=secreta" not in guardado
    assert "XUBIO_EMAIL=" in guardado
    assert "XUBIO_PASSWORD=" in guardado
    assert config.settings.XUBIO_WEB_TOKEN == ""