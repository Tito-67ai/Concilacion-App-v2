import logging
import os
import tempfile
import uuid

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.models.schemas import RespuestaExtraccion
from app.services.extractor_generico import extraer_generico
from app.services.importador_tablas import EXTENSIONES as EXTENSIONES_TABLA
from app.services.importador_tablas import procesar_tabla
from app.services.procesador_central import (
    BANCOS,
    ErrorDeExtraccion,
    _df_to_movimientos,
    procesar_archivo,
)

logger = logging.getLogger(__name__)

router = APIRouter()

CARPETA_TEMPORALES = os.path.join(tempfile.gettempdir(), "conciliacion_pdfs")

# El usuario puede elegir el motor generico a proposito, y ademas se usa de
# rescate cuando el parser del banco no logra leer el PDF. Va aparte de BANCOS
# para no meter un import en el modulo que central importa.
MOTORES_GENERICOS = {"GENERICO": extraer_generico}

# Ultimo recurso cuando el motor generico no puede explicar el fallo.
_MOTOR_GENERICO_FALLIDO = (
    "El motor generico no pudo leer este PDF. Probalo con el motor de tu "
    "banco, o descargalo como Excel/CSV."
)

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
    # Los .xls viejos son un contenedor OLE2, distinto del zip del .xlsx
    ".xls": lambda datos: datos[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
}

DESCRIPCION_CONTENIDO = {
    ".pdf": "un PDF (tiene que empezar con %PDF)",
    ".xlsx": "un Excel .xlsx",
    ".xls": "un Excel .xls (el formato viejo de Office 97)",
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
    return {
        "bancos": sorted(set(BANCOS) | set(MOTORES_GENERICOS)),
        "formatos": sorted(FORMATOS),
    }


def _leer_pdf(banco_id, ruta_pdf):
    """
    Corre el extractor del banco y, si no puede con el PDF, el motor generico.

    Un extractor por banco se rompe con cada cambio del banco: una coma, un
    logo, una columna nueva. Antes de devolver un error (o cero movimientos en
    silencio) se prueba el motor generico, que no depende del banco.
    """
    if banco_id in MOTORES_GENERICOS:
        movimientos, motivo = procesar_generico(ruta_pdf)
        if movimientos is None:
            raise HTTPException(status_code=422, detail=motivo or _MOTOR_GENERICO_FALLIDO)
        return movimientos, "GENERICO"

    fallback_error = None
    try:
        movimientos = procesar_archivo(banco_id=banco_id, ruta_pdf=ruta_pdf)
    except ErrorDeExtraccion as e:
        logger.warning("El parser de %s no pudo leer el PDF: %s", banco_id, e)
        fallback_error = e
        movimientos = None

    if movimientos:
        return movimientos, banco_id

    logger.warning(
        "El parser de %s termino sin movimientos, se prueba el motor generico", banco_id
    )
    rescued, motivo = procesar_generico(ruta_pdf)
    if rescued is None:
        # Si el generico supo decir por que fallo (escaneo, sin filas, fechas sin
        # ano) se muestra eso; si no, el error del parser del banco, que para ese
        # banco puntual suele ser mas claro.
        if motivo:
            raise HTTPException(status_code=422, detail=motivo)
        if fallback_error is not None:
            raise fallback_error
        # Se devuelve una lista vacia y no None: el llamador cuenta los
        # movimientos con len() y un None aca terminaba en un TypeError sin
        # mensaje, que el usuario veia como un 500 opaco.
        logger.error(
            "Ni el parser de %s ni el motor generico leiaron el PDF", banco_id
        )
        return [], banco_id
    logger.info("El motor generico leyo %d movimientos de %s", len(rescued), banco_id)
    return rescued, "GENERICO"


def procesar_generico(ruta_pdf):
    """
    Corre el motor generico sobre el PDF.

    Devuelve (movimientos, motivo_del_fallo). El motivo viene del propio motor y
    explica el caso concreto (PDF escaneado, sin filas, fechas sin ano), que es
    mucho mas util que un "no se pudo leer" generico. Si el fallo no es del
    motor, el motivo es None y le toca al llamador quedarse con el error del
    parser del banco, que explica mejor por que fallo ese caso puntual.
    """
    descriptor, excel_tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(descriptor)

    try:
        ok, resultado = extraer_generico(ruta_pdf, excel_tmp, logger.info)
        if not ok:
            logger.warning("El motor generico tampoco pudo leer el PDF: %s", resultado)
            return None, resultado
        df = pd.read_excel(excel_tmp)
        movimientos = _df_to_movimientos(df, "generico")
        logger.info("Motor generico: %d movimientos", len(movimientos))
        return movimientos, None
    except ErrorDeExtraccion as e:
        logger.exception("El motor generico no pudo armar los movimientos")
        return None, str(e)
    except Exception:
        logger.exception("Fallo el motor generico")
        return None, None
    finally:
        _borrar(excel_tmp)


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
    bancos_aceptados = set(BANCOS) | set(MOTORES_GENERICOS)
    if banco_id not in bancos_aceptados:
        raise HTTPException(
            status_code=400,
            detail=f"El banco '{banco}' no esta soportado. "
            f"Soportados: {', '.join(sorted(bancos_aceptados))}",
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
    motor = banco_id
    try:
        if origen == "pdf":
            movimientos, motor = _leer_pdf(banco_id, ruta_temporal)
        else:
            movimientos = procesar_tabla(banco_id=banco_id, ruta_tabla=ruta_temporal)
    except HTTPException:
        # Los raises de _leer_pdf ya traen su status y su motivo: si llegaran
        # al except Exception de abajo se verian como un 500 sin explicar nada.
        raise
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
        motor=motor,
        cantidad_movimientos=len(movimientos),
        datos=movimientos,
    )
