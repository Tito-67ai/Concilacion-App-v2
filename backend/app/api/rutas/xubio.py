import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.models.schemas import (
    Afiliado,
    MovimientoBancario,
    SolicitudClasificarMayor,
    SolicitudCruceAfiliados,
    SolicitudLoginXubio,
)
from app.services import sesion_xubio as servicio_sesion
from app.services.conciliador import conciliar_movimientos
from app.services.cruce_afiliados import cruzar_movimientos_con_afiliados
from app.services.xubio_client import XubioClient, XubioNoConfigurado
from app.services.xubio_web_client import XubioWebClient, XubioWebNoConfigurado

logger = logging.getLogger(__name__)

router = APIRouter()

# Una instancia por proceso: solo guarda la URL y arma los headers.
cliente_api = XubioClient()
cliente_web = XubioWebClient()


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


async def _descargar_afiliados() -> list[dict]:
    """Baja la lista completa de afiliados desde la web de Xubio.

    Separado del manejo de errores para que los dos endpoints de abajo lo
    compartan. Sin XUBIO_WEB_COOKIE el cliente no hace ninguna llamada y aca
    se responde 503: no se inventan datos.
    """
    try:
        return await cliente_web.obtener_afiliados()
    except XubioWebNoConfigurado as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("No se pudo consultar la API web de Xubio")
        raise HTTPException(
            status_code=502, detail=f"No se pudo consultar la API web de Xubio: {e}"
        )


@router.get("/afiliados")
async def listar_afiliados():
    """
    Descarga la lista completa de clientes/afiliados desde la web de Xubio.

    El backend pagina solo las paginas que haga falta (findAllPaginado trae
    de a 20). Sin XUBIO_WEB_COOKIE en el .env responde 503 y no llama a
    nadie.
    """
    crudo = await _descargar_afiliados()
    try:
        afiliados = [Afiliado.model_validate(c) for c in crudo]
    except Exception as e:
        logger.exception("La web de Xubio devolvio afiliados que no entiende el schema")
        raise HTTPException(
            status_code=502, detail=f"Xubio devolvio datos inesperados: {e}"
        )
    return {"exito": True, "cantidad": len(afiliados), "datos": afiliados}


def _cantidad_libro_mayor(datos) -> Optional[int]:
    """Cuenta las filas del JSON crudo de la grilla del reporte sin asumir su
    forma exacta: ya sea una lista o un dict con la lista en "data"."""
    if isinstance(datos, list):
        return len(datos)
    if isinstance(datos, dict) and isinstance(datos.get("data"), list):
        return len(datos["data"])
    return None


@router.get("/libro-mayor")
async def descargar_libro_mayor(
    desde: Optional[str] = Query(
        None, description="Fecha inicial (YYYY-MM-DD). Por defecto, hace 30 dias."
    ),
    hasta: Optional[str] = Query(
        None, description="Fecha final (YYYY-MM-DD). Por defecto, hoy."
    ),
):
    """
    Baja el Libro Mayor por la sesion web de Xubio (webreport), no por la API
    oficial.

    Es el mismo POST XML que arma el frontend web con el Bearer/cookie que
    captura el bot de login, asi que funciona aunque la cuenta no tenga
    habilitada la API oficial. El JSON crudo de la grilla se devuelve tal
    cual; el parseo a movimientos (cuando el cruce lo use) vive aca, en el
    backend. Sin credenciales de sesion responde 503 sin llamar a nadie.
    """
    try:
        datos = await cliente_web.obtener_libro_mayor(desde=desde, hasta=hasta)
    except XubioWebNoConfigurado as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("No se pudo bajar el Libro Mayor de la web de Xubio")
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo bajar el Libro Mayor de la web de Xubio: {e}",
        )

    return {
        "exito": True,
        "desde": desde,
        "hasta": hasta,
        "cantidad": _cantidad_libro_mayor(datos),
        "datos": datos,
    }


@router.post("/cruzar-afiliados")
async def cruzar_afiliados(solicitud: SolicitudCruceAfiliados):
    """
    Marca cada movimiento del banco con el afiliado que lo pago.

    Si el frontend manda la lista de afiliados ya descargada, el backend la
    usa y no vuelve a la web de Xubio. Si no, la baja el mismo (y puede
    responder 503 si no hay cookie configurada).
    """
    if not solicitud.movimientos:
        raise HTTPException(
            status_code=400,
            detail="No hay movimientos para cruzar. Cargar primero un extracto.",
        )

    if solicitud.afiliados:
        afiliados = [a.model_dump() for a in solicitud.afiliados]
    else:
        afiliados = await _descargar_afiliados()

    datos = cruzar_movimientos_con_afiliados(solicitud.movimientos, afiliados)
    reconocidos = sum(1 for d in datos if d["afiliado"] is not None)

    return {
        "exito": True,
        "resumen": {
            "afiliados_reconocidos": reconocidos,
            "sin_reconocer": len(datos) - reconocidos,
        },
        "datos": datos,
    }


