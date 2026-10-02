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