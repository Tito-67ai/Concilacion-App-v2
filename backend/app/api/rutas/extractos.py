import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import RespuestaExtraccion
from app.services.procesador_central import BANCOS, ErrorDeExtraccion, procesar_archivo

logger = logging.getLogger(__name__)

router = APIRouter()

CARPETA_TEMPORALES = os.path.join(tempfile.gettempdir(), "conciliacion_pdfs")


def _borrar(ruta):
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except OSError as e:
        logger.warning("No se pudo borrar el temporal %s: %s", ruta, e)


@router.get("/bancos")
def bancos_soportados():
    """Los extractores registrados, para que el frontend no los adivine."""
    return {"bancos": sorted(BANCOS)}


@router.post("/procesar", response_model=RespuestaExtraccion)
async def procesar_extracto(
    banco: str = Form(...),
    archivo: UploadFile = File(...),
):
    nombre = (archivo.filename or "").strip()
    if not nombre.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="El archivo debe ser un PDF. "
            f"Se recibio: {nombre or '(sin nombre)'}",
        )

    banco_id = (banco or "").upper().strip()
    if banco_id not in BANCOS:
        raise HTTPException(
            status_code=400,
            detail=f"El banco '{banco}' no esta soportado. "
            f"Soportados: {', '.join(sorted(BANCOS))}",
        )

    # Nombre generado por nosotros: el nombre que manda el cliente nunca se usa
    # para armar la ruta, asi que no hay forma de escribir fuera de la carpeta.
    os.makedirs(CARPETA_TEMPORALES, exist_ok=True)
    ruta_temporal = os.path.join(CARPETA_TEMPORALES, f"{uuid.uuid4().hex}.pdf")

    try:
        contenido = await archivo.read()
        if not contenido:
            raise HTTPException(status_code=400, detail="El PDF llega vacio.")
        if not contenido.startswith(b"%PDF"):
            raise HTTPException(
                status_code=400,
                detail="El archivo no es un PDF valido (no empieza con %PDF).",
            )
        with open(ruta_temporal, "wb") as destino:
            destino.write(contenido)
    except HTTPException:
        _borrar(ruta_temporal)
        raise
    except Exception as e:
        _borrar(ruta_temporal)
        logger.exception("Falló guardando el archivo temporal")
        raise HTTPException(status_code=500, detail=f"Error guardando el archivo: {e}")

    try:
        movimientos = procesar_archivo(banco_id=banco_id, ruta_pdf=ruta_temporal)
    except ErrorDeExtraccion as e:
        # El PDF se abrio pero este banco no se pudo leer: es del lado del
        # servidor, no del cliente. Se devuelve el motivo real para que se vea
        # en consola en vez de una tabla vacia sin explicacion.
        logger.error("No se pudo procesar el PDF de %s: %s", banco_id, e)
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error inesperado procesando el PDF de %s", banco_id)
        raise HTTPException(status_code=500, detail=f"Error procesando el PDF: {e}")
    finally:
        # procesar_archivo ya lo borra, pero si falla antes de llegar ahi
        # este finally es el que garantiza que no queden PDFs en el temp.
        _borrar(ruta_temporal)

    if not movimientos:
        logger.warning("El PDF de %s no tiene movimientos", banco_id)

    return RespuestaExtraccion(
        exito=True,
        banco=banco_id,
        cantidad_movimientos=len(movimientos),
        datos=movimientos,
    )