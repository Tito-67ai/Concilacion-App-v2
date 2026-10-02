import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="API de Conciliacion Bancaria",
    description="Lee extractos bancarios en PDF y los cruza con Xubio.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "mensaje": "Backend de conciliacion bancaria en FastAPI funcionando",
        "docs": "/docs",
        "bancos_soportados": ["BBK", "BBVA", "CMF", "GAL", "HIPO", "ICBC", "MP", "PBA", "RIO", "SUPV"],
    }


@app.get("/health")
def health():
    return {"estado": "ok"}


app.include_router(api_router, prefix="/api")