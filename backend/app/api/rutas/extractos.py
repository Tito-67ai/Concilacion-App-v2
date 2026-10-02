import logging
import os
import tempfile
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import RespuestaExtraccion
from app.services.importador_tablas import EXTENSIONES as EXTENSIONES_TABLA
from app.services.importador_tablas import procesar_tabla
from app.services.procesador_central import BANCOS, ErrorDeExtraccion, procesar_archivo

logger = logging.getLogger(__name__)

router = APIRouter()

CARPETA_TEMPORALES = os.path.join(tempfile.gettempdir(), "conciliacion_pdfs")

# El mismo endpoint recibe PDF o Excel/CSV: se decide por la extension y se
# deriva al extractor correspondiente.
FORMATOS = {".pdf": "pdf", **dict.fromkeys(sorted(EXTENSIONES_TABLA), "tabla")}

# Los primeros bytes de cada formato. La extension la manda el cliente, asi que
# se mira el contenido antes de creerle: un .pdf que no arranca con %PDF no es
# un PDF y un .xlsx que no es un zip tampoco se puede abrir.
FIRMAS = {
    ".pdf": lambda datos: datos.startswith(b"%PDF"),
    ".xlsx": lambda datos: datos[:4] in (b"PK\x03\x04", b"PK\x05\x06"),
    ".csv": lambda datos: b"\x00" not in datos[:8192],
}

DESCRIPCION_CONTENIDO = {
    ".pdf": "un PDF (tiene que empezar con %PDF)",
    ".xlsx": "un Excel .xlsx",
    ".csv": "un CSV de texto",
}


def _verificar_contenido(datos, extension, nombre):
    """Chequea que el archivo sea de verdad lo que dice su extension."""
    if not datos:
        raise HTTPException(
            status_code=400,
            detail=f"El archivo '{nombre or '(sin nombre)'}' llega vacio.",
        )

    if not FIRMAS[extension](datos):
        raise HTTPException(
            status_code=400,
            detail=(
                f"El contenido de '{nombre}' no es "
                f"{DESCRIPCION_CONTENIDO[extension]}, apesar de la extension "
                f"{extension}. Si lo exportaste del portal del banco, fijate que "
                f"sea el detalle de movimientos y no otro tipo de reporte."
            ),
        )


def _borrar(ruta):
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except OSError as e:
        logger.warning("No se pudo borrar el temporal %s: %s", ruta, e)


@router.get("/bancos")
def bancos_soportados():
    """Los extractores registrados, para que el frontend no los adivine."""
    return {"bancos": sorted(BANCOS), "formatos": sorted(FORMATOS)}


@router.post("/procesar", response_model=RespuestaExtraccion)
async def procesar_extracto(
    banco: str = Form(...),
    archivo: UploadFile = File(...),
):
    nombre = (archivo.filename or "").strip()
    extension = os.path.splitext(nombre)[1].lower()

    if extension not in FORMATOS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Formato '{extension or '(sin extension)'}' no soportado. "
                f"Se aceptan: {', '.join(sorted(FORMATOS))}. "
                f"Se recibio: {nombre or '(sin nombre)'}"
            ),
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
    ruta_temporal = os.path.join(
        CARPETA_TEMPORALES, f"{uuid.uuid4().hex}{extension}"
    )

    try:
        contenido = await archivo.read()
        _verificar_contenido(contenido, extension, nombre)
        with open(ruta_temporal, "wb") as destino:
            destino.write(contenido)
    except HTTPException:
        _borrar(ruta_temporal)
        raise
    except Exception as e:
        _borrar(ruta_temporal)
        logger.exception("Falló guardando el archivo temporal")
        raise HTTPException(status_code=500, detail=f"Error guardando el archivo: {e}")

    origen = FORMATOS[extension]
    try:
        if origen == "pdf":
            movimientos = procesar_archivo(banco_id=banco_id, ruta_pdf=ruta_temporal)
        else:
            movimientos = procesar_tabla(banco_id=banco_id, ruta_tabla=ruta_temporal)
    except ErrorDeExtraccion as e:
        # El archivo se abrio pero no se pudo leer: es del lado del servidor, no
        # del cliente. Se devuelve el motivo real para que se vea en vez de una
        # tabla vacia sin explicacion.
        logger.error("No se pudo procesar el %s de %s: %s", origen, banco_id, e)
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Error inesperado procesando el %s de %s", origen, banco_id)
        raise HTTPException(status_code=500, detail=f"Error procesando el archivo: {e}")
    finally:
        # procesar_archivo y procesar_tabla ya lo borran, pero si falla antes de
        # llegar ahi este finally es el que garantiza que no queden temporales.
        _borrar(ruta_temporal)

    if not movimientos:
        logger.warning("El %s de %s no tiene movimientos", origen, banco_id)

    return RespuestaExtraccion(
        exito=True,
        banco=banco_id,
        origen=origen,
        cantidad_movimientos=len(movimientos),
        datos=movimientos,
    )
