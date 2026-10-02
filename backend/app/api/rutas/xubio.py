import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.schemas import MovimientoBancario
from app.services.conciliador import conciliar_movimientos
from app.services.xubio_client import XubioClient, XubioNoConfigurado

logger = logging.getLogger(__name__)

router = APIRouter()

# Una instancia por proceso: solo guarda la URL y arma los headers.
cliente_api = XubioClient()


@router.post("/cruzar-datos")
async def ejecutar_cruce(
    movimientos_banco: list[MovimientoBancario],
    desde: Optional[str] = Query(
        None, description="Fecha inicial (YYYY-MM-DD). Por defecto, la mas vieja del extracto."
    ),
    hasta: Optional[str] = Query(
        None, description="Fecha final (YYYY-MM-DD). Por defecto, la mas nueva del extracto."
    ),
):
    """
    Cruza los movimientos del banco contra el mayor de Xubio.

    El rango de fechas se saca de los propios movimientos que manda el Angular,
    salvo que se pase desde/hasta por query. Antes estaba fijo en October 2026
    en el codigo, asi que cualquier extracto de otra fecha se cruzaba contra una
    ventana vacia.
    """
    if not movimientos_banco:
        raise HTTPException(
            status_code=400,
            detail="No hay movimientos bancarios para cruzar. "
            "Cargar primero un extracto.",
        )

    fechas = sorted(m.fecha for m in movimientos_banco)
    fecha_desde = desde or fechas[0].isoformat()
    fecha_hasta = hasta or fechas[-1].isoformat()
    logger.info("Cruce contra Xubio de %s a %s", fecha_desde, fecha_hasta)

    try:
        movimientos_xubio = await cliente_api.obtener_mayor(fecha_desde, fecha_hasta)
    except XubioNoConfigurado as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("No se pudo consultar la API de Xubio")
        raise HTTPException(
            status_code=502, detail=f"No se pudo consultar la API de Xubio: {e}"
        )

    if not movimientos_xubio:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Xubio no devolvio movimientos entre {fecha_desde} y {fecha_hasta}. "
                "Revisar el rango de fechas o si la cuenta tiene movimientos."
            ),
        )

    try:
        resultado = conciliar_movimientos(movimientos_banco, movimientos_xubio)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Falló el cruce entre banco y Xubio")
        raise HTTPException(status_code=500, detail=f"Error en el cruce: {e}")

    return {
        "exito": True,
        "resumen": {
            "pares_encontrados": len(resultado["conciliados"]),
            "sin_cargar_en_xubio": len(resultado["pendientes_banco"]),
            "no_impactados_en_banco": len(resultado["pendientes_xubio"]),
        },
        "tablas": resultado,
    }