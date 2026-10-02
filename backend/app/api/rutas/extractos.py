from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.models.schemas import RespuestaExtraccion
from app.services.procesador_central import procesar_archivo
import shutil
import os
import tempfile
import uuid

router = APIRouter()

@router.post("/procesar", response_model=RespuestaExtraccion)
async def procesar_extracto(
    banco: str = Form(...),
    archivo: UploadFile = File(...)
):
    if not archivo.filename or not archivo.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un formato PDF válido.")
    
    # Crear carpeta temporal segura
    temp_dir = os.path.join(tempfile.gettempdir(), "conciliacion_pdfs")
    os.makedirs(temp_dir, exist_ok=True)
    # nombre seguro
    nombre_seguro = f"{uuid.uuid4().hex}.pdf"
    ruta_temporal = os.path.join(temp_dir, nombre_seguro)
    
    try:
        with open(ruta_temporal, "wb") as buffer:
            shutil.copyfileobj(archivo.file, buffer)
    except Exception as e:
        if os.path.exists(ruta_temporal):
            try:
                os.remove(ruta_temporal)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Error guardando archivo temporal: {str(e)}")
        
    try:
        movimientos = procesar_archivo(banco_id=banco, ruta_pdf=ruta_temporal)
        return RespuestaExtraccion(
            exito=True,
            banco=banco.upper(),
            cantidad_movimientos=len(movimientos),
            datos=movimientos
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando el PDF: {str(e)}")
