"""Rutas de la pantalla de revision y aprobacion de asientos de ajuste.

Cierra el circuito de las partidas sin coincidencia (FO 02-03):

  /asientos/proponer  arma la propuesta (asientos + partidas sin asiento) y
                      devuelve las cuentas del plan para elegir en la pantalla.
  /asientos/aprobar   recibe los asientos YA revisados y los inyecta en Xubio a
                      traves de la interfaz `InyectorXubio` (hoy, mock/dry-run).
  /asientos/cuentas   lista las cuentas configuradas, para el desplegable.

La propuesta usa el MISMO `asientos_ajuste.proponer_asientos` que el Excel: la
pantalla no reimplementa la partida doble. La inyeccion pasa por
`xubio_injector.obtener_inyector`, asi que cambiar el mock por el cliente real
no toca este archivo.
"""

import logging

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.models.schemas import (
    AsientoRespuesta,
    CuentaDisponible,
    LineaAsientoRespuesta,
    PartidaTemporalRespuesta,
    RespuestaAprobacionAsientos,
    RespuestaPropuestaAsientos,
    ResultadoAsientoInyectado,
    SolicitudAprobacionAsientos,
    SolicitudExportacion,
)
from app.services.asientos_ajuste import proponer_asientos
from app.services.xubio_injector import obtener_inyector

logger = logging.getLogger(__name__)

router = APIRouter()

# Tolerancia para considerar que la partida doble cierra (un centavo).
TOLERANCIA_BALANCE = 0.005


def _linea_respuesta(linea) -> LineaAsientoRespuesta:
    return LineaAsientoRespuesta(
        cuenta=linea.cuenta,
        cuenta_codigo=linea.cuenta_codigo,
        rol=linea.rol,
        detalle=linea.detalle,
        debe=round(linea.debe, 2),
        haber=round(linea.haber, 2),
    )


def _asiento_respuesta(asiento) -> AsientoRespuesta:
    return AsientoRespuesta(
        numero=asiento.numero,
        fecha=asiento.fecha,
        origen=asiento.origen,
        tipo=asiento.tipo,
        regla=asiento.regla,
        estado=asiento.estado,
        revisar_manual=asiento.revisar_manual,
        concepto=asiento.concepto,
        referencia=asiento.referencia,
        cuit=asiento.cuit,
        debe=round(asiento.debe, 2),
        haber=round(asiento.haber, 2),
        balancea=asiento.balancea,
        lineas=[_linea_respuesta(l) for l in asiento.lineas],
    )


def _partida_respuesta(partida) -> PartidaTemporalRespuesta:
    return PartidaTemporalRespuesta(
        origen=partida.origen,
        tipo=partida.tipo,
        regla=partida.regla,
        fecha=partida.fecha,
        concepto=partida.concepto,
        referencia=partida.referencia,
        importe=round(partida.importe, 2),
        revisar_manual=partida.revisar_manual,
    )


def _cuentas_disponibles() -> list[CuentaDisponible]:
    """Las cuentas configuradas del plan, para elegir como contracuenta."""
    return [
        CuentaDisponible(codigo=settings.CUENTA_BANCO_CODIGO, nombre=settings.CUENTA_BANCO),
        CuentaDisponible(
            codigo=settings.CUENTA_GASTOS_BANCARIOS_CODIGO,
            nombre=settings.CUENTA_GASTOS_BANCARIOS,
        ),
        CuentaDisponible(
            codigo=settings.CUENTA_RETENCIONES_CODIGO,
            nombre=settings.CUENTA_RETENCIONES,
        ),
        CuentaDisponible(
            codigo=settings.CUENTA_CONCILIACION_BANCO_CODIGO,
            nombre=settings.CUENTA_CONCILIACION_BANCO,
        ),
        CuentaDisponible(
            codigo=settings.CUENTA_CONCILIACION_MAYOR_CODIGO,
            nombre=settings.CUENTA_CONCILIACION_MAYOR,
        ),
    ]


@router.post("/proponer", response_model=RespuestaPropuestaAsientos)
def proponer(solicitud: SolicitudExportacion) -> RespuestaPropuestaAsientos:
    """Propone los asientos de ajuste y separa las partidas que no llevan asiento.

    Mismo calculo que la hoja "Asientos de Ajuste" del papel de trabajo. Las
    partidas del mayor y las acreditaciones sin comprobante vuelven en
    `partidas_temporales` para revisarlas a mano.
    """
    asientos, partidas = proponer_asientos(
        solicitud.pendientes_banco, solicitud.pendientes_xubio
    )
    total_debe = round(sum(a.debe for a in asientos), 2)
    total_haber = round(sum(a.haber for a in asientos), 2)

    return RespuestaPropuestaAsientos(
        asientos=[_asiento_respuesta(a) for a in asientos],
        partidas_temporales=[_partida_respuesta(p) for p in partidas],
        total_debe=total_debe,
        total_haber=total_haber,
        balancea=abs(total_debe - total_haber) < TOLERANCIA_BALANCE,
        cuentas_disponibles=_cuentas_disponibles(),
    )


@router.get("/cuentas", response_model=list[CuentaDisponible])
def cuentas() -> list[CuentaDisponible]:
    """Las cuentas configuradas del plan de cuentas, para la pantalla."""
    return _cuentas_disponibles()


@router.post("/aprobar", response_model=RespuestaAprobacionAsientos)
def aprobar(solicitud: SolicitudAprobacionAsientos) -> RespuestaAprobacionAsientos:
    """Aprueba e inyecta los asientos revisados en Xubio.

    Valida que cada asiento cierre (Debe = Haber) antes de mandarlo: un asiento
    desbalanceado se rechaza con 400 y no se inyecta nada. La inyeccion concreta
    la hace `InyectorXubio` (hoy, mock en dry-run por defecto: arma el payload y
    no llama a nadie).
    """
    if not solicitud.asientos:
        raise HTTPException(
            status_code=400,
            detail="No hay asientos para aprobar. Genera la propuesta primero.",
        )

    desbalanceados = [
        a.numero
        for a in solicitud.asientos
        if abs(round(a.debe, 2) - round(a.haber, 2)) >= TOLERANCIA_BALANCE
    ]
    if desbalanceados:
        raise HTTPException(
            status_code=400,
            detail=(
                "Estos asientos no balancean (Debe != Haber) y no se pueden "
                f"inyectar: {desbalanceados}."
            ),
        )

    inyector = obtener_inyector()
    resultados: list[ResultadoAsientoInyectado] = []
    for asiento in solicitud.asientos:
        resultado = inyector.inyectar(asiento)
        resultados.append(
            ResultadoAsientoInyectado(
                numero=resultado.numero,
                estado=resultado.estado,
                xubio_id=resultado.xubio_id,
                error=resultado.error,
                payload=resultado.payload,
            )
        )

    errores = sum(1 for r in resultados if r.estado == "error")
    return RespuestaAprobacionAsientos(
        exito=errores == 0,
        dry_run=getattr(inyector, "dry_run", settings.XUBIO_INJECT_DRY_RUN),
        inyectados=len(resultados) - errores,
        errores=errores,
        resultados=resultados,
    )
