from fastapi import APIRouter
from app.api.rutas import extractos

api_router = APIRouter()

# Agrupamos todas las rutas bajo prefijos limpios
api_router.include_router(extractos.router, prefix="/extractos", tags=["Extractos"])