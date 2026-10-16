"""Tests de los asientos de ajuste de partida doble (asientos_ajuste.py).

Lo que se prueba:
    - Cada partida sin coincidencia genera UN asiento que balancea (Debe = Haber).
    - La contracuenta depende del lado y del tipo de concepto:
        extracto + gasto bancario -> subcategoria (Comisiones, IVA, ...)
        extracto + otro           -> cuenta de conciliacion de banco
        mayor                     -> cuenta de conciliacion del mayor
    - El signo del Banco es el correcto: entra plata = Debe Banco; sale = Haber Banco.
    - La hoja "Asientos de Ajuste" viaja en el .xlsx con los asientos y el total.
"""

import io
from datetime import date

import openpyxl

from app.core.config import settings
from app.models.schemas import (
    EncabezadoConciliacion,
    MovimientoBancoExport,
    PendienteExport,
    SolicitudExportacion,
)
from app.services import asientos_ajuste, exportador


def _banco(**campos) -> PendienteExport:
    base = {"origen": "banco", "fecha": date(2026, 7, 5), "concepto": "COMISION", "debe": 150.0}
    base.update(campos)
    return PendienteExport(**base)


def _mayor(**campos) -> PendienteExport:
    base = {"origen": "pendiente_mayor", "fecha": date(2026, 7, 4), "concepto": "ALQUILER", "debe": 300.0}
    base.update(campos)
    return PendienteExport(**base)


# ----------------------------------------------------------------------
# Construccion de asientos
# ----------------------------------------------------------------------


def test_un_asiento_por_partida_y_balancea():
    asientos = asientos_ajuste.construir_asientos(
        pendientes_banco=[_banco()],
        pendientes_xubio=[_mayor()],
    )
    assert len(asientos) == 2
    assert all(a.balancea for a in asientos)
    assert [a.numero for a in asientos] == [1, 2]


def test_gasto_bancario_usa_la_subcategoria_como_contracuenta():
    asiento = asientos_ajuste.asiento_desde_pendiente(1, _banco(concepto="COMISION", debe=150.0))
    assert asiento is not None
    # Sale plata: Debe la contracuenta (gasto) / Haber Banco.
    cuentas = {(l.cuenta, round(l.debe, 2), round(l.haber, 2)) for l in asiento.lineas}
    assert ("Comisiones", 150.0, 0.0) in cuentas
    assert (settings.CUENTA_BANCO, 0.0, 150.0) in cuentas


def test_gasto_bancario_sin_subcategoria_usa_gastos_bancarios():
    asiento = asientos_ajuste.asiento_desde_pendiente(1, _banco(concepto="INTERESES", debe=50.0))
    assert asiento is not None
    cuentas = {l.cuenta for l in asiento.lineas}
    assert settings.CUENTA_GASTOS_BANCARIOS in cuentas


def test_credito_en_banco_debita_el_banco():
    # Un credito del extracto (haber) es plata que entra: Debe Banco / Haber contra.
    asiento = asientos_ajuste.asiento_desde_pendiente(1, _banco(concepto="TRANSFERENCIA", debe=0.0, haber=800.0))
    assert asiento is not None
    cuentas = {(l.cuenta, round(l.debe, 2), round(l.haber, 2)) for l in asiento.lineas}
    assert (settings.CUENTA_BANCO, 800.0, 0.0) in cuentas
    assert (settings.CUENTA_CONCILIACION_BANCO, 0.0, 800.0) in cuentas


def test_partida_del_mayor_usa_la_cuenta_de_conciliacion_del_mayor():
    asiento = asientos_ajuste.asiento_desde_pendiente(1, _mayor(concepto="ALQUILER", debe=300.0))
    assert asiento is not None
    assert asiento.origen == asientos_ajuste.ORIGEN_MAYOR
    cuentas = {l.cuenta for l in asiento.lineas}
    assert settings.CUENTA_CONCILIACION_MAYOR in cuentas
    assert settings.CUENTA_BANCO in cuentas


def test_partida_sin_importe_no_genera_asiento():
    assert asientos_ajuste.asiento_desde_pendiente(1, _banco(debe=0.0, haber=0.0)) is None


def test_totales_debe_y_haber_coinciden():
    asientos = asientos_ajuste.construir_asientos(
        pendientes_banco=[_banco(), _banco(concepto="IVA", debe=200.0)],
        pendientes_xubio=[_mayor()],
    )
    debe, haber = asientos_ajuste.totales(asientos)
    assert debe == haber == 650.0


# ----------------------------------------------------------------------
# Hoja del papel de trabajo
# ----------------------------------------------------------------------


def _solicitud(**cambios) -> SolicitudExportacion:
    base = {
        "encabezado": EncabezadoConciliacion(empresa="ACME S.A.", banco="SANT", periodo="2026-07"),
        "pendientes_banco": [_banco(), _banco(fecha=date(2026, 7, 6), concepto="IVA", debe=200.0)],
        "pendientes_xubio": [_mayor()],
        "movimientos_banco": [
            MovimientoBancoExport(fecha=date(2026, 7, 5), concepto="COMISION", debe=150.0, saldo=-150.0),
        ],
    }
    base.update(cambios)
    return SolicitudExportacion(**base)


def _hoja_asientos(contenido: bytes):
    libro = openpyxl.load_workbook(io.BytesIO(contenido))
    assert exportador.HOJA_ASIENTOS in libro.sheetnames
    return libro[exportador.HOJA_ASIENTOS]


def test_la_hoja_de_asientos_viaja_en_el_archivo():
    hoja = _hoja_asientos(exportador.exportar(_solicitud()))
    encabezados = [hoja.cell(row=exportador.FILA_ENCABEZADO_ASIENTOS, column=c).value for c in range(1, 8)]
    assert encabezados == exportador.COLUMNAS_ASIENTOS_AJUSTE

    valores = [c.value for fila in hoja.iter_rows() for c in fila]
    assert "Comisiones" in valores
    assert "TOTAL GENERAL" in valores
    # Los tres asientos (2 banco + 1 mayor) tienen su total.
    assert "Total asiento 1" in valores
    assert "Total asiento 3" in valores


def test_la_hoja_de_asientos_balancea_a_nivel_total():
    hoja = _hoja_asientos(exportador.exportar(_solicitud()))
    # La fila TOTAL GENERAL trae el mismo numero en Debe (F) y Haber (G).
    fila_total = next(
        f for f in range(1, hoja.max_row + 1)
        if hoja.cell(row=f, column=4).value == "TOTAL GENERAL"
    )
    debe = hoja.cell(row=fila_total, column=6).value
    haber = hoja.cell(row=fila_total, column=7).value
    assert debe == haber == 650.0


def test_la_hoja_de_asientos_se_escribe_sin_pendientes():
    hoja = _hoja_asientos(exportador.exportar(_solicitud(pendientes_banco=[], pendientes_xubio=[])))
    valores = [c.value for fila in hoja.iter_rows() for c in fila]
    assert any(isinstance(v, str) and v.startswith("Sin partidas sin coincidencia") for v in valores)
    assert "TOTAL GENERAL" not in valores
