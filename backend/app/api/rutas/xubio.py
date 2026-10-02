from fastapi import APIRouter, HTTPException
from app.services.xubio_client import XubioClient
from app.services.conciliador import conciliar_movimientos
from app.models.schemas import MovimientoBancario

router = APIRouter()
cliente_api = XubioClient()

@router.post("/cruzar-datos")
async def ejecutar_cruce(movimientos_banco: list[MovimientoBancario]):
    try:
        # En producción, Angular debería mandar las fechas en el request
        mov_xubio = await cliente_api.obtener_mayor("2026-10-01", "2026-10-31")
        
        resultado = conciliar_movimientos(movimientos_banco, mov_xubio)
        
        return {
            "exito": True,
            "resumen": {
                "pares_encontrados": len(resultado["conciliados"]),
                "sin_cargar_en_xubio": len(resultado["pendientes_banco"]),
                "no_impactados_en_banco": len(resultado["pendientes_xubio"])
            },
            "tablas": resultado
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))