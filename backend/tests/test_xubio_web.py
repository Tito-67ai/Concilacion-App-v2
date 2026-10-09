"""
Tests del cliente de la API web de Xubio (afiliados) y del cruce de
movimientos con afiliados.

La web de Xubio (core.xubio.com) no es la API oficial: pide la cookie de
sesion del navegador o el token Authorization Bearer de esa misma web, asi
que los tests no tocan la red. El cliente se prueba con MockTransport y el
cruce es una funcion pura.

El JSON de las paginas replica la estructura real de
clientes/findAllPaginado (content/totalElements/totalPages/last) capturada de
la pestana Network.
"""

from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.models.schemas import Afiliado, MovimientoBancario
from app.services.cruce_afiliados import cruzar_movimientos_con_afiliados
from app.services.xubio_web_client import XubioWebClient, XubioWebNoConfigurado

cliente_test = TestClient(app)


def _afiliado(id_, nombre, cuit="", activo=1, **extra):
    return {
        "id": id_,
        "organizacionId": id_,
        "organizacionNombre": nombre,
        "cuit": cuit,
        "categoriaFiscal": "Monotributista",
        "activo": activo,
        "esProveedor": 0,
        **extra,
    }


# Dos paginas de a 2, con la metadata que manda el endpoint de verdad.
PAGINA_0 = {
    "content": [
        _afiliado(5261262, "2GTECH ELECTRONICA S.A.S.", "30-71615408-0"),
        _afiliado(782823, "Carbia Silvia Karina", "23-21820231-4"),
    ],
    "empty": False, "first": True, "last": False, "number": 0,
    "numberOfElements": 2, "size": 2, "totalElements": 3, "totalPages": 2,
    "pageable": {"offset": 0, "pageNumber": 0, "pageSize": 2, "paged": True,
                 "sort": {"empty": False, "sorted": True, "unsorted": False},
                 "unpaged": False},
    "sort": {"empty": False, "sorted": True, "unsorted": False},
}
PAGINA_1 = {
    "content": [_afiliado(1722762, "CHATEAU DEL PORTAL SA", "30-71327670-3")],
    "empty": False, "first": False, "last": True, "number": 1,
    "numberOfElements": 1, "size": 2, "totalElements": 3, "totalPages": 2,
    "pageable": {"offset": 2, "pageNumber": 1, "pageSize": 2, "paged": True,
                 "sort": {"empty": False, "sorted": True, "unsorted": False},
                 "unpaged": False},
    "sort": {"empty": False, "sorted": True, "unsorted": False},
}


# --------------------------------------------------------------------------
# Cliente: cookie y paginacion
# --------------------------------------------------------------------------


