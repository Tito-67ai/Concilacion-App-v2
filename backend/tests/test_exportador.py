"""Tests del papel de trabajo FO 02-03 (estructura segun modelo de auditoria).

Estructura esperada (hoja "Libro Mayor"):
    Fila 9: encabezados (Fecha, Documento, Cuenta, Debe, Haber, Saldo, Descripcion, Organizacion, Centro de Costos)
    Fila 10: "Saldo Inicial" con saldo en F
    Fila 11+: todos los movimientos del mayor ordenados por fecha, saldo por formula

Hoja "Movimientos Bancarios":
    Fila 8: encabezados (Fecha contable, Concepto, Debito en $, Credito en $, Saldo en $)
    Fila 9: "Saldo Inicial" con saldo en E
    Fila 10+: todos los movimientos del extracto (sin repetidos), debito=negativo, credito=positivo, saldo acumulado

Colores:
    Amarillo (FFFFFF00) = importe conciliado
    Verde (93C47D) = gasto bancario pendiente (debito automatico)
"""

import io
from collections import Counter
from datetime import date, datetime

import pytest
from openpyxl import load_workbook

from app.services import exportador
from app.models.schemas import SolicitudExportacion


FORMATO_CONTABLE = '_ * #,##0.00_ ;_ * \\-#,##0.00_ ;_ * "-"??_ ;_ @_ '


def _libro(contenido: bytes):
    return load_workbook(io.BytesIO(contenido))


def _mayor(contenido: bytes):
    return _libro(contenido)["Libro Mayor"]


def _movimientos(contenido: bytes):
    return _libro(contenido)["Movimientos Bancarios"]


