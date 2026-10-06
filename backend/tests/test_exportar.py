"""Tests del endpoint POST /api/exportar/conciliacion.

Se prueba por HTTP y no llamando a la funcion de la ruta: lo que importa es que
la respuesta sea un xlsx con los headers correctos, porque de eso depende que el
navegador lo baje como archivo y no lo muestre en una pestana.
"""

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(**cambios):
    base = {
        "encabezado": {
            "empresa": "ACME S.A.",
            "banco": "SANT",
            "numero_cuenta": "0001234",
            "periodo": "2026-07",
        },
        "conciliados": [
            {
                "fecha": "2026-07-01",
                "concepto_banco": "COBRO",
                "concepto_xubio": "Factura 1",
                "debe": 0,
                "haber": 1000,
                "saldo": 1000,
                "importe": 1000,
                "categoria": "operativo",
            }
        ],
        "pendientes_banco": [
            {"origen": "banco", "fecha": "2026-07-03", "concepto": "COMISION", "debe": 150, "saldo": 350}
        ],
        "pendientes_xubio": [],
    }
    base.update(cambios)
    return base


def test_devuelve_un_xlsx_que_se_puede_abrir():
    respuesta = client.post("/api/exportar/conciliacion", json=_payload())

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )

    libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
    assert libro["Libro Mayor"]["B5"].value == "ACME S.A."
    assert libro["Libro Mayor"]["B20"].value == "COMISION"


def test_manda_el_nombre_del_archivo_para_que_el_navegador_lo_baje():
    respuesta = client.post("/api/exportar/conciliacion", json=_payload())

    disposicion = respuesta.headers["content-disposition"]
    assert "attachment" in disposicion
    assert 'filename="FO 02-03 ACME S.A. SANT ' in disposicion
    assert ".xlsx" in disposicion

    # Sin filename* el nombre llega con la tilde mojada en algunos navegadores.
    assert "filename*=UTF-8''" in disposicion


def test_una_conciliacion_vacia_da_400_y_no_un_archivo_vacio():
    respuesta = client.post(
        "/api/exportar/conciliacion",
        json=_payload(conciliados=[], pendientes_banco=[], pendientes_xubio=[]),
    )

    assert respuesta.status_code == 400
    # Un Excel vacio pasa la prueba de "se genero el archivo" y deja al usuario
    # con un papel de trabajo de cero filas que no dice por que.
    assert "Content-Disposition" not in respuesta.headers


def test_solo_con_pares_conciliados_tambien_exporta():
    respuesta = client.post(
        "/api/exportar/conciliacion", json=_payload(conciliados=_payload()["conciliados"], pendientes_banco=[])
    )

    assert respuesta.status_code == 200


def test_un_payload_con_importes_basura_da_422():
    respuesta = client.post(
        "/api/exportar/conciliacion",
        json=_payload(
            pendientes_banco=[
                {"fecha": "2026-07-03", "concepto": "X", "debe": "mil", "saldo": 1}
            ]
        ),
    )

    assert respuesta.status_code == 422


def test_una_fecha_que_no_existe_da_422():
    respuesta = client.post(
        "/api/exportar/conciliacion",
        json=_payload(
            pendientes_banco=[
                {"fecha": "2026-02-30", "concepto": "X", "debe": 1, "saldo": 1}
            ]
        ),
    )

    assert respuesta.status_code == 422


def test_una_fecha_en_formato_argentino_se_acepta():
    respuesta = client.post(
        "/api/exportar/conciliacion",
        json=_payload(
            pendientes_banco=[
                {"fecha": "03/07/2026", "concepto": "COMISION", "debe": 150, "saldo": 350}
            ]
        ),
    )

    assert respuesta.status_code == 200
    libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
    assert libro["Libro Mayor"]["B20"].value == "COMISION"


def test_el_ruta_esta_registrada_en_el_documento():
    # El registro se mira en el esquema de OpenAPI y no en app.routes: en la
    # version de FastAPI del proyecto las entradas de los routers incluidos no
    # traen .path, y el esquema es ademas lo que ve el frontend al generarse.
    esquema = app.openapi()

    assert "/api/exportar/conciliacion" in esquema["paths"]
    assert "post" in esquema["paths"]["/api/exportar/conciliacion"]


def test_el_nombre_del_archivo_llega_visible_al_frontend():
    # Content-Disposition no es un header "seguro" de CORS. El frontend corre
    # en otro origen (localhost:4200 contra 127.0.0.1:8000), asi que si el
    # header no aparece en Access-Control-Expose-Headers el navegador se lo
    # esconde al JavaScript y el archivo se baja siempre con el nombre por
    # defecto, aunque el backend mande empresa, banco y periodo.
    respuesta = client.post(
        "/api/exportar/conciliacion",
        json=_payload(),
        headers={"Origin": "http://localhost:4200"},
    )

    assert respuesta.status_code == 200
    expuestos = respuesta.headers["access-control-expose-headers"]
    assert "Content-Disposition" in expuestos


@pytest.mark.parametrize(
    "payload",
    [
        _payload(),
        _payload(conciliados=[], pendientes_banco=[], pendientes_xubio=[]),
    ],
)
def test_no_tira_excepcion_con_payloads_de_los_dos_tamanos(payload):
    # Un error sin manejar en la ruta vuelve 500 con una traza en el log y el
    # usuario ve un error generico en la pantalla.
    respuesta = client.post("/api/exportar/conciliacion", json=payload)

    assert respuesta.status_code in (200, 400)