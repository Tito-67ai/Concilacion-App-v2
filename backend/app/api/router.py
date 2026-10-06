from fastapi import APIRouter

from app.api.rutas import conciliacion, exportar, extractos, xubio

api_router = APIRouter()

# Agrupamos todas las rutas bajo prefijos limpios
api_router.include_router(extractos.router, prefix="/extractos", tags=["Extractos"])
api_router.include_router(xubio.router, prefix="/xubio", tags=["Xubio"])
api_router.include_router(conciliacion.router, prefix="/conciliacion", tags=["Conciliacion"])
api_router.include_router(exportar.router, prefix="/exportar", tags=["Exportar"])