def test_sin_credenciales_no_se_hace_la_llamada(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    cliente = XubioWebClient()
    with pytest.raises(XubioWebNoConfigurado, match="XUBIO_WEB_COOKIE"):
        _ = cliente.headers


def test_el_token_bearer_alcanza_sin_cookie(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")

    cliente = XubioWebClient()

    assert cliente.headers["Authorization"] == "Bearer 309-token-de-prueba"
    assert "Cookie" not in cliente.headers


def test_con_cookie_y_token_se_mandan_los_dos(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")

    cliente = XubioWebClient()

    assert cliente.headers["Cookie"] == "sesion=abc"
    assert cliente.headers["Authorization"] == "Bearer 309-token-de-prueba"


def _transport_con_paginas(paginas):
    def handler(request: httpx.Request) -> httpx.Response:
        # .../findAllPaginado/{pagina}/{tamano}
        partes = request.url.path.strip("/").split("/")
        pagina = int(partes[-2])
        return httpx.Response(200, json=paginas[pagina])

    return httpx.MockTransport(handler)


async def test_obtener_afiliados_recorre_todas_las_paginas(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")
    cliente = XubioWebClient(transport=_transport_con_paginas([PAGINA_0, PAGINA_1]))

    afiliados = await cliente.obtener_afiliados(tamano_pagina=2)

    assert [a["id"] for a in afiliados] == [5261262, 782823, 1722762]


# --------------------------------------------------------------------------
# Cliente: Libro Mayor via webreport (POST XML, igual que el navegador)
# --------------------------------------------------------------------------


# La grilla del reporte devuelve un JSON crudo; este replica su forma (una
# lista dentro de "data"). El cliente lo devuelve tal cual.
MAYOR_JSON = {
    "data": [
        {"p_Fecha": "2026-07-01", "descripcion": "Pago a proveedor", "debe": 0.0, "haber": 1000.0},
        {"p_Fecha": "2026-07-02", "descripcion": "Ingreso por alquiler", "debe": 500.0, "haber": 0.0},
    ],
    "total": 2,
}


def _transport_mayor(captura):
    def handler(request: httpx.Request) -> httpx.Response:
        captura["method"] = request.method
        captura["url"] = str(request.url)
        captura["cuerpo"] = request.content.decode("utf-8")
        captura["authorization"] = request.headers.get("authorization")
        captura["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json=MAYOR_JSON)

    return httpx.MockTransport(handler)


async def test_obtener_libro_mayor_arma_el_payload_con_las_fechas(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")
    captura: dict = {}
    cliente = XubioWebClient(transport=_transport_mayor(captura))

    datos = await cliente.obtener_libro_mayor(desde="2026-07-01", hasta="2026-07-31")

    assert datos == MAYOR_JSON
    assert captura["method"] == "POST"
    assert "NXV/webreport/data" in captura["url"]
    assert "LibroMayorNXVWebReportGridLayout" in captura["url"]
    assert captura["authorization"] == "Bearer 309-token-de-prueba"
    assert captura["content_type"].startswith("application/xml")
    assert 'name="p_FechaDesde" value="2026-07-01"' in captura["cuerpo"]
    assert 'name="p_FechaHasta" value="2026-07-31"' in captura["cuerpo"]
    assert 'name="p_EmpresaReportCode" value="29774"' in captura["cuerpo"]


async def test_obtener_libro_mayor_sin_fechas_usa_los_ultimos_30_dias(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")
    captura: dict = {}
    cliente = XubioWebClient(transport=_transport_mayor(captura))

    hoy = date.today().isoformat()
    hace_30 = (date.today() - timedelta(days=30)).isoformat()

    await cliente.obtener_libro_mayor()

    assert f'name="p_FechaDesde" value="{hace_30}"' in captura["cuerpo"]
    assert f'name="p_FechaHasta" value="{hoy}"' in captura["cuerpo"]


async def test_obtener_libro_mayor_sin_credenciales_lanza(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    cliente = XubioWebClient(transport=_transport_mayor({}))

    with pytest.raises(XubioWebNoConfigurado, match="XUBIO_WEB_COOKIE"):
        await cliente.obtener_libro_mayor()


# --------------------------------------------------------------------------
# Cruce movimiento <-> afiliado (funcion pura)
# --------------------------------------------------------------------------


def _mov(fecha, concepto, referencia=None, debe=0.0, haber=0.0, saldo=0.0):
    return MovimientoBancario(
        fecha=fecha, concepto=concepto, referencia=referencia,
        debe=debe, haber=haber, saldo=saldo,
    )


def test_cruce_por_nombre_ignora_mayusculas_y_tildes():
    afiliados = [
        _afiliado(702595, "Compañia Argentina de Marketing Directo S.A.", "")
    ]
    movimientos = [
        _mov(date(2026, 7, 1), "TRANSFERENCIA COMPANIA ARGENTINA DE MARKETING DIRECTO SA")
    ]

    datos = cruzar_movimientos_con_afiliados(movimientos, afiliados)

    assert datos[0]["metodo"] == "nombre"
    assert datos[0]["afiliado"]["id"] == 702595


def test_cruce_por_cuit_manda_por_encima_del_nombre():
    # El texto trae el nombre de otro afiliado y el CUIT de este: el CUIT gana.
    afiliados = [
        _afiliado(5261262, "2GTECH", "30-71615408-0"),
        _afiliado(1722762, "CHATEAU DEL PORTAL SA", "30-71327670-3"),
    ]
    movimientos = [_mov(date(2026, 7, 1), "Pago CUIT 30-71615408-0 CHATEAU DEL PORTAL")]

    datos = cruzar_movimientos_con_afiliados(movimientos, afiliados)

    assert datos[0]["metodo"] == "cuit"
    assert datos[0]["afiliado"]["id"] == 5261262


def test_sin_match_devuelve_none():
    afiliados = [_afiliado(782823, "Carbia Silvia Karina", "23-21820231-4")]
    movimientos = [_mov(date(2026, 7, 1), "Devolucion impuesto nacional")]

    datos = cruzar_movimientos_con_afiliados(movimientos, afiliados)

    assert datos[0]["afiliado"] is None
    assert datos[0]["metodo"] is None


def test_el_nombre_mas_largo_gana_cuando_hay_prefijo_comun():
    afiliados = [
        _afiliado(1, "CONSORCIO CARACAS 4641"),
        _afiliado(2, "CONSORCIO CARACAS 4641 DTO B"),
    ]
    movimientos = [_mov(date(2026, 7, 1), "Transferencia CONSORCIO CARACAS 4641 DTO B")]

    datos = cruzar_movimientos_con_afiliados(movimientos, afiliados)

    assert datos[0]["afiliado"]["id"] == 2


def test_la_salida_queda_alineada_con_los_movimientos():
    afiliados = [_afiliado(5261262, "2GTECH ELECTRONICA", "30-71615408-0")]
    movimientos = [
        _mov(date(2026, 7, 1), "Hola"),
        _mov(date(2026, 7, 2), "Pago 2GTECH ELECTRONICA"),
        _mov(date(2026, 7, 3), "Hola"),
    ]

    datos = cruzar_movimientos_con_afiliados(movimientos, afiliados)

    assert [d["indice"] for d in datos] == [0, 1, 2]
    assert [d["afiliado"] is not None for d in datos] == [False, True, False]


def test_el_cruce_con_afiliados_vacios_no_rompe():
    datos = cruzar_movimientos_con_afiliados(
        [_mov(date(2026, 7, 1), "Algo")], []
    )
    assert datos == [{"indice": 0, "afiliado": None, "metodo": None}]


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


def test_rutas_de_afiliados_montadas():
    from app.main import app

    rutas = set(app.openapi()["paths"].keys())
    assert "/api/xubio/afiliados" in rutas
    assert "/api/xubio/cruzar-afiliados" in rutas
    assert "/api/xubio/clasificar-mayor" in rutas
    assert "/api/xubio/libro-mayor" in rutas


def test_afiliados_sin_credenciales_responde_503(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")

    respuesta = cliente_test.get("/api/xubio/afiliados")

    assert respuesta.status_code == 503


def test_afiliados_con_cookie_devuelve_la_lista_paginada(monkeypatch):
    import app.api.rutas.xubio as rutas_xubio

    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")
    fabrica = _transport_con_paginas([PAGINA_0, PAGINA_1])
    monkeypatch.setattr(
        rutas_xubio, "cliente_web", XubioWebClient(transport=fabrica)
    )

    respuesta = cliente_test.get("/api/xubio/afiliados")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["cantidad"] == 3
    assert [d["id"] for d in cuerpo["datos"]] == [5261262, 782823, 1722762]


def test_afiliados_con_token_solo_devuelve_la_lista_paginada(monkeypatch):
    import app.api.rutas.xubio as rutas_xubio

    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")
    fabrica = _transport_con_paginas([PAGINA_0, PAGINA_1])
    monkeypatch.setattr(
        rutas_xubio, "cliente_web", XubioWebClient(transport=fabrica)
    )

    respuesta = cliente_test.get("/api/xubio/afiliados")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["cantidad"] == 3
    assert [d["id"] for d in cuerpo["datos"]] == [5261262, 782823, 1722762]


def test_libro_mayor_sin_credenciales_responde_503(monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")

    respuesta = cliente_test.get("/api/xubio/libro-mayor")

    assert respuesta.status_code == 503


def test_libro_mayor_baja_por_la_sesion_web(monkeypatch):
    import app.api.rutas.xubio as rutas_xubio

    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token-de-prueba")
    captura: dict = {}
    monkeypatch.setattr(
        rutas_xubio, "cliente_web", XubioWebClient(transport=_transport_mayor(captura))
    )

    respuesta = cliente_test.get(
        "/api/xubio/libro-mayor?desde=2026-07-01&hasta=2026-07-31"
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is True
    assert cuerpo["cantidad"] == 2
    assert cuerpo["desde"] == "2026-07-01"
    assert cuerpo["hasta"] == "2026-07-31"
    assert cuerpo["datos"] == MAYOR_JSON
    # El endpoint bajo el Libro Mayor por la sesion web: el payload llego con
    # las fechas pedidas y el bearer.
    assert 'name="p_FechaDesde" value="2026-07-01"' in captura["cuerpo"]
    assert captura["authorization"] == "Bearer 309-token-de-prueba"


def test_afiliados_toleran_campos_nulos_como_la_web_real(monkeypatch):
    # En vivo la web manda telefono: null (no "" solo) en varios registros y
    # email/localidad/provincia nulos en casi todos: el schema tiene que
    # soportarlo, o el endpoint rompe con 502.
    import app.api.rutas.xubio as rutas_xubio

    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "sesion=abc")
    pagina_real = {
        "content": [
            _afiliado(
                5261262, "2GTECH ELECTRONICA S.A.S.", "30-71615408-0",
                telefono=None, email=None, localidad=None, provincia=None,
            ),
            _afiliado(
                5485949, "AXEL LEONEL PICCININI", "20-40643860-1",
                telefono="", email=None, localidad=None,
            ),
        ],
        "empty": False, "first": True, "last": True,
        "number": 0, "numberOfElements": 2, "size": 20,
        "totalElements": 2, "totalPages": 1,
    }
    fabrica = _transport_con_paginas([pagina_real])
    monkeypatch.setattr(
        rutas_xubio, "cliente_web", XubioWebClient(transport=fabrica)
    )

    respuesta = cliente_test.get("/api/xubio/afiliados")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["cantidad"] == 2
    assert [d["organizacionNombre"] for d in cuerpo["datos"]] == [
        "2GTECH ELECTRONICA S.A.S.",
        "AXEL LEONEL PICCININI",
    ]


def test_cruzar_afiliados_con_lista_ya_descargada_no_toca_la_red():
    movimientos = [
        _mov(date(2026, 7, 1), "Transferencia a 2GTECH ELECTRONICA S.A.S.", haber=1000.0),
        _mov(date(2026, 7, 2), "Pago expensas", debe=500.0),
    ]
    afiliados = [
        Afiliado.model_validate(_afiliado(5261262, "2GTECH ELECTRONICA S.A.S.", "30-71615408-0"))
    ]
    cuerpo = {
        "movimientos": [m.model_dump(mode="json") for m in movimientos],
        "afiliados": [a.model_dump(mode="json") for a in afiliados],
    }

    respuesta = cliente_test.post("/api/xubio/cruzar-afiliados", json=cuerpo)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resumen"] == {"afiliados_reconocidos": 1, "sin_reconocer": 1}
    assert cuerpo["datos"][0]["metodo"] == "nombre"
    assert cuerpo["datos"][0]["afiliado"]["id"] == 5261262
    assert cuerpo["datos"][1]["afiliado"] is None


def test_cruzar_afiliados_sin_movimientos_responde_400():
    respuesta = cliente_test.post(
        "/api/xubio/cruzar-afiliados", json={"movimientos": [], "afiliados": []}
    )
    assert respuesta.status_code == 400


def test_clasificar_mayor_marca_cada_fila_del_mayor_con_su_afiliado():
    """El filtro 'Empresa' de la bandeja derecha sale de aca: cada fila del
    mayor queda con el afiliado que la pago, por nombre o CUIT."""
    movimientos = [
        {"fecha": "01/07/2026", "concepto": "Transferencia a 2GTECH ELECTRONICA S.A.S.",
         "comprobante": "FCA-0001-00000001", "debe": 0.0, "haber": 1000.0},
        {"fecha": "02/07/2026", "concepto": "Pago expensas",
         "comprobante": "FCA-0001-00000002", "debe": 500.0, "haber": 0.0},
    ]
    afiliados = [
        Afiliado.model_validate(_afiliado(5261262, "2GTECH ELECTRONICA S.A.S.", "30-71615408-0"))
    ]
    cuerpo = {
        "movimientos": movimientos,
        "afiliados": [a.model_dump(mode="json") for a in afiliados],
    }

    respuesta = cliente_test.post("/api/xubio/clasificar-mayor", json=cuerpo)

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["resumen"] == {"afiliados_reconocidos": 1, "sin_reconocer": 1}
    assert cuerpo["datos"][0]["metodo"] == "nombre"
    assert cuerpo["datos"][0]["afiliado"]["id"] == 5261262
    assert cuerpo["datos"][1]["afiliado"] is None


def test_clasificar_mayor_acepta_filas_de_pares_conciliados():
    """La bandeja derecha tambien clasifica filas de la pestana de pares: el
    frontend les pone el texto de Xubio en `concepto` (concepto_xubio) y el
    schema descarta los campos de mas que trae un par."""
    movimientos = [
        {"fecha": "2026-07-01", "concepto": "Pago a 2GTECH ELECTRONICA S.A.S.",
         "concepto_banco": "TRANSFERENCIA 2GTECH", "concepto_xubio": "Pago a 2GTECH ELECTRONICA S.A.S.",
         "debe": 1000.0, "haber": 0.0, "saldo": 1000.0, "importe": -1000.0,
         "importe_xubio": -1000.0, "cuadra": True},
    ]
    afiliados = [
        Afiliado.model_validate(_afiliado(5261262, "2GTECH ELECTRONICA S.A.S.", "30-71615408-0"))
    ]
    cuerpo = {
        "movimientos": movimientos,
        "afiliados": [a.model_dump(mode="json") for a in afiliados],
    }

    respuesta = cliente_test.post("/api/xubio/clasificar-mayor", json=cuerpo)

    assert respuesta.status_code == 200
    assert respuesta.json()["datos"][0]["afiliado"]["id"] == 5261262


def test_clasificar_mayor_sin_movimientos_responde_400():
    respuesta = cliente_test.post(
        "/api/xubio/clasificar-mayor", json={"movimientos": [], "afiliados": []}
    )
    assert respuesta.status_code == 400