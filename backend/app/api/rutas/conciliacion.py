"""
Las dos rutas de la conciliacion que no pasan por la API de Xubio.

La API de Xubio esta reservada a planes superiores al contratado, asi que el
mayor se trae como archivo exportado desde el navegador:

  /mayor    lee ese Libro Mayor (Excel/CSV).
  /cruzar   cruza el extracto contra ese mayor.

El cruce usa el MISMO conciliador que /xubio/cruzar-datos: lo que cambia es de
donde salen los movimientos de la derecha, no como se comparan. Por eso la
respuesta tambien tiene la misma forma, y la pantalla no necesita dos maneras de
leerla. Cuando se contrate la API, /xubio/cruzar-datos sigue ahi.
"""

import logging
import os
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import RespuestaMayor, SolicitudCruce
from app.services.conciliador import conciliar_movimientos
from app.services.importador_mayor import leer_mayor
from app.services.importador_tablas import EXTENSIONES
from app.services.procesador_central import ErrorDeExtraccion, _borrar

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/mayor", response_model=RespuestaMayor)
async def cargar_mayor(archivo: UploadFile = File(...)):
    """
    Lee la contraparte que el usuario exporto a Excel/CSV desde su sistema.

    Se sube igual que un extracto: mismos formatos, misma validacion de
    extension. Lo que cambia es la lectura de las columnas (importador_mayor):
    el archivo puede venir como Libro Mayor (Debe/Haber, el debe es entrada) o
    como Movimientos de CC de Xubio (debito = salida). La convencion se deduce
    de los encabezados y se devuelve para que la pantalla la muestre.
    """
    nombre = archivo.filename or ""
    extension = os.path.splitext(nombre)[1].lower()

    if extension not in EXTENSIONES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"El Libro Mayor se exporta como .xlsx, .xls o .csv, y '{nombre}' "
                "no es ninguno de esos."
            ),
        )

    descriptor, ruta = tempfile.mkstemp(suffix=extension)
    os.close(descriptor)
    try:
        datos = await archivo.read()
        with open(ruta, "wb") as fh:
            fh.write(datos)
        movimientos = leer_mayor(ruta)
    except ErrorDeExtraccion as e:
        # El motivo lo arma el importador con las columnas que encontro: es lo
        # unico que le sirve al usuario para arreglar el archivo.
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("No se pudo leer el Libro Mayor %s", nombre)
        raise HTTPException(status_code=500, detail=f"No se pudo leer el Libro Mayor: {e}")
    finally:
        _borrar(ruta)

    logger.info(
        "Libro Mayor '%s': %d movimientos (convencion %s)",
        nombre,
        len(movimientos.datos),
        movimientos.convencion,
    )
    return {
        "exito": True,
        "cantidad_movimientos": len(movimientos.datos),
        "convencion": movimientos.convencion,
        "datos": movimientos.datos,
    }


@router.post("/cruzar")
def cruzar_contra_mayor(solicitud: SolicitudCruce):
    """
    Cruza el extracto del banco contra el Libro Mayor cargado desde archivo.

    Devuelve lo mismo que /xubio/cruzar-datos: {exito, resumen, tablas}. La
    diferencia es que el mayor viene en el pedido en vez de salir de la API.
    """
    if not solicitud.movimientos_banco:
        raise HTTPException(
            status_code=400,
            detail="No hay movimientos bancarios para cruzar. Cargar primero un extracto.",
        )
    if not solicitud.movimientos_xubio:
        raise HTTPException(
            status_code=400,
            detail="No hay movimientos del Libro Mayor para cruzar. "
            "Cargar primero el mayor con el boton 'Libro Mayor'.",
        )

    try:
        # model_dump y no los modelos: conciliador trabaja con .get(), que los
        # modelos de Pydantic no tienen.
        resultado = conciliar_movimientos(
            solicitud.movimientos_banco,
            [m.model_dump() for m in solicitud.movimientos_xubio],
        )
    except Exception as e:
        logger.exception("Fallo el cruce entre banco y Libro Mayor")
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
