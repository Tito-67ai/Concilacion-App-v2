"""Pipeline del bot de Xubio: login, catalogo, fetch del mayor y normalizacion.

Orquesta en un solo lugar las cuatro fases del bot de automatizacion:

  * FASE 1 - Autenticacion y captura de sesion: si el .env ya tiene
    XUBIO_WEB_TOKEN / XUBIO_WEB_COOKIE se reusa esa sesion; si no, corre el bot
    de Playwright (sesion_xubio_bot) con las credenciales guardadas y captura
    token + cookie. La sesion se guarda en el .env y en memoria.
  * FASE 2 - Catalogo de afiliados: baja clientes/findAllPaginado por HTTP y
    filtra SOLO los activos. Si el llamador pasa una lista local de afiliados,
    la cruza por CUIT (normalizado, sin guiones) y devuelve unicamente los que
    existen en Xubio (tiene_xubio=True). Sin lista local, todos los activos de
    Xubio se consideran afiliados con Xubio.
  * FASE 3 - Fetch del Libro Mayor por HTTP (webreport), sin archivos en disco.
  * FASE 4 - Normalizacion a la estructura estandar {fecha, documento, cuenta,
    debe, haber, descripcion, organizacion, ...} en memoria.

Resilience Suite:

  * 401/403 -> el cliente web renueva la sesion con las credenciales guardadas
    (misma fase 1) y reintenta la llamada (max 2).
  * Sin sesion / sin credenciales / timeout / afiliado sin cuenta en Xubio ->
    status "FALLBACK_MANUAL" para que la UI ofrezca subir el archivo a mano.
  * Cualquier otra falla -> status "ERROR" con error_message.

Contrato de salida de `sincronizar` (el del prompt):

    {
      "status": "SUCCESS" | "FALLBACK_MANUAL" | "ERROR",
      "afiliados_con_xubio": [...],
      "data_mayor_normalizada": [...],
      "execution_logs": [...],
      "error_message": null | "..."
    }
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import httpx

from app.core.config import settings
from app.services import sesion_xubio as servicio_sesion
from app.services.cruce_afiliados import normalizar_cuit
from app.services.importador_mayor import leer_mayor_desde_json
from app.services.procesador_central import ErrorDeExtraccion
from app.services.xubio_web_client import XubioWebClient, XubioWebNoConfigurado

logger = logging.getLogger(__name__)

# Estados del contrato de salida.
STATUS_SUCCESS = "SUCCESS"
STATUS_FALLBACK_MANUAL = "FALLBACK_MANUAL"
STATUS_ERROR = "ERROR"

# El catalogo puede paginar varias veces; el Libro Mayor es una sola llamada.
# El prompt pide cortar a los 15s y ofrecer carga manual, asi que el fetch del
# mayor se limita a 15s.
TIMEOUT_CATALOGO_SEGUNDOS = 60.0
TIMEOUT_FETCH_SEGUNDOS = 15.0
MAX_REINTENTOS_RENOVACION = 2


class _Bitacora:
    """Lista de logs con sello horario, para `execution_logs` del contrato."""

    def __init__(self) -> None:
        self.lineas: list[str] = []

    def log(self, mensaje: str) -> None:
        self.lineas.append(f"{datetime.now().strftime('%H:%M:%S')} - {mensaje}")
        logger.info(mensaje)


def sesion_configurada() -> bool:
    """True si el .env ya tiene token o cookie de la web de Xubio."""
    return bool(
        (settings.XUBIO_WEB_TOKEN or "").strip()
        or (settings.XUBIO_WEB_COOKIE or "").strip()
    )


def es_activo(afiliado: dict) -> bool:
    """Solo los clientes activos entran al catalogo (activo == 1)."""
    valor = afiliado.get("activo", 1)
    if isinstance(valor, bool):
        return valor
    try:
        return int(valor) == 1
    except (TypeError, ValueError):
        # Sin dato de activo se asume activo: mejor mostrarlo que esconderlo.
        return True


def _entrada_de_xubio(afiliado: dict) -> dict:
    """Contrato de un afiliado que sale de la propia lista de Xubio."""
    return {
        "afiliado_id": str(afiliado.get("id")),
        "nombre": afiliado.get("organizacionNombre") or "",
        "cuit": afiliado.get("cuit") or None,
        "xubio_cliente_id": int(afiliado.get("id")),
        "tiene_xubio": True,
    }


def _cruzar_por_cuit(afiliados_locales: list[dict], activos: list[dict]) -> list[dict]:
    """Cruza la lista local contra Xubio y devuelve solo los que coinciden.

    El CUIT se normaliza sin guiones ni espacios: "30-71615408-0" y
    "30716154080" son el mismo. Los afiliados locales sin CUIT o sin match no
    se devuelven (tiene_xubio=False).
    """
    por_cuit: dict[str, dict] = {}
    for afiliado in activos:
        cuit = normalizar_cuit(afiliado.get("cuit"))
        if cuit:
            por_cuit.setdefault(cuit, afiliado)

    entradas: list[dict] = []
    for local in afiliados_locales:
        cuit = normalizar_cuit(local.get("cuit"))
        encontrado = por_cuit.get(cuit) if cuit else None
        if encontrado is None:
            continue
        entradas.append(
            {
                "afiliado_id": str(
                    local.get("id")
                    or local.get("organizacionId")
                    or local.get("afiliado_id")
                ),
                "nombre": local.get("organizacionNombre")
                or local.get("nombre")
                or "",
                "cuit": local.get("cuit") or None,
                "xubio_cliente_id": int(encontrado.get("id")),
                "tiene_xubio": True,
            }
        )
    return entradas


def _buscar_afiliado(entradas: list[dict], afiliado_id) -> dict | None:
    """Ubica el afiliado seleccionado por su id local o por el id de Xubio."""
    objetivo = str(afiliado_id)
    for entrada in entradas:
        if entrada["afiliado_id"] == objetivo:
            return entrada
    for entrada in entradas:
        if str(entrada["xubio_cliente_id"]) == objetivo:
            return entrada
    return None


def _normalizar_filas_mayor(filas: list[dict]) -> list[dict]:
    """Deja `fecha` como texto ISO (YYYY-MM-DD) en el contrato de salida.

    El importer devuelve la fecha como `date`; el contrato del bot la pide como
    string. El resto de los campos viaja tal cual.
    """
    normalizadas: list[dict] = []
    for fila in filas:
        copia = dict(fila)
        fecha = copia.get("fecha")
        if hasattr(fecha, "isoformat"):
            copia["fecha"] = fecha.isoformat()
        normalizadas.append(copia)
    return normalizadas


async def sincronizar(
    *,
    desde: str | None = None,
    hasta: str | None = None,
    afiliado_id=None,
    organizacion_report_code: str | None = None,
    afiliados_locales: list[dict] | None = None,
    cliente_web: XubioWebClient | None = None,
    renovar=None,
    headless: bool = True,
) -> dict:
    """Corre el pipeline completo y devuelve el contrato de salida.

    `cliente_web` y `renovar` se pueden inyectar en los tests (evitan la red y
    el navegador). `afiliado_id=None` devuelve solo el catalogo; con un afiliado
    seleccionado hace ademas el fetch del Libro Mayor (fases 3 y 4).
    """
    bitacora = _Bitacora()
    contrato: dict = {
        "status": STATUS_SUCCESS,
        "afiliados_con_xubio": [],
        "data_mayor_normalizada": [],
        "execution_logs": bitacora.lineas,
        "error_message": None,
    }

    async def _renovar():
        if renovar is not None:
            return await renovar()
        return await servicio_sesion.renovar_con_credenciales_guardadas(
            headless=headless
        )

    # ---------------------------------------------------------------- FASE 1
    if sesion_configurada():
        bitacora.log("Sesion de Xubio ya configurada: se reusa el token/cookie del .env")
    else:
        bitacora.log("Bot Headless iniciado en segundo plano")
        try:
            capturada = await _renovar()
        except Exception as e:  # noqa: BLE001 - se reporta como fallback
            bitacora.log(f"No se pudo autenticar en Xubio: {e}")
            contrato["status"] = STATUS_FALLBACK_MANUAL
            contrato["error_message"] = str(e)
            return contrato
        if not (capturada.get("token") or capturada.get("cookie")):
            mensaje = "El login no capturo token ni cookie de sesion"
            bitacora.log(mensaje)
            contrato["status"] = STATUS_FALLBACK_MANUAL
            contrato["error_message"] = mensaje
            return contrato
        bitacora.log("Autenticacion exitosa en Xubio. Token y cookies capturados")

    cliente = cliente_web or XubioWebClient(
        renovar_sesion=_renovar, max_reintentos=MAX_REINTENTOS_RENOVACION
    )

    # ---------------------------------------------------------------- FASE 2
    try:
        crudos = await asyncio.wait_for(
            cliente.obtener_afiliados(), timeout=TIMEOUT_CATALOGO_SEGUNDOS
        )
    except (asyncio.TimeoutError, httpx.TimeoutException) as e:
        mensaje = f"Xubio no respondio el catalogo a tiempo: {e}"
        bitacora.log(mensaje)
        contrato["status"] = STATUS_FALLBACK_MANUAL
        contrato["error_message"] = mensaje
        return contrato
    except XubioWebNoConfigurado as e:
        bitacora.log(f"Sin credenciales de la web de Xubio: {e}")
        contrato["status"] = STATUS_FALLBACK_MANUAL
        contrato["error_message"] = str(e)
        return contrato
    except Exception as e:  # noqa: BLE001
        bitacora.log(f"Fallo la consulta del catalogo: {e}")
        contrato["status"] = STATUS_ERROR
        contrato["error_message"] = str(e)
        return contrato

    activos = [a for a in crudos if es_activo(a)]
    bitacora.log(
        f"Catalogo consultado. {len(activos)} de {len(crudos)} clientes activos en Xubio"
    )

    if afiliados_locales:
        entradas = _cruzar_por_cuit(afiliados_locales, activos)
        bitacora.log(
            f"Cruce por CUIT: {len(entradas)} de {len(afiliados_locales)} afiliados "
            "coinciden con cuentas de Xubio"
        )
        contrato["afiliados_con_xubio"] = entradas
    else:
        contrato["afiliados_con_xubio"] = [_entrada_de_xubio(a) for a in activos]

    # ------------------------------------------------------------ FASE 3 y 4
    if afiliado_id is None:
        bitacora.log("Sin afiliado seleccionado: se devuelve el catalogo de afiliados")
        return contrato

    if _buscar_afiliado(contrato["afiliados_con_xubio"], afiliado_id) is None:
        mensaje = f"El afiliado {afiliado_id} no tiene cuenta en Xubio: carga manual"
        bitacora.log(mensaje)
        contrato["status"] = STATUS_FALLBACK_MANUAL
        contrato["error_message"] = mensaje
        return contrato

    try:
        crudo_mayor = await asyncio.wait_for(
            cliente.obtener_libro_mayor(
                desde=desde,
                hasta=hasta,
                organizacion_report_code=organizacion_report_code,
            ),
            timeout=TIMEOUT_FETCH_SEGUNDOS,
        )
    except (asyncio.TimeoutError, httpx.TimeoutException) as e:
        mensaje = f"Xubio no respondio el Libro Mayor en {TIMEOUT_FETCH_SEGUNDOS:.0f}s: {e}"
        bitacora.log(mensaje)
        contrato["status"] = STATUS_FALLBACK_MANUAL
        contrato["error_message"] = mensaje
        return contrato
    except XubioWebNoConfigurado as e:
        bitacora.log(f"Sin credenciales de la web de Xubio: {e}")
        contrato["status"] = STATUS_FALLBACK_MANUAL
        contrato["error_message"] = str(e)
        return contrato
    except httpx.HTTPStatusError as e:
        mensaje = (
            f"Xubio rechazo el Libro Mayor ({e.response.status_code}) incluso "
            "despues de renovar la sesion"
        )
        bitacora.log(mensaje)
        contrato["status"] = STATUS_ERROR
        contrato["error_message"] = mensaje
        return contrato
    except Exception as e:  # noqa: BLE001
        bitacora.log(f"Fallo el fetch del Libro Mayor: {e}")
        contrato["status"] = STATUS_ERROR
        contrato["error_message"] = str(e)
        return contrato

    try:
        lectura = leer_mayor_desde_json(crudo_mayor)
    except ErrorDeExtraccion as e:
        bitacora.log(f"No se pudo normalizar el Libro Mayor: {e}")
        contrato["status"] = STATUS_ERROR
        contrato["error_message"] = str(e)
        return contrato

    contrato["data_mayor_normalizada"] = _normalizar_filas_mayor(lectura.datos)
    bitacora.log(
        f"Fetch del Libro Mayor completado para cliente ID: {afiliado_id} "
        f"({len(lectura.datos)} registros procesados)"
    )
    return contrato
