"""Tests del conector de inyeccion de asientos en Xubio (xubio_injector.py).

La API real no tiene contrato confirmado: todo pasa por la interfaz
`InyectorXubio` y hoy la implementacion es un mock. Lo que se prueba es el mapeo
al payload de Xubio y que el mock respete el modo dry-run y numere los ids.
"""

import json
from datetime import date

from app.services import xubio_injector
from app.services.asientos_ajuste import AsientoAjuste, LineaAsiento


def _asiento() -> AsientoAjuste:
    return AsientoAjuste(
        numero=1,
        fecha=date(2026, 7, 5),
        origen="banco",
        concepto="COMISION",
        lineas=[
            LineaAsiento("Comisiones", "COMISION", debe=150.0, cuenta_codigo="5.1.01", rol="contracuenta"),
            LineaAsiento("Banco", "COMISION", haber=150.0, cuenta_codigo="1.1.01", rol="banco"),
        ],
    )


def test_mapear_payload_arma_fecha_descripcion_y_detalle():
    payload = xubio_injector.mapear_payload(_asiento())
    assert payload["fecha"] == "2026-07-05"
    assert "COMISION" in payload["descripcion"]
    assert len(payload["detalle"]) == 2
    assert payload["detalle"][0][xubio_injector.CLAVE_CUENTA] == "5.1.01"
    assert payload["detalle"][0]["debe"] == 150.0
    assert payload["detalle"][1]["haber"] == 150.0


def test_mapear_payload_usa_el_nombre_si_no_hay_codigo():
    asiento = _asiento()
    for linea in asiento.lineas:
        linea.cuenta_codigo = ""
    payload = xubio_injector.mapear_payload(asiento)
    assert payload["detalle"][0][xubio_injector.CLAVE_CUENTA] == "Comisiones"


def test_mock_en_dry_run_no_llama_a_xubio(monkeypatch, tmp_path):
    monkeypatch.setattr(xubio_injector, "RUTA_AUDITORIA", tmp_path / "auditoria.jsonl")
    inyector = xubio_injector.InyectorXubioMock(dry_run=True)

    resultado = inyector.inyectar(_asiento())

    assert resultado.estado == "dry_run"
    assert resultado.xubio_id is None
    assert resultado.payload["detalle"]


def test_mock_sin_dry_run_numera_los_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(xubio_injector, "RUTA_AUDITORIA", tmp_path / "auditoria.jsonl")
    inyector = xubio_injector.InyectorXubioMock(dry_run=False)

    resultados = inyector.inyectar_lote([_asiento(), _asiento()])

    assert [r.estado for r in resultados] == ["inyectado", "inyectado"]
    assert [r.xubio_id for r in resultados] == [1, 2]


def test_el_mock_deja_una_linea_de_auditoria_por_intento(monkeypatch, tmp_path):
    ruta = tmp_path / "auditoria.jsonl"
    monkeypatch.setattr(xubio_injector, "RUTA_AUDITORIA", ruta)
    inyector = xubio_injector.InyectorXubioMock(dry_run=True)

    inyector.inyectar(_asiento())

    lineas = ruta.read_text(encoding="utf-8").strip().splitlines()
    assert len(lineas) == 1
    registro = json.loads(lineas[0])
    assert registro["asiento_numero"] == 1
    assert registro["resultado"] == "dry_run"


def test_obtener_inyector_devuelve_el_mock():
    inyector = xubio_injector.obtener_inyector()
    assert isinstance(inyector, xubio_injector.InyectorXubioMock)