def _solicitud(**cambios) -> SolicitudExportacion:
    """Solicitud base con datos representativos."""
    base = {
        "encabezado": {
            "empresa": "ACME S.A.",
            "banco": "SANT",
            "numero_cuenta": "0001234",
            "periodo": "2026-07",
        },
        "movimientos_mayor": [
            {"fecha": "2026-07-02", "comprobante": "FCA-1", "concepto": "Factura 1", "debe": 1000, "haber": 0},
            {"fecha": "2026-07-03", "comprobante": "FCA-2", "concepto": "Pago 2", "debe": 0, "haber": 400},
            {"fecha": "2026-07-04", "comprobante": "FCA-3", "concepto": "ALQUILER", "debe": 300, "haber": 0},
        ],
        "pendientes_xubio": [
            {"origen": "xubio", "fecha": "2026-07-04", "comprobante": "FCA-3", "concepto": "ALQUILER", "debe": 300, "haber": 0}
        ],
        "pendientes_banco": [
            {"origen": "banco", "fecha": "2026-07-05", "concepto": "COMISION", "referencia": "OP-9", "debe": 150, "haber": 0},
            {"origen": "banco", "fecha": "2026-07-06", "concepto": "IVA", "referencia": "OP-10", "debe": 200, "haber": 0},
        ],
        "movimientos_banco": [
            {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
            {"fecha": "2026-07-05", "concepto": "COMISION", "debe": 150, "saldo": 850, "referencia": "OP-9"},
            {"fecha": "2026-07-06", "concepto": "IVA", "debe": 200, "saldo": 650, "referencia": "OP-10"},
            {"fecha": "2026-07-07", "concepto": "PAGO PROVEEDOR", "debe": 500, "saldo": 150, "referencia": "OP-11"},
        ],
        "saldo_inicial_mayor": 500,
        "saldo_final_banco": 150,
    }
    base.update(cambios)
    return SolicitudExportacion.model_validate(base)


# ----------------------------------------------------------------------
# Hoja LIBRO MAYOR
# ----------------------------------------------------------------------


def test_libro_mayor_tiene_encabezados_correctos():
    hoja = _mayor(exportador.exportar(_solicitud()))
    esperados = [
        "Fecha", "Documento", "Cuenta", "Debe", "Haber", "Saldo",
        "Descripción", "Organización", "Centro de Costos"
    ]
    for i, nombre in enumerate(esperados, start=1):
        assert hoja.cell(row=9, column=i).value == nombre
        celda = hoja.cell(row=9, column=i)
        assert celda.font.bold
        assert celda.fill.fgColor.rgb == "FF00B0F0"


def test_libro_mayor_saldo_inicial_en_fila_10():
    hoja = _mayor(exportador.exportar(_solicitud()))
    assert hoja["B10"].value == "Saldo Inicial"
    assert hoja["F10"].value == 500
    fmt = hoja["F10"].number_format
    assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt
    assert hoja["B10"].font.bold


def test_libro_mayor_lista_todos_los_movimientos_ordenados():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # Debe haber 3 movimientos (FCA-1, FCA-2, FCA-3) en filas 11, 12, 13
    # openpyxl escribe datetime, comparar solo la fecha
    assert hoja["A11"].value.date() == date(2026, 7, 2)
    assert hoja["B11"].value == "FCA-1"
    assert hoja["D11"].value == 1000
    assert hoja["E11"].value in (None, 0)  # haber=0 se escribe como vacio

    assert hoja["A12"].value.date() == date(2026, 7, 3)
    assert hoja["B12"].value == "FCA-2"
    assert hoja["D12"].value in (None, 0)  # debe=0 se escribe como vacio
    assert hoja["E12"].value == 400

    assert hoja["A13"].value.date() == date(2026, 7, 4)
    assert hoja["B13"].value == "FCA-3"
    assert hoja["D13"].value == 300
    assert hoja["E13"].value in (None, 0)  # haber=0 se escribe como vacio


def test_libro_mayor_saldo_por_formula():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # F11 = F10 + D11 - E11
    assert hoja["F11"].value == "=F10+D11-E11"
    # F12 = F11 + D12 - E12
    assert hoja["F12"].value == "=F11+D12-E12"
    # F13 = F12 + D13 - E13
    assert hoja["F13"].value == "=F12+D13-E13"
    # Todas las celdas de saldo tienen formato contable
    for fila in (10, 11, 12, 13):
        celda = hoja.cell(row=fila, column=6)
        fmt = celda.number_format
        assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt
        assert celda.alignment.horizontal == "right"


def test_libro_mayor_conciliados_en_amarillo_pendientes_sin_color():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # FCA-1 y FCA-2 estan conciliados -> amarillo en D/E
    for fila in (11, 12):
        for col in (4, 5):  # D, E
            c = hoja.cell(row=fila, column=col)
            if c.value not in (None, 0):
                assert c.fill.fgColor.rgb == "FFFFFF00", f"Fila {fila} col {col} deberia ser amarillo"
    # FCA-3 esta en pendientes_xubio -> sin color
    for col in (4, 5):
        c = hoja.cell(row=13, column=col)
        if c.value not in (None, 0):
            assert c.fill.fgColor.rgb != "FFFFFF00" or c.fill.fgColor.rgb == "00000000", f"Fila 13 col {col} no deberia ser amarillo"


# ----------------------------------------------------------------------
# Hoja MOVIMIENTOS BANCARIOS
# ----------------------------------------------------------------------


def test_movimientos_bancarios_tiene_encabezados_correctos():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    esperados = ["Fecha contable", "Concepto", "Debito en $", "Credito en $", "Saldo en $"]
    for i, nombre in enumerate(esperados, start=1):
        assert hoja.cell(row=8, column=i).value == nombre
        c = hoja.cell(row=8, column=i)
        assert c.font.bold
        assert c.fill.fgColor.rgb == "FF00B0F0"


def test_movimientos_bancarios_saldo_inicial_en_fila_9():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    assert hoja["B9"].value == "Saldo Inicial"
    assert hoja["E9"].value == 150
    fmt = hoja["E9"].number_format
    assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt
    assert hoja["B9"].font.bold


def test_movimientos_bancarios_todos_los_movimientos_sin_repetidos():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # 4 movimientos unicos en filas 10, 11, 12, 13
    conceptos = [hoja.cell(row=r, column=2).value for r in range(10, 14)]
    assert conceptos == ["COBRO", "COMISION", "IVA", "PAGO PROVEEDOR"]


def test_movimientos_bancarios_debito_negativo_credito_positivo():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # COBRO: haber=1000 -> credito (D) = 1000, debito (C) = None
    assert hoja["C10"].value is None
    assert hoja["D10"].value == 1000
    # COMISION: debe=150 -> debito (C) = -150, credito (D) = None
    assert hoja["C11"].value == -150
    assert hoja["D11"].value is None
    # IVA: debe=200 -> debito (C) = -200
    assert hoja["C12"].value == -200
    # PAGO PROVEEDOR: debe=500 -> debito (C) = -500
    assert hoja["C13"].value == -500


def test_movimientos_bancarios_saldo_acumulado_por_formula():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # E10 = E9 + D10 + C10 (C10 es None -> 0)
    assert hoja["E10"].value == "=E9+D10+C10"
    # E11 = E10 + D11 + C11
    assert hoja["E11"].value == "=E10+D11+C11"
    # E12 = E11 + D12 + C12
    assert hoja["E12"].value == "=E11+D12+C12"
    # E13 = E12 + D13 + C13
    assert hoja["E13"].value == "=E12+D13+C13"
    # Formato contable en todas
    for fila in (9, 10, 11, 12, 13):
        fmt = hoja.cell(row=fila, column=5).number_format
        assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt


def test_movimientos_bancarios_gasto_pendiente_en_verde():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # COMISION (fila 11) y IVA (fila 12) son gastos bancarios y estan en pendientes_banco -> verde en C
    c11 = hoja.cell(row=11, column=3)
    c12 = hoja.cell(row=12, column=3)
    assert c11.fill.fgColor.rgb == "FF93C47D"
    assert c12.fill.fgColor.rgb == "FF93C47D"
    # PAGO PROVEEDOR (fila 13) NO es gasto bancario -> no verde
    c13 = hoja.cell(row=13, column=3)
    assert c13.fill.fgColor.rgb != "FF93C47D"


def test_movimientos_bancarios_conciliados_en_amarillo():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # COBRO (fila 10) esta conciliado -> amarillo en D (tiene credito)
    d10 = hoja.cell(row=10, column=4)
    assert d10.fill.fgColor.rgb == "FFFFFF00"
    # COMISION e IVA son pendientes -> no amarillo (son verdes)
    # PAGO PROVEEDOR no es pendiente -> amarillo en C
    c13 = hoja.cell(row=13, column=3)
    assert c13.fill.fgColor.rgb == "FFFFFF00"


def test_movimientos_bancarios_no_duplica_lineas_repetidas():
    # Agregar una linea repetida del extracto
    sol = _solicitud(
        movimientos_banco=[
            {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
            {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000, "referencia": "REF-1"},  # repetida
            {"fecha": "2026-07-05", "concepto": "COMISION", "debe": 150, "saldo": 850, "referencia": "OP-9"},
        ]
    )
    hoja = _movimientos(exportador.exportar(sol))
    # Solo 2 filas de datos (10, 11) - openpyxl devuelve datetime, comparar .date()
    assert hoja["A10"].value.date() == date(2026, 7, 2)
    assert hoja["A11"].value.date() == date(2026, 7, 5)
    assert hoja["A12"].value is None  # no hay fila 12


def test_movimientos_bancarios_fechas_formato_dd_mm_yyyy():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    for fila in (10, 11, 12, 13):
        c = hoja.cell(row=fila, column=1)
        assert c.number_format == "dd/mm/yyyy"


# ----------------------------------------------------------------------
# Formatos generales
# ----------------------------------------------------------------------


def test_importes_formato_contable_dos_decimales():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # Todas las celdas de importe en Libro Mayor (D, E, F)
    for fila in (10, 11, 12, 13):
        for col in (4, 5, 6):
            c = hoja.cell(row=fila, column=col)
            if c.value not in (None, 0):
                fmt = c.number_format
                assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt


def test_encabezados_resaltados_azul():
    hoja = _mayor(exportador.exportar(_solicitud()))
    for col in range(1, 10):
        c = hoja.cell(row=9, column=col)
        assert c.fill.fgColor.rgb == "FF00B0F0"
        assert c.font.bold

    hoja2 = _movimientos(exportador.exportar(_solicitud()))
    for col in range(1, 6):
        c = hoja2.cell(row=8, column=col)
        assert c.fill.fgColor.rgb == "FF00B0F0"
        assert c.font.bold


def test_membrete_linkado_desde_movimientos():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    assert hoja["B5"].value == "=+'Libro Mayor'!B5"
    assert hoja["B6"].value == "=+'Libro Mayor'!B6"
    assert hoja["I5"].value == "=+'Libro Mayor'!I5"
    assert hoja["I6"].value == "=+'Libro Mayor'!I6"


# ----------------------------------------------------------------------
# Casos borde
# ----------------------------------------------------------------------


def test_conciliacion_vacia_no_falla():
    """Sin movimientos ni pendientes no debe romper."""
    sol = _solicitud(
        movimientos_mayor=[],
        pendientes_xubio=[],
        pendientes_banco=[],
        movimientos_banco=[],
        saldo_inicial_mayor=0,
        saldo_final_banco=0,
    )
    contenido = exportador.exportar(sol)
    hoja = _mayor(contenido)
    assert hoja["B10"].value == "Saldo Inicial"
    assert hoja["F10"].value == 0


def test_importes_nan_no_rompen():
    sol = _solicitud(
        movimientos_mayor=[{"fecha": "2026-07-01", "comprobante": "X", "concepto": "TEST", "debe": float("nan"), "haber": 0}],
        pendientes_xubio=[],
    )
    contenido = exportador.exportar(sol)
    hoja = _mayor(contenido)
    assert hoja["D11"].value in (None, 0)


def test_muchas_filas_no_se_pisan():
    """Muchos movimientos no deben pisar la estructura."""
    # Usar fechas validas dentro de julio (1-31) y agosto (1-31)
    muchos = []
    for i in range(1, 40):
        dia = (i % 28) + 1  # 1-28 para ser seguro
        mes = 7 if i <= 28 else 8
        muchos.append({
            "fecha": f"2026-{mes:02d}-{dia:02d}",
            "comprobante": f"C{i}",
            "concepto": f"MOV {i}",
            "debe": i * 100,
            "haber": 0
        })
    sol = _solicitud(movimientos_mayor=muchos, pendientes_xubio=[])
    hoja = _mayor(exportador.exportar(sol))
    # La ultima fila de datos deberia estar mucho mas abajo
    ultima_con_dato = max(r for r in range(11, 100) if hoja.cell(row=r, column=1).value)
    assert ultima_con_dato >= 49  # 10 (saldo inicial) + 39 movimientos