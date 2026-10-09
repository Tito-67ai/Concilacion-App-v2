from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# La raiz del backend, para encontrar el .env aunque uvicorn se levante de otro lado
RAIZ_BACKEND = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ_BACKEND / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_XUBIO_URL: str = "https://api.xubio.com"

    # Vienen del .env. Se dejan vacios para que la app levante igual, pero el
    # cliente de Xubio no hace ninguna llamada sin ellos.
    XUBIO_CLIENT_ID: str = ""
    XUBIO_CLIENT_SECRET: str = ""

    # API interna del frontend web de Xubio (core.xubio.com), para leer la
    # lista de afiliados. NO es la API oficial: no acepta Basic, autentica con
    # la cookie de sesion del navegador o con el token "Authorization: Bearer"
    # de las peticiones de esa web. Ambas van en el .env local, nunca
    # versionadas (xubio_web_client.py). Con cualquiera de las dos alcanza;
    # sin ninguna, los endpoints de afiliados responden 503 sin llamar a nadie.
    XUBIO_WEB_URL: str = "https://core.xubio.com"
    XUBIO_WEB_COOKIE: str = ""
    XUBIO_WEB_TOKEN: str = ""

    # El bot de sesion (sesion_xubio_bot.py) abre el navegador de Playwright
    # visible por defecto, porque el login de Visma Connect puede pedir captcha
    # o verificacion que se completa a mano en esa ventana. En un server de
    # verdad conviene True (invisible), aunque ahi esos pasos no se pueden
    # completar y el intento falla con un aviso.
    XUBIO_BOT_HEADLESS: bool = False

    # El Angular corre en 4200. Hay que habilitar las dos formas de escribirlo:
    # si se abre http://localhost:4200 el origen es uno, y si se abre
    # http://127.0.0.1:4200 es otro, y el navegador los distingue.
    CORS_ORIGINS: list[str] = [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ]

    # Puerto que espera el frontend. conciliacion.ts llama a http://127.0.0.1:8000
    # de forma directa, sin proxy, asi que el backend tiene que escuchar ahi.
    PUERTO: int = 8000


# Instancia global para usar en toda la app
settings = Settings()