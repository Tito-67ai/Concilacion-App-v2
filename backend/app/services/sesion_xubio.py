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

Ademas del token/cookie, el bot detecta la empresa y la cuenta del Libro Mayor;
renovar_sesion guarda todo en el .env Y lo deja vivo en `settings`, para que el
server use la sesion nueva sin reiniciar uvicorn.
"""

from __future__ import annotations

import logging

from app.core.config import RAIZ_BACKEND, settings
from app.services.sesion_xubio_bot import (
    SesionCapturada,
    escribir_env,
    leer_env,
    obtener_sesion_xubio,
)

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

    Devuelve {"token": bool, "cookie": bool, "empresa": bool, "cuenta": bool}.
    El bot levanta RuntimeError si no logra capturar una sesion valida (p.ej.
    quedo un paso a mano).

    Ademas de escribir el .env, actualiza `settings` en memoria: el cliente de
    la web lee la config en cada request, asi que sin esto el token recien
    capturado no servia hasta reiniciar uvicorn (y el panel seguia diciendo
    que no habia sesion).
    """
    capturada = await obtener_sesion_xubio(
        email=email,
        password=password,
        headless=headless,
        slow_mo=50,
    )
    actualizar: dict[str, str] = {}
    if capturada.token:
        actualizar["XUBIO_WEB_TOKEN"] = capturada.token
    if capturada.cookie:
        actualizar["XUBIO_WEB_COOKIE"] = capturada.cookie
    # Los codigos del Libro Mayor solo se reescriben si el bot los detecto: si
    # no, se respeta lo que ya hubiera en el .env.
    if capturada.empresa_report_code:
        actualizar["XUBIO_WEB_EMPRESA_REPORT_CODE"] = capturada.empresa_report_code
    if capturada.cuenta_report_code:
        actualizar["XUBIO_WEB_CUENTA_REPORT_CODE"] = capturada.cuenta_report_code
    if not (capturada.token or capturada.cookie):
        raise RuntimeError(
            "El bot no capturo ni token ni cookie de sesion. Puede que en la "
            "ventana que se abrio haya quedado un paso a mano; reintenta."
        )
    escribir_env(actualizar, RUTA_ENV)

    # Mismo valor que quedo en el .env, pero vivo en el proceso actual.
    if capturada.token:
        settings.XUBIO_WEB_TOKEN = capturada.token
    if capturada.cookie:
        settings.XUBIO_WEB_COOKIE = capturada.cookie
    if capturada.empresa_report_code:
        settings.XUBIO_WEB_EMPRESA_REPORT_CODE = capturada.empresa_report_code
    if capturada.cuenta_report_code:
        settings.XUBIO_WEB_CUENTA_REPORT_CODE = capturada.cuenta_report_code

    logger.info(
        "Sesion de Xubio renovada (token=%s cookie=%s empresa=%s cuenta=%s)",
        bool(capturada.token),
        bool(capturada.cookie),
        bool(capturada.empresa_report_code),
        bool(capturada.cuenta_report_code),
    )
    return {
        "token": bool(capturada.token),
        "cookie": bool(capturada.cookie),
        "empresa": bool(capturada.empresa_report_code),
        "cuenta": bool(capturada.cuenta_report_code),
    }


async def renovar_con_credenciales_guardadas(headless: bool = True) -> dict:
    """Renueva la sesion con el email/password guardados en el .env.

    La usan la fase 1 del pipeline del bot y el reintento automatico del
    cliente web ante un 401/403: en ese momento no hay nadie para tipear las
    credenciales, asi que se leen del .env. Sin credenciales guardadas levanta
    RuntimeError (el pipeline lo traduce a FALLBACK_MANUAL).
    """
    env = leer_env(RUTA_ENV)
    email = (env.get("XUBIO_EMAIL") or "").strip()
    password = env.get("XUBIO_PASSWORD") or ""
    if not email or not password:
        raise RuntimeError(
            "No hay XUBIO_EMAIL / XUBIO_PASSWORD guardadas en el .env: inicia "
            "sesion una vez desde la pantalla de Xubio para poder renovar la "
            "sesion automaticamente."
        )
    return await renovar_sesion(email=email, password=password, headless=headless)


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