@router.get("/sesion")
async def estado_de_sesion_xubio():
    """Dice si la app ya tiene sesion de Xubio y/o credenciales guardadas.

    "configurada" = hay XUBIO_WEB_TOKEN o XUBIO_WEB_COOKIE en el .env, asi que
    los endpoints de afiliados pueden hablar con la web. "credenciales" = hay
    XUBIO_EMAIL y XUBIO_PASSWORD, las que usa el bot para renovar la sesion.
    El frontend lo usa para decidir si muestra el login del panel de afiliados.
    """
    return servicio_sesion.estado_sesion()


@router.post("/login")
async def iniciar_sesion_xubio(solicitud: SolicitudLoginXubio):
    """Guarda email/password en el .env y renueva el token de la web de Xubio.

    La renovacion corre el bot de Playwright con el navegador visible en la
    maquina del backend: puede tardar un rato y pedir un captcha o una
    verificacion a mano en esa ventana. Corre en un thread aparte para no
    bloquear el loop de FastAPI mientras tanto.
    """
    email = solicitud.email.strip()
    password = solicitud.password
    if not email or not password:
        raise HTTPException(
            status_code=400, detail="Email y contraseña son obligatorios."
        )

    try:
        servicio_sesion.guardar_credenciales(email, password)
    except Exception as e:
        logger.exception("No se pudieron guardar las credenciales de Xubio")
        raise HTTPException(
            status_code=500, detail=f"No se pudo guardar la configuración: {e}"
        )

    try:
        resultado = await asyncio.to_thread(
            lambda: asyncio.run(
                servicio_sesion.renovar_sesion(
                    email=email,
                    password=password,
                    headless=settings.XUBIO_BOT_HEADLESS,
                )
            )
        )
    except Exception as e:
        logger.exception("No se pudo renovar la sesion de Xubio")
        raise HTTPException(
            status_code=502, detail=f"No se pudo renovar la sesión de Xubio: {e}"
        )

    return {"exito": True, "sesion": resultado}


@router.delete("/sesion")
async def cerrar_sesion_xubio(
    olvidar_credenciales: bool = Query(
        False,
        description=(
            "Ademas de token/cookie, borrar XUBIO_EMAIL y XUBIO_PASSWORD del "
            ".env: la proxima vez hay que tipearlas de nuevo en el login."
        ),
    )
):
    """Olvida la sesion de la web de Xubio de este backend.

    Es el "Salir de Xubio" de la barra superior: vacia XUBIO_WEB_TOKEN y
    XUBIO_WEB_COOKIE en el .env y en memoria, asi los endpoints de afiliados
    vuelven a responder 503 y el panel derecho ofrece el login. Con
    olvidar_credenciales=true (el "Cerrar sesion") tambien borra el
    email/contraseña guardados. No se revoca nada del lado de Xubio: solo se
    olvida la sesion localmente.
    """
    return servicio_sesion.cerrar_sesion(olvidar_credenciales=olvidar_credenciales)


@router.post("/clasificar-mayor")
async def clasificar_mayor(solicitud: SolicitudClasificarMayor):
    """
    Marca cada movimiento del Libro Mayor con el afiliado que le corresponde.

    Es el mismo cruce puro que /cruzar-afiliados pero del lado del mayor: el
    filtro "Empresa" de la bandeja derecha muestra solo los movimientos de un
    afiliado. La normalizacion de nombres y la prioridad del CUIT viven aca,
    no en el frontend. Si el frontend manda la lista ya descargada no se
    vuelve a la web de Xubio; si la manda vacia, se baja (puede responder 503).
    """
    if not solicitud.movimientos:
        raise HTTPException(
            status_code=400,
            detail="No hay movimientos del Libro Mayor para clasificar.",
        )

    if solicitud.afiliados:
        afiliados = [a.model_dump() for a in solicitud.afiliados]
    else:
        afiliados = await _descargar_afiliados()

    datos = cruzar_movimientos_con_afiliados(solicitud.movimientos, afiliados)
    reconocidos = sum(1 for d in datos if d["afiliado"] is not None)

    return {
        "exito": True,
        "resumen": {
            "afiliados_reconocidos": reconocidos,
            "sin_reconocer": len(datos) - reconocidos,
        },
        "datos": datos,
    }