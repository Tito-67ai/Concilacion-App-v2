"""Tests del papel de trabajo FO 02-03 (estructura segun modelo de auditoria).

Estructura esperada (hoja "Libro Mayor"):
    Fila 9: encabezados (Fecha, Documento, Cuenta, Debe, Haber, Saldo, Descripcion, Organizacion, Centro de Costos)
    Fila 10: "Saldo Inicial" con saldo en F
    Fila 11+: todos los movimientos del mayor ordenados por fecha, saldo por formula

Hoja "Movimientos Bancarios":
    Fila 8: encabezados (Fecha contable, Concepto, Debito en $, Credito en $, Saldo en $)
    Fila 9: "Saldo Inicial" con saldo en E
    Fila 10+: todos los movimientos del extracto (sin repetidos), debito=negativo, credito=positivo, saldo acumulado
    Encabezado sin relleno y con filtro de Excel (A8:E...).

Colores:
    Libro Mayor:
        Amarillo (FFFFFF00) = el movimiento tiene coincidencia (conciliado)
        Verde (FF93C47D)    = sin coincidencia (partida pendiente)
    Movimientos Bancarios (jerarquia FO 02-03):
        Amarillo (FFFFFF00) = el movimiento tiene coincidencia (conciliado)
        Verde (FF93C47D)    = sin coincidencia y es gasto/impuesto bancario
        Sin color           = sin coincidencia y es comercial (a auditar)
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
        assert celda.fill.fgColor.rgb == "00000000"  # sin relleno azul
        # Sin relleno, la fuente no puede ser blanca: el titulo quedaria
        # invisible sobre el fondo blanco (incluida la "Fecha").
        color = celda.font.color.rgb if celda.font.color else None
        assert color not in ("00FFFFFF", "FFFFFFFF")


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


def test_libro_mayor_escribe_documento_cuenta_y_organizacion():
    """El modelo de auditoria: B=Documento, C=Cuenta, H=Organizacion."""
    sol = _solicitud(
        movimientos_mayor=[
            {
                "fecha": "2026-07-02",
                "documento": "Movimiento de Fondos N 952",
                "cuenta": "1.1.1.2.01 I.C.B.C. Bank",
                "organizacion": "FUSION MKT S.R.L.",
                "descripcion": "RESCATE FCI.",
                "concepto": "detalle interno",
                "debe": 32000000,
                "haber": 0,
            }
        ],
        pendientes_xubio=[],
    )
    hoja = _mayor(exportador.exportar(sol))
    assert hoja["B11"].value == "Movimiento de Fondos N 952"   # Documento
    assert hoja["C11"].value == "1.1.1.2.01 I.C.B.C. Bank"     # Cuenta
    assert hoja["G11"].value == "RESCATE FCI."                 # Descripción
    assert hoja["H11"].value == "FUSION MKT S.R.L."            # Organización


def test_libro_mayor_saldo_inicial_lleva_la_fecha_de_apertura():
    """El Saldo Inicial va con la fecha de apertura (un dia antes del primero).

    La cuenta queda vacia a proposito: el mayor trae todas las cuentas y poner
    "la primera" seria una cuenta cualquiera.
    """
    sol = _solicitud(
        movimientos_mayor=[
            {
                "fecha": "2026-07-01",
                "cuenta": "1.1.1.2.01 I.C.B.C. Bank",
                "debe": 10,
                "haber": 0,
            }
        ],
        pendientes_xubio=[],
    )
    hoja = _mayor(exportador.exportar(sol))
    assert hoja["A10"].value.date() == date(2026, 6, 30)  # un dia antes del 1er movimiento
    assert hoja["B10"].value == "Saldo Inicial"
    assert hoja["C10"].value in (None, "")


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


def test_libro_mayor_conciliados_en_amarillo_pendientes_en_verde():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # FCA-1 y FCA-2 tienen coincidencia -> amarillo en D/E
    for fila in (11, 12):
        for col in (4, 5):  # D, E
            c = hoja.cell(row=fila, column=col)
            if c.value not in (None, 0):
                assert c.fill.fgColor.rgb == "FFFFFF00", f"Fila {fila} col {col} deberia ser amarillo"
    # FCA-3 esta en pendientes_xubio -> sin coincidencia -> verde
    for col in (4, 5):
        c = hoja.cell(row=13, column=col)
        if c.value not in (None, 0):
            assert c.fill.fgColor.rgb == "FF93C47D", f"Fila 13 col {col} deberia ser verde"


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
        # Sin relleno azul (ni ninguno): solo el dato.
        assert c.fill.fgColor.rgb in ("00000000", None) or c.fill.fill_type is None


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


def test_movimientos_bancarios_encabezados_sin_relleno():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # Encabezado de la tabla (A-E) y del cuadro (I-K): sin relleno.
    for col in list(range(1, 6)) + list(range(9, 12)):
        c = hoja.cell(row=8, column=col)
        assert not c.fill.fill_type, f"{c.coordinate} no deberia tener relleno"


def test_movimientos_bancarios_conciliados_en_amarillo_gastos_en_verde():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # COBRO (fila 10) y PAGO PROVEEDOR (fila 13) tienen coincidencia -> amarillo
    assert hoja["D10"].fill.fgColor.rgb == "FFFFFF00"
    assert hoja["C13"].fill.fgColor.rgb == "FFFFFF00"
    # COMISION (fila 11) e IVA (fila 12) no tienen coincidencia pero son gasto
    # bancario -> verde (van al cuadro de partidas pendientes de registracion).
    assert hoja["C11"].fill.fgColor.rgb == "FF93C47D"
    assert hoja["C12"].fill.fgColor.rgb == "FF93C47D"


def test_movimientos_bancarios_comercial_sin_match_queda_sin_color():
    # Un debito comercial (transferencia) sin coincidencia NO es gasto bancario:
    # no debe pintarse, queda sin color para auditoria manual (regla FO 02-03).
    sol = _solicitud(
        pendientes_banco=[
            {"origen": "banco", "fecha": "2026-07-07", "concepto": "TRANSFERENCIA", "referencia": "OP-11", "debe": 500, "haber": 0},
        ],
        movimientos_banco=[
            {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000, "referencia": "REF-1"},
            {"fecha": "2026-07-07", "concepto": "TRANSFERENCIA", "debe": 500, "saldo": 500, "referencia": "OP-11"},
        ],
    )
    hoja = _movimientos(exportador.exportar(sol))
    # fila 10 COBRO conciliado -> amarillo; fila 11 TRANSFERENCIA pendiente
    # comercial -> sin relleno.
    assert hoja["D10"].fill.fgColor.rgb == "FFFFFF00"
    assert not hoja["C11"].fill.fill_type, "el pendiente comercial no debe pintarse"


def test_movimientos_bancarios_tiene_filtro():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # Filtro de Excel sobre la tabla, arrancando en el encabezado (fila 8).
    assert hoja.auto_filter.ref == "A8:E13"


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
# Cuadro de asientos sin coincidencia (debajo de cada tabla)
# ----------------------------------------------------------------------


def test_cuadro_asientos_banco_va_debajo_de_la_tabla():
    """Los pendientes del banco se detallan abajo, con una fila en blanco de separacion."""
    hoja = _movimientos(exportador.exportar(_solicitud()))
    # Tabla: encabezado 8, saldo inicial 9, datos 10-13 -> cuadro desde la 16
    assert hoja["A16"].value.startswith("Asientos sin coincidencia en el banco")
    assert hoja["A16"].font.bold
    # Fila 15 en blanco: el cuadro no es una continuation de los datos
    assert all(hoja.cell(row=15, column=col).value in (None, "") for col in range(1, 6))

    encabezados = ["Fecha", "Detalle", "Debe", "Haber", "Importe"]
    assert [hoja.cell(row=17, column=col).value for col in range(1, 6)] == encabezados

    # COMISION (05/07) e IVA (06/07), en orden de fecha
    assert hoja["A18"].value.date() == date(2026, 7, 5)
    assert hoja["B18"].value.startswith("COMISION")
    assert hoja["C18"].value == 150   # Debe
    assert hoja["D18"].value is None  # Haber
    assert hoja["E18"].value == 150   # Importe

    assert hoja["A19"].value.date() == date(2026, 7, 6)
    assert hoja["C19"].value == 200
    assert hoja["E19"].value == 200

    # Total del cuadro
    assert hoja["B20"].value == "TOTAL"
    assert hoja["C20"].value == 350
    assert hoja["D20"].value in (None, 0)
    assert hoja["E20"].value == 350


def test_cuadro_asientos_mayor_va_debajo_de_la_tabla():
    hoja = _mayor(exportador.exportar(_solicitud()))
    # Datos 11-13 -> cuadro desde la 16
    assert hoja["A16"].value.startswith("Asientos sin coincidencia en el Libro Mayor")
    assert [hoja.cell(row=17, column=col).value for col in range(1, 6)] == [
        "Fecha", "Detalle", "Debe", "Haber", "Importe"
    ]
    # FCA-3 ALQUILER: el comprobante va pegado al detalle para poder identificarlo
    assert hoja["A18"].value.date() == date(2026, 7, 4)
    assert hoja["B18"].value == "ALQUILER · FCA-3"
    assert hoja["C18"].value == 300
    assert hoja["D18"].value is None
    assert hoja["E18"].value == 300
    assert hoja["B19"].value == "TOTAL"
    assert hoja["C19"].value == 300


def test_cuadro_asientos_no_se_escribe_sin_pendientes():
    """Sin asientos sin coincidencia no hay cuadro: ni titulo ni encabezado."""
    sol = _solicitud(pendientes_xubio=[], pendientes_banco=[])
    for hoja in (_mayor(exportador.exportar(sol)), _movimientos(exportador.exportar(sol))):
        encontrados = [
            hoja.cell(row=fila, column=1).value
            for fila in range(14, hoja.max_row + 1)
            if hoja.cell(row=fila, column=1).value
        ]
        assert all(not str(v).startswith("Asientos sin coincidencia") for v in encontrados)


def test_cuadro_asientos_importes_con_formato_contable():
    hoja = _movimientos(exportador.exportar(_solicitud()))
    for fila in (18, 19, 20):
        for col in (3, 4, 5):
            celda = hoja.cell(row=fila, column=col)
            if celda.value not in (None, 0):
                fmt = celda.number_format
                assert "#,##0.00" in fmt and "-" in fmt and "@" in fmt
                assert celda.border.top.style == "thin"
                assert celda.border.bottom.style == "thin"


def test_el_filtro_del_extracto_no_traga_el_cuadro():
    """El auto_filter termina en el ultimo dato, no sobre el cuadro de abajo."""
    hoja = _movimientos(exportador.exportar(_solicitud()))
    assert hoja.auto_filter.ref == "A8:E13"


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
    # Libro Mayor: headers SIN relleno azul (transparente) pero con texto visible
    for col in range(1, 10):
        c = hoja.cell(row=9, column=col)
        assert c.fill.fgColor.rgb == "00000000"  # sin relleno
        assert c.font.bold
        color = c.font.color.rgb if c.font.color else None
        assert color not in ("00FFFFFF", "FFFFFFFF")  # nunca blanco sobre blanco

    hoja2 = _movimientos(exportador.exportar(_solicitud()))
    # Movimientos Bancarios: headers SIN relleno (en limpio) pero con texto visible
    for col in range(1, 6):
        c = hoja2.cell(row=8, column=col)
        assert not c.fill.fill_type
        assert c.font.bold
        color = c.font.color.rgb if c.font.color else None
        assert color not in ("00FFFFFF", "FFFFFFFF")  # nunca blanco sobre blanco


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


# ----------------------------------------------------------------------
# Logo de la empresa en el membrete (recuadro A1:B3)
# ----------------------------------------------------------------------


def test_el_logo_va_en_el_membrete_de_las_dos_hojas():
    """El membrete queda con el logo en el recuadro vacio de la izquierda."""
    libro = _libro(exportador.exportar(_solicitud()))
    for nombre in ("Libro Mayor", "Movimientos Bancarios"):
        imagenes = libro[nombre]._images
        assert len(imagenes) == 1, f"{nombre} no tiene el logo"
        ancla = imagenes[0].anchor
        # Arriba a la izquierda: A1 (col 0, row 0).
        assert ancla._from.col == 0
        assert ancla._from.row == 0


def test_el_logo_entra_escalado_sin_deformarse(tmp_path):
    """Un logo cuadrado se achica respetando la proporcion hasta el recuadro."""
    from PIL import Image as ImagenPIL
    from openpyxl import Workbook

    ruta = tmp_path / "logo.png"
    ImagenPIL.new("RGBA", (400, 400), (0, 0, 0, 0)).save(ruta)

    hoja = Workbook().active
    exportador._insertar_logo(hoja, ruta)

    assert len(hoja._images) == 1
    imagen = hoja._images[0]
    assert imagen.width <= exportador.ANCHO_LOGO_MAX
    assert imagen.height <= exportador.ALTO_LOGO_MAX
    # Cuadrado entra cuadrado: no se estira.
    assert imagen.width == imagen.height


def test_sin_archivo_de_logo_la_exportacion_no_se_rompe(tmp_path, caplog):
    """Si el logo no existe, se exporta igual y solo queda el aviso."""
    from openpyxl import Workbook

    contenido = exportador.exportar(_solicitud())
    assert contenido  # la exportacion normal sigue andando

    hoja = Workbook().active
    exportador._insertar_logo(hoja, tmp_path / "no_existe.png")
    assert len(hoja._images) == 0