import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.models.schemas import (
    AsientoRespuesta,
    LineaAsientoRespuesta,
    RespuestaAsientos,
    SolicitudExportacion,
)
from app.services import exportador
from app.services.asientos_ajuste import construir_asientos, totales

logger = logging.getLogger(__name__)

router = APIRouter()

TIPO_XLSX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@router.post("/asientos", response_model=RespuestaAsientos)
async def asientos_de_ajuste(solicitud: SolicitudExportacion) -> RespuestaAsientos:
    """Vista previa de los asientos de ajuste de las partidas sin coincidencia.

    Es el mismo calculo que usa el Excel (asientos_ajuste.py): cada partida sin
    par se convierte en un asiento de partida doble con su contracuenta. La
    pantalla lo muestra antes de bajar el papel de trabajo.
    """
    asientos = construir_asientos(solicitud.pendientes_banco, solicitud.pendientes_xubio)
    total_debe, total_haber = totales(asientos)

    return RespuestaAsientos(
        asientos=[
            AsientoRespuesta(
                numero=a.numero,
                fecha=a.fecha,
                origen=a.origen,
                concepto=a.concepto,
                referencia=a.referencia,
                debe=round(a.debe, 2),
                haber=round(a.haber, 2),
                lineas=[
                    LineaAsientoRespuesta(
                        cuenta=l.cuenta,
                        detalle=l.detalle,
                        debe=round(l.debe, 2),
                        haber=round(l.haber, 2),
                    )
                    for l in a.lineas
                ],
            )
            for a in asientos
        ],
        total_debe=total_debe,
        total_haber=total_haber,
    )



@router.post("/conciliacion")
async def exportar_conciliacion(solicitud: SolicitudExportacion):
    """Devuelve el papel de trabajo FO 02-03 con la conciliacion ya resuelta.

    El archivo se arma en el servidor porque aca ya estan openpyxl y la
    plantilla: es la unica forma de conservar el membrete y los formatos de la
    auditoria sin reimplementarlos en el navegador.
    """
    total = (
        len(solicitud.conciliados)
        + len(solicitud.pendientes_banco)
        + len(solicitud.pendientes_xubio)
        + len(solicitud.movimientos_mayor)
        + len(solicitud.movimientos_banco)
    )
    if total == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "No hay nada conciliado para exportar. Hacé el cruce primero o "
                "importá un extracto."
            ),
        )

    try:
        contenido = exportador.exportar(solicitud)
    except FileNotFoundError as e:
        logger.error("Falta la plantilla del papel de trabajo: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception("No se pudo armar el papel de trabajo")
        raise HTTPException(status_code=500, detail=f"No se pudo generar el Excel: {e}")

    nombre = exportador.nombre_archivo(solicitud)

    # El nombre va en un header aparte ademas del filename= del Content-Disposition:
    # si el nombre trae acentos, filename* es lo que los navegadores modernos
    # leen bien. Sin eso, "Conciliación" llega como "ConciliaciÃ³n".
    disposition = f"attachment; filename=\"{nombre}\"; filename*=UTF-8''{quote(nombre)}"

    return Response(
        content=contenido,
        media_type=TIPO_XLSX,
        headers={
            "Content-Disposition": disposition,
            "Content-Length": str(len(contenido)),
        },
    )