"""Tests del endpoint POST /conciliacion/cruzar-avanzado."""

import io
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models.schemas import MovimientoBancario

client = TestClient(app)


def _payload_base():
    return {
        "movimientos_banco": [
            {"fecha": "2026-07-01", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
            {"fecha": "2026-07-02", "concepto": "COMISION", "debe": 150, "haber": 0, "saldo": 850, "referencia": "OP-1"},
        ],
        "movimientos_mayor": [
            {"fecha": "2026-07-01", "comprobante": "FCA-1", "concepto": "Factura 1", "debe": 1000, "haber": 0},
            {"fecha": "2026-07-02", "comprobante": "PAGO", "concepto": "Pago comision", "debe": 0, "haber": 150},
        ],
        "extracto_crudo": [],
        "tolerancia_dias": 3,
    }


def test_cruzar_avanzado_devuelve_conciliados_ajustes_pendientes():
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=_payload_base())
    assert respuesta.status_code == 200
    data = respuesta.json()
    assert data["exito"] is True
    assert "conciliados" in data
    assert "ajustes_contables" in data
    assert "partidas_pendientes" in data
    assert "cuadro_control" in data
    assert "tabla_dinamica_gastos" in data
    assert "estadisticas" in data


def test_cruzar_avanzado_conciliados_tiene_campos_completos():
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=_payload_base())
    data = respuesta.json()
    conc = data["conciliados"]
    assert len(conc) == 2
    c = conc[0]
    assert "fecha" in c
    assert "concepto_banco" in c
    assert "concepto_mayor" in c
    assert "importe_banco" in c
    assert "importe_mayor" in c
    assert "cuadra" in c
    assert c["cuadra"] is True


def test_cruzar_avanzado_cuadro_control_tiene_ingresos_egresos():
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=_payload_base())
    data = respuesta.json()
    ctrl = data["cuadro_control"]
    assert "ingresos" in ctrl
    assert "egresos" in ctrl
    assert "ajustes_contables" in ctrl
    assert "partidas_pendientes" in ctrl
    assert "conciliados" in ctrl
    assert "diferencia_neta" in ctrl["ingresos"]
    assert "diferencia_neta" in ctrl["egresos"]


def test_cruzar_avanzado_tabla_dinamica_gastos():
    """Si hay ajustes, la tabla dinámica debe tener filas."""
    # Payload con comisión que NO matchea (diferente importe)
    payload = {
        "movimientos_banco": [
            {"fecha": "2026-07-01", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
            {"fecha": "2026-07-03", "concepto": "COMISION", "debe": 200, "haber": 0, "saldo": 800, "referencia": "OP-1"},
        ],
        "movimientos_mayor": [
            {"fecha": "2026-07-01", "comprobante": "FCA-1", "concepto": "Factura 1", "debe": 1000, "haber": 0},
        ],
        "extracto_crudo": [],
        "tolerancia_dias": 3,
    }
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    data = respuesta.json()
    # La comisión de 200 no matchea (mayor solo tiene 1000) -> ajuste
    assert len(data["ajustes_contables"]) >= 1
    assert len(data["tabla_dinamica_gastos"]) >= 1
    tabla = data["tabla_dinamica_gastos"]
    assert all(k in tabla[0] for k in ("concepto", "suma", "cantidad", "porcentaje", "porcentaje_acumulado"))


def test_cruzar_avanzado_sin_banco_devuelve_400():
    payload = _payload_base()
    payload["movimientos_banco"] = []
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    assert respuesta.status_code == 400
    assert "movimientos bancarios" in respuesta.json()["detail"].lower()


def test_cruzar_avanzado_sin_mayor_devuelve_400():
    payload = _payload_base()
    payload["movimientos_mayor"] = []
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    assert respuesta.status_code == 400
    assert "libro mayor" in respuesta.json()["detail"].lower()


def test_cruzar_avanzado_con_extracto_crudo_enriquece_cuit():
    """Si se pasa extracto_crudo, los conciliados deben traer CUIT/Nombre."""
    payload = {
        "movimientos_banco": [
            {"fecha": "2026-07-01", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
        ],
        "movimientos_mayor": [
            {"fecha": "2026-07-01", "comprobante": "FCA-1", "concepto": "Factura 1", "debe": 1000, "haber": 0},
        ],
        "extracto_crudo": [{
            "Fecha contable": "2026-07-01",
            "Concepto": "COBRO",
            "Debito en $": 0,
            "Credito en $": 1000,
            "Saldo en $": 1000,
            "Nro doc": "30-12345678-9",
            "Nombre": "CLIENTE TEST S.A.",
            "CBU/Alias": "0000000000000000000001",
        }],
        "tolerancia_dias": 3,
    }
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    data = respuesta.json()
    assert len(data["conciliados"]) == 1
    conc = data["conciliados"][0]
    assert conc["cuit"] == "30-12345678-9"
    assert conc["nombre_tercero"] == "CLIENTE TEST S.A."
    assert conc["cbu"] == "0000000000000000000001"


def test_cruzar_avanzado_tolerancia_dias_personalizada():
    """La tolerancia de días se puede configurar."""
    payload = {
        "movimientos_banco": [
            {"fecha": "2026-07-05", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "R1"},
        ],
        "movimientos_mayor": [
            {"fecha": "2026-07-01", "comprobante": "FCA-1", "concepto": "Factura", "debe": 1000, "haber": 0},
        ],
        "extracto_crudo": [],
        "tolerancia_dias": 3,  # 5 días de diferencia, fuera de tolerancia 3
    }
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    data = respuesta.json()
    # Con tolerancia 3, 5 días de diferencia NO matchea
    assert len(data["conciliados"]) == 0
    assert len(data["partidas_pendientes"]) >= 1

    # Con tolerancia 5, sí matchea
    payload["tolerancia_dias"] = 5
    respuesta = client.post("/api/conciliacion/cruzar-avanzado", json=payload)
    data = respuesta.json()
    assert len(data["conciliados"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])