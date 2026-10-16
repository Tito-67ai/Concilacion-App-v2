"""Tests de la API de revision y aprobacion de asientos (/api/asientos).

Lo que se prueba por HTTP:
    - /proponer devuelve los asientos, las partidas sin asiento y las cuentas.
    - /cuentas lista el plan de cuentas configurado.
    - /aprobar inyecta con el mock (dry-run por defecto) y numera los resultados.
    - /aprobar rechaza asientos desbalanceados y pedidos vacios.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import xubio_injector

client = TestClient(app)


@pytest.fixture(autouse=True)
def _auditoria_temporal(monkeypatch, tmp_path):
    """La auditoria real escribe en logs/: en tests va a un temporal."""
    monkeypatch.setattr(xubio_injector, "RUTA_AUDITORIA", tmp_path / "auditoria.jsonl")


def _payload(**cambios):
    base = {
        "pendientes_banco": [
            {"origen": "banco", "fecha": "2026-07-03", "concepto": "COMISION", "debe": 150, "saldo": 350},
            {"origen": "banco", "fecha": "2026-07-07", "concepto": "TRANSFERENCIA", "haber": 900, "saldo": 1250},
        ],
        "pendientes_xubio": [
            {"origen": "pendiente_mayor", "fecha": "2026-07-04", "concepto": "ALQUILER", "debe": 300, "comprobante": "FCA-3"},
        ],
    }
    base.update(cambios)
    return base


def test_proponer_devuelve_asientos_partidas_y_cuentas():
    respuesta = client.post("/api/asientos/proponer", json=_payload())

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    # Solo la comision lleva asiento; el mayor y la transferencia son partidas.
    assert [a["concepto"] for a in cuerpo["asientos"]] == ["COMISION"]
    assert cuerpo["asientos"][0]["tipo"] == "gasto_bancario"
    assert cuerpo["asientos"][0]["balancea"] is True
    assert {p["concepto"] for p in cuerpo["partidas_temporales"]} == {"ALQUILER", "TRANSFERENCIA"}
    assert cuerpo["balancea"] is True
    assert cuerpo["total_debe"] == cuerpo["total_haber"] == 150.0
    assert cuerpo["cuentas_disponibles"]


def test_cuentas_lista_el_plan_configurado():
    respuesta = client.get("/api/asientos/cuentas")

    assert respuesta.status_code == 200
    nombres = {c["nombre"] for c in respuesta.json()}
    assert "Banco" in nombres
    assert "Gastos bancarios" in nombres


def test_aprobar_inyecta_con_el_mock_en_dry_run():
    propuesta = client.post("/api/asientos/proponer", json=_payload()).json()
    respuesta = client.post(
        "/api/asientos/aprobar",
        json={"asientos": propuesta["asientos"]},
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is True
    assert cuerpo["dry_run"] is True
    assert cuerpo["inyectados"] == 1
    assert cuerpo["errores"] == 0
    assert cuerpo["resultados"][0]["estado"] == "dry_run"
    assert cuerpo["resultados"][0]["payload"]["detalle"]


def test_aprobar_rechaza_un_asiento_desbalanceado():
    respuesta = client.post(
        "/api/asientos/aprobar",
        json={
            "asientos": [
                {
                    "numero": 1,
                    "origen": "banco",
                    "concepto": "COMISION",
                    "debe": 150,
                    "haber": 100,
                    "lineas": [],
                }
            ]
        },
    )

    assert respuesta.status_code == 400
    assert "balancean" in respuesta.json()["detail"]


def test_aprobar_sin_asientos_da_400():
    respuesta = client.post("/api/asientos/aprobar", json={"asientos": []})
    assert respuesta.status_code == 400
