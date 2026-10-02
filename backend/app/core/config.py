from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    API_XUBIO_URL: str
    XUBIO_CLIENT_ID: str
    XUBIO_CLIENT_SECRET: str

    class Config:
        env_file = ".env"

# Instancia global para usar en toda la app
settings = Settings()