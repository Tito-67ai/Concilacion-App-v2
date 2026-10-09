"""Manejo de la sesion web de Xubio para el login de la aplicacion.

El panel de afiliados consulta dos estados:

  * "configurada": el .env ya tiene XUBIO_WEB_TOKEN o XUBIO_WEB_COOKIE, asi que
    los endpoints de afiliados pueden hablar con core.xubio.com.
  * "credenciales": el .env tiene XUBIO_EMAIL y XUBIO_PASSWORD (se guardan
    desde el login de la pantalla, y las usa el bot para renovar la sesion).

POST /xubio/login guarda las credenciales y corre el bot de Playwright con el
navegador visible (headless=False por defecto en XUBIO_BOT_HEADLESS), porque el
login de Visma Connect puede pedir un captcha o una verificacion que se
completa en la misma ventana.
"""

from __future__ import annotations

import logging

from app.core.config import RAIZ_BACKEND, settings
from app.services.sesion_xubio_bot import escribir_env, leer_env, obtener_sesion_xubio

logger = logging.getLogger(__name__)

# Sobreescribible en los tests (monkeypatch) para no tocar el .env real.
RUTA_ENV = RAIZ_BACKEND / ".env"


def estado_sesion() -> dict:
    """Resume si la app ya puede hablar con la web de Xubio."""
    env = leer_env(RUTA_ENV)
    return {
        # Configurada: lo que usa el server para llamar a la web de Xubio.
        "configurada": bool(
            (settings.XUBIO_WEB_TOKEN or "").strip()
            or (settings.XUBIO_WEB_COOKIE or "").strip()
        ),
        # Credenciales: lo que usa el bot para renovar la sesion.
        "credenciales": bool(
            (env.get("XUBIO_EMAIL") or "").strip()
            and (env.get("XUBIO_PASSWORD") or "").strip()
        ),
    }


def guardar_credenciales(email: str, password: str) -> None:
    """Persiste XUBIO_EMAIL / XUBIO_PASSWORD en el .env local."""
    escribir_env({"XUBIO_EMAIL": email, "XUBIO_PASSWORD": password}, RUTA_ENV)


async def renovar_sesion(email: str, password: str, headless: bool) -> dict:
    """Corre el bot, guarda lo capturado en el .env y resume el resultado.

    Devuelve {"token": bool, "cookie": bool}. El bot levanta RuntimeError si
    no logra capturar una sesion valida (p.ej. quedo un paso a mano).
    """
    token, cookie = await obtener_sesion_xubio(
        email=email,
        password=password,
        headless=headless,
        slow_mo=50,
    )
    actualizar: dict[str, str] = {}
    if token:
        actualizar["XUBIO_WEB_TOKEN"] = token
    if cookie:
        actualizar["XUBIO_WEB_COOKIE"] = cookie
    if not actualizar:
        raise RuntimeError(
            "El bot no capturo ni token ni cookie de sesion. Puede que en la "
            "ventana que se abrio haya quedado un paso a mano; reintenta."
        )
    escribir_env(actualizar, RUTA_ENV)
    logger.info(
        "Sesion de Xubio renovada (token=%s cookie=%s)", bool(token), bool(cookie)
    )
    return {"token": bool(token), "cookie": bool(cookie)}


def cerrar_sesion(olvidar_credenciales: bool = False) -> dict:
    """Olvida la sesion web de Xubio (token/cookie) y, opcional, las credenciales.

    Vacia XUBIO_WEB_TOKEN / XUBIO_WEB_COOKIE (y XUBIO_EMAIL / XUBIO_PASSWORD si
    olvidar_credenciales) en el .env y tambien en la config en memoria: el
    cliente de la web lee `settings` en cada request, asi que si solo se tocara
    el archivo el token seguiria vivo hasta reiniciar uvicorn. Devuelve el
    estado de sesion como quedo.
    """
    actualizar: dict[str, str] = {"XUBIO_WEB_TOKEN": "", "XUBIO_WEB_COOKIE": ""}
    if olvidar_credenciales:
        actualizar["XUBIO_EMAIL"] = ""
        actualizar["XUBIO_PASSWORD"] = ""
    escribir_env(actualizar, RUTA_ENV)
    settings.XUBIO_WEB_TOKEN = ""
    settings.XUBIO_WEB_COOKIE = ""
    logger.info(
        "Sesion de Xubio cerrada (credenciales olvidadas=%s)", olvidar_credenciales
    )
    return estado_sesion()