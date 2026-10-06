import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.procesador_central import BANCOS

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
    # ng serve agrega 4201, 4202, 4300... cuando el puerto pedido esta ocupado
    # por otro proyecto, y ahi el navegador frenaba la respuesta con un error
    # de CORS que no dice ni media palabra del motivo. Cualquier puerto de
    # localhost sirve igual; un origen que no sea localhost sigue teniendo que
    # estar escrito en CORS_ORIGINS.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition no es un header "seguro" de CORS: si no se declara
    # aca, el navegador lo esconde al JavaScript y el frontend no puede leer el
    # nombre del archivo. El usuario terminaria bajando siempre un
    # "Conciliacion.xlsx" generico en vez del nombre con empresa, banco y
    # periodo que manda el exportador.
    expose_headers=["Content-Disposition", "Content-Length"],
)


@app.get("/")
def home():
    # La lista sale de BANCOS y no de una copia escrita a mano: asi no puede
    # quedar desactualizada cuando se agrega un extractor.
    return {
        "mensaje": "Backend de conciliacion bancaria en FastAPI funcionando",
        "docs": "/docs",
        "bancos_soportados": sorted(BANCOS),
    }


@app.get("/health")
def health():
    return {"estado": "ok"}


app.include_router(api_router, prefix="/api")