"""
Tests del pipeline del bot de Xubio (bot_xubio.py) y de la resiliencia del
cliente web (reintento ante 401/403).

No se toca la red ni Playwright: el cliente del pipeline se reemplaza por un
fake y el cliente web por un MockTransport, igual que en el resto de la suite.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.services import bot_xubio
from app.services.xubio_web_client import XubioWebClient, XubioWebNoConfigurado

cliente_test = TestClient(app)


def _afiliado(id_, nombre, cuit="", activo=1):
    return {
        "id": id_,
        "organizacionId": id_,
        "organizacionNombre": nombre,
        "cuit": cuit,
        "activo": activo,
        "esProveedor": 0,
    }


def _pagina_unica(contenido):
    return {"content": contenido, "last": True, "totalElements": len(contenido)}


# Una sola fila de webreport con forma real de la grilla de Xubio.
MAYOR_JSON = {
    "data": [
        {
            "p_Fecha": "2026-07-01",
            "descripcion": "Pago a proveedor",
            "debe": 0.0,
            "haber": 1000.0,
        }
    ]
}


class _ClienteFalso:
    """Cliente web de Xubio falso: devuelve lo que le configuren."""

    def __init__(
        self,
        afiliados=None,
        mayor=None,
        error_catalogo=None,
        error_mayor=None,
        demora=0.0,
        **kwargs,
    ):
        self._afiliados = afiliados or []
        self._mayor = mayor if mayor is not None else {}
        self._error_catalogo = error_catalogo
        self._error_mayor = error_mayor
        self._demora = demora
        self.kwargs_mayor = None

    async def obtener_afiliados(self, tamano_pagina=20):
        if self._demora:
            await asyncio.sleep(self._demora)
        if self._error_catalogo:
            raise self._error_catalogo
        return self._afiliados

    async def obtener_libro_mayor(self, **kwargs):
        self.kwargs_mayor = kwargs
        if self._demora:
            await asyncio.sleep(self._demora)
        if self._error_mayor:
            raise self._error_mayor
        return self._mayor


@pytest.fixture
def sesion_ok(monkeypatch):
    """Deja el .env 'configurado' para que el pipeline no intente loguearse."""
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "token-de-prueba")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")


# --------------------------------------------------------------------------
# Cliente web: reintento ante 401/403
# --------------------------------------------------------------------------


async def test_client_401_renueva_y_reintenta(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=vieja")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    llamadas = {"n": 0}
    renovaciones = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            return httpx.Response(401, json={"error": "token vencido"})
        return httpx.Response(200, json=_pagina_unica([_afiliado(1, "UNO", "30-1")]))

    async def renovar():
        renovaciones["n"] += 1

    cliente = XubioWebClient(
        transport=httpx.MockTransport(handler), renovar_sesion=renovar
    )

    afiliados = await cliente.obtener_afiliados()

    assert [a["id"] for a in afiliados] == [1]
    assert llamadas["n"] == 2
    assert renovaciones["n"] == 1


async def test_client_401_sin_callback_propaga(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=vieja")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    cliente = XubioWebClient(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await cliente.obtener_afiliados()


async def test_client_reintenta_como_maximo_dos_veces(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=vieja")
    renovaciones = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={})

    async def renovar():
        renovaciones["n"] += 1

    cliente = XubioWebClient(
        transport=httpx.MockTransport(handler),
        renovar_sesion=renovar,
        max_reintentos=2,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await cliente.obtener_afiliados()

    assert renovaciones["n"] == 2


async def test_client_renovacion_que_falla_es_no_configurado(monkeypatch):
    """Si el 401 viene de un token vencido y la renovacion tambien falla, se
    reporta como 'no configurado' para que el pipeline ofrezca carga manual."""
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=vieja")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    async def renovar():
        raise RuntimeError("no hay credenciales")

    cliente = XubioWebClient(
        transport=httpx.MockTransport(handler), renovar_sesion=renovar
    )

    with pytest.raises(XubioWebNoConfigurado, match="renovar la sesion"):
        await cliente.obtener_afiliados()


# --------------------------------------------------------------------------
# Pipeline: fase 1 (sesion)
# --------------------------------------------------------------------------


async def test_sin_sesion_y_sin_credenciales_es_fallback(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")

    async def renovar_falla():
        raise RuntimeError("sin credenciales guardadas")

    contrato = await bot_xubio.sincronizar(renovar=renovar_falla)

    assert contrato["status"] == bot_xubio.STATUS_FALLBACK_MANUAL
    assert "sin credenciales guardadas" in contrato["error_message"]
    assert contrato["execution_logs"]


async def test_login_exitoso_cuando_no_hay_sesion(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")

    async def renovar_ok():
        return {"token": True, "cookie": False, "empresa": False, "cuenta": False}

    cliente = _ClienteFalso(afiliados=[_afiliado(1, "UNO", "30-1")])

    contrato = await bot_xubio.sincronizar(cliente_web=cliente, renovar=renovar_ok)

    assert contrato["status"] == bot_xubio.STATUS_SUCCESS
    assert any(
        "Autenticacion exitosa" in linea for linea in contrato["execution_logs"]
    )


# --------------------------------------------------------------------------
# Pipeline: fase 2 (catalogo + filtro de activos + cruce por CUIT)
# --------------------------------------------------------------------------


async def test_catalogo_devuelve_solo_activos(sesion_ok):
    cliente = _ClienteFalso(
        afiliados=[
            _afiliado(1, "ACTIVO", "30-1"),
            _afiliado(2, "INACTIVO", "30-2", activo=0),
        ]
    )

    contrato = await bot_xubio.sincronizar(cliente_web=cliente)

    assert contrato["status"] == bot_xubio.STATUS_SUCCESS
    assert [a["nombre"] for a in contrato["afiliados_con_xubio"]] == ["ACTIVO"]
    assert contrato["error_message"] is None


async def test_cruce_por_cuit_devuelve_solo_coincidentes(sesion_ok):
    cliente = _ClienteFalso(
        afiliados=[
            _afiliado(104, "LOGYS", "30-71182812-1"),
            _afiliado(105, "OTRA", "30-99999999-9"),
        ]
    )
    locales = [
        {"id": 1, "organizacionNombre": "LOGYS SOLUTIONS SRL", "cuit": "30-71182812-1"},
        {"id": 2, "organizacionNombre": "SIN XUBIO", "cuit": "20-11111111-1"},
    ]

    contrato = await bot_xubio.sincronizar(
        cliente_web=cliente, afiliados_locales=locales
    )

    assert [a["afiliado_id"] for a in contrato["afiliados_con_xubio"]] == ["1"]
    assert contrato["afiliados_con_xubio"][0]["xubio_cliente_id"] == 104
    assert contrato["afiliados_con_xubio"][0]["nombre"] == "LOGYS SOLUTIONS SRL"


# --------------------------------------------------------------------------
# Pipeline: fases 3 y 4 (fetch + normalizacion del Libro Mayor)
# --------------------------------------------------------------------------


async def test_afiliado_seleccionado_baja_y_normaliza_el_mayor(sesion_ok):
    cliente = _ClienteFalso(
        afiliados=[_afiliado(104, "LOGYS", "30-71182812-1")], mayor=MAYOR_JSON
    )

    contrato = await bot_xubio.sincronizar(
        cliente_web=cliente, afiliado_id="104", desde="2026-07-01", hasta="2026-07-31"
    )

    assert contrato["status"] == bot_xubio.STATUS_SUCCESS
    assert len(contrato["data_mayor_normalizada"]) == 1
    fila = contrato["data_mayor_normalizada"][0]
    assert fila["fecha"] == "2026-07-01"
    assert fila["haber"] == 1000.0
    assert cliente.kwargs_mayor["desde"] == "2026-07-01"
    assert cliente.kwargs_mayor["hasta"] == "2026-07-31"


async def test_afiliado_sin_cuenta_en_xubio_es_fallback(sesion_ok):
    cliente = _ClienteFalso(afiliados=[_afiliado(104, "LOGYS", "30-71182812-1")])

    contrato = await bot_xubio.sincronizar(cliente_web=cliente, afiliado_id="CLI-999")

    assert contrato["status"] == bot_xubio.STATUS_FALLBACK_MANUAL
    assert "no tiene cuenta en Xubio" in contrato["error_message"]


async def test_timeout_del_mayor_es_fallback(sesion_ok, monkeypatch):
    monkeypatch.setattr(bot_xubio, "TIMEOUT_FETCH_SEGUNDOS", 0.05)
    cliente = _ClienteFalso(
        afiliados=[_afiliado(104, "LOGYS", "30-71182812-1")], demora=0.5
    )

    contrato = await bot_xubio.sincronizar(cliente_web=cliente, afiliado_id="104")

    assert contrato["status"] == bot_xubio.STATUS_FALLBACK_MANUAL
    assert "Libro Mayor" in contrato["error_message"]


async def test_error_del_catalogo_es_error(sesion_ok):
    cliente = _ClienteFalso(error_catalogo=RuntimeError("boom"))

    contrato = await bot_xubio.sincronizar(cliente_web=cliente)

    assert contrato["status"] == bot_xubio.STATUS_ERROR
    assert "boom" in contrato["error_message"]


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


def test_ruta_bot_montada():
    rutas = set(app.openapi()["paths"].keys())
    assert "/api/xubio/bot/sincronizar" in rutas


def test_afiliados_del_endpoint_filtra_inactivos(monkeypatch):
    import app.api.rutas.xubio as rutas_xubio

    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_pagina_unica(
                [
                    _afiliado(1, "ACTIVO", "30-1"),
                    _afiliado(2, "INACTIVO", "30-2", activo=0),
                ]
            ),
        )

    monkeypatch.setattr(
        rutas_xubio, "cliente_web", XubioWebClient(transport=httpx.MockTransport(handler))
    )

    respuesta = cliente_test.get("/api/xubio/afiliados")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["cantidad"] == 1
    assert cuerpo["datos"][0]["organizacionNombre"] == "ACTIVO"


def test_endpoint_bot_devuelve_el_contrato(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "token-de-prueba")
    monkeypatch.setattr(
        bot_xubio,
        "XubioWebClient",
        lambda **kw: _ClienteFalso(afiliados=[_afiliado(104, "LOGYS", "30-71182812-1")]),
    )

    respuesta = cliente_test.post("/api/xubio/bot/sincronizar", json={})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "SUCCESS"
    assert cuerpo["afiliados_con_xubio"][0]["xubio_cliente_id"] == 104
    assert cuerpo["data_mayor_normalizada"] == []
    assert cuerpo["execution_logs"]
