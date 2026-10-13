"""Tests del papel de trabajo FO 02-03.

Cada test vuelve a leer el .xlsx generado con openpyxl. No se chequea que el
archivo "no este vacio": se chequean las celdas donde caeria cada dato, porque
un archivo que se abre y esta vacio pasa cualquier prueba de bytes.

La estructura que se prueba es la del formulario: membrete en las filas 1-6,
Tabla 1 (mayor completo con saldo por formula), Tabla 2 y Tabla 3 de partidas
pendientes, pie de control y, en la segunda hoja, el extracto resumido en cinco
columnas (fecha, concepto, debito, credito y saldo).
"""

import io
from datetime import date, datetime

import openpyxl
import pytest

from app.models.schemas import SolicitudExportacion
from app.services import exportador


# El formato contable del formulario: miles con separador y el cero como "-".
FORMATO_CONTABLE = '_ * #,##0.00_ ;_ * \\-#,##0.00_ ;_ * "-"??_ ;_ @_ '


def _libro(contenido: bytes):
    return openpyxl.load_workbook(io.BytesIO(contenido))


def _mayor(contenido: bytes):
    return _libro(contenido)["Libro Mayor"]


def _movimientos(contenido: bytes):
    return _libro(contenido)["Movimientos Bancarios"]


def _celda(hoja, coordenada: str):
    """La celda, con la fecha como date y no como datetime.

    Al releer el archivo, openpyxl devuelve datetime para cualquier celda con
    formato de fecha, aunque lo escrito haya sido un date.
    """
    valor = hoja[coordenada].value
    if isinstance(valor, datetime):
        return valor.date()
    return valor


def _valores(hoja) -> list:
    return [celda.value for fila in hoja.iter_rows() for celda in fila]


def _solicitud(**cambios) -> SolicitudExportacion:
    base = {
        "encabezado": {
            "empresa": "ACME S.A.",
            "banco": "SANT",
            "numero_cuenta": "0001234",
            "periodo": "2026-07",
        },
        "movimientos_mayor": [
            {"fecha": "2026-07-02", "comprobante": "FCA-1", "concepto": "Factura 1", "debe": 1000},
            {"fecha": "2026-07-03", "comprobante": "FCA-2", "concepto": "Pago 2", "haber": 400},
        ],
        "pendientes_xubio": [
            {"origen": "xubio", "fecha": "2026-07-04", "comprobante": "FCA-3", "concepto": "ALQUILER", "debe": 300}
        ],
        "pendientes_banco": [
            {"origen": "banco", "fecha": "2026-07-05", "concepto": "COMISION", "referencia": "OP-9", "debe": 150}
        ],
        "movimientos_banco": [
            {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000},
            {"fecha": "2026-07-05", "concepto": "COMISION", "debe": 150, "saldo": 850},
        ],
        "saldo_inicial_mayor": 500,
        "saldo_final_banco": 850,
    }
    base.update(cambios)
    return SolicitudExportacion.model_validate(base)


# ----------------------------------------------------------------------
# Membrete
# ----------------------------------------------------------------------


def test_conserva_el_membrete_de_la_plantilla():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["I1"].value == "FO 02-03"
    assert hoja["I2"].value == "Rev 0"
    assert "Papeles de Trabajo" in hoja["C2"].value
    assert hoja["A5"].value == "Empresa:"
    assert hoja["H5"].value == "Periodo a conciliar:"
    assert hoja["A6"].value == "Banco:"
    assert hoja["H6"].value == "Numero de Cuenta:"


def test_escribe_empresa_banco_cuenta_y_periodo():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["B5"].value == "ACME S.A."
    assert hoja["B6"].value == "SANT"
    assert hoja["I6"].value == "0001234"
    assert _celda(hoja, "I5") == date(2026, 7, 1)
    assert hoja["I5"].number_format == "yyyy-mm-dd"


def test_un_periodo_que_no_se_entiende_se_escribe_como_venia():
    hoja = _mayor(exportador.exportar(_solicitud(encabezado={"periodo": "julio 26"})))

    assert hoja["I5"].value == "julio 26"


def test_sin_periodo_la_celda_queda_vacia():
    hoja = _mayor(exportador.exportar(_solicitud(encabezado={"periodo": None})))

    assert hoja["I5"].value is None


def test_la_hoja_de_movimientos_sigue_al_membrete_por_formula():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    assert hoja["B5"].value == "=+'Libro Mayor'!B5"
    assert hoja["B6"].value == "=+'Libro Mayor'!B6"
    assert hoja["I5"].value == "=+'Libro Mayor'!I5"
    assert hoja["I6"].value == "=+'Libro Mayor'!I6"


# ----------------------------------------------------------------------
# Tabla 1: movimientos del Libro Mayor
# ----------------------------------------------------------------------


def test_la_tabla1_tiene_las_nueve_columnas_del_formulario():
    hoja = _mayor(exportador.exportar(_solicitud()))

    esperadas = [
        "Fecha",
        "Documento",
        "Cuenta",
        "Debe",
        "Haber",
        "Saldo",
        "Descripción",
        "Organización",
        "Centro de Costos",
    ]
    leidas = [hoja.cell(row=8, column=i + 1).value for i in range(len(esperadas))]

    assert leidas == esperadas


def test_la_tabla1_arranca_con_el_saldo_inicial():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["G9"].value == "Saldo Inicial"
    assert hoja["F9"].value == 500


def test_la_tabla1_lista_los_movimientos_del_mayor():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert _celda(hoja, "A10") == date(2026, 7, 2)
    assert hoja["B10"].value == "FCA-1"
    assert hoja["D10"].value == 1000
    assert hoja["E10"].value == 0
    assert hoja["G10"].value == "Factura 1"

    assert _celda(hoja, "A11") == date(2026, 7, 3)
    assert hoja["E11"].value == 400


def test_la_tabla1_deja_vacias_las_columnas_sin_dato():
    # Cuenta, Organizacion y Centro de Costos todavia no se capturan: columnas
    # presentes pero sin dato, tal como se decidio.
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["C10"].value in (None, "")
    assert hoja["H10"].value in (None, "")
    assert hoja["I10"].value in (None, "")


def test_la_tabla1_calcula_el_saldo_por_formula():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # Cada fila arrastra el saldo anterior y suma el debe, resta el haber.
    assert hoja["F10"].value == "=F9+D10-E10"
    assert hoja["F11"].value == "=F10+D11-E11"


# ----------------------------------------------------------------------
# Tabla 2: partidas contables no registradas en banco
# ----------------------------------------------------------------------


def test_la_tabla2_va_despues_de_la_tabla1_con_su_titulo_y_encabezados():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["A13"].value == "Partidas contables no registradas en banco."
    esperadas = ["Fecha", "Documento", "Cuenta", "Debe", "Haber", "Saldo", "Descripción", "Organización"]
    leidas = [hoja.cell(row=14, column=i + 1).value for i in range(len(esperadas))]
    assert leidas == esperadas


def test_la_tabla2_lista_las_partidas_del_mayor_sin_par():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert _celda(hoja, "A15") == date(2026, 7, 4)
    assert hoja["B15"].value == "FCA-3"
    assert hoja["D15"].value == 300
    assert hoja["G15"].value == "ALQUILER"
    # El acumulado de la seccion arranca en cero.
    assert hoja["F15"].value == "=D15-E15"


# ----------------------------------------------------------------------
# Tabla 3: partidas en banco pendientes de registracion contable
# ----------------------------------------------------------------------


def test_la_tabla3_va_despues_de_la_tabla2():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["A17"].value == "Partidas en banco pendientes de registración contable."
    esperadas = ["Fecha", "Documento", "Cuenta", "Debe", "Haber", "Saldo", "Descripción"]
    leidas = [hoja.cell(row=18, column=i + 1).value for i in range(len(esperadas))]
    assert leidas == esperadas

    # El cargo del banco va en la columna Haber: es un debito que baja el saldo.
    assert _celda(hoja, "A19") == date(2026, 7, 5)
    assert hoja["B19"].value == "OP-9"
    assert hoja["D19"].value in (None, 0)
    assert hoja["E19"].value == 150
    assert hoja["G19"].value == "COMISION"
    assert hoja["F19"].value == "=F18+D19-E19"


def test_la_tabla3_totaliza_los_gastos_pendientes():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # La fila de total suma la columna Haber del cuadro.
    # Nueva etiqueta en columna B (Documento) y suma en columna E (Haber)
    assert hoja["B20"].value == "TOTAL SUMA DE DÉBITOS PENDIENTES"
    assert hoja["E20"].value == "=SUM(E19:E19)"


def test_la_tabla3_deja_afuera_los_pagos_operativos_pendientes():
    hoja = _mayor(
        exportador.exportar(
            _solicitud(
                pendientes_banco=[
                    {"origen": "banco", "fecha": "2026-07-05", "concepto": "COMISION", "referencia": "OP-9", "debe": 150},
                    {"origen": "banco", "fecha": "2026-07-06", "concepto": "PAGO PROVEEDOR", "referencia": "OP-10", "debe": 500},
                ]
            )
        )
    )

    # Solo la comision entra al cuadro; el pago queda afuera y el total lo ignora.
    assert hoja["G19"].value == "COMISION"
    assert hoja["E19"].value == 150
    assert hoja["G20"].value != "PAGO PROVEEDOR"
    assert hoja["B20"].value == "TOTAL SUMA DE DÉBITOS PENDIENTES"
    assert hoja["E20"].value == "=SUM(E19:E19)"


# ----------------------------------------------------------------------
# Pie de control
# ----------------------------------------------------------------------


def test_el_pie_compara_el_saldo_ajustado_con_el_del_extracto():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # Sin el cuadro de subcategorias en Libro Mayor, el pie vuelve a estar mas arriba
    assert hoja["A22"].value == "Saldo Ajustado"
    assert hoja["F22"].value == "=F11"  # ultimo saldo de la Tabla 1 (F11)
    assert hoja["A23"].value == "Saldo según Extracto"
    assert hoja["F23"].value == 850
    assert hoja["A24"].value == "Control de diferencia"
    assert hoja["F24"].value == "=F22-F23"


# ----------------------------------------------------------------------
# Hoja Movimientos Bancarios
# ----------------------------------------------------------------------


def test_la_hoja_de_movimientos_tiene_solo_las_cinco_columnas_del_resumen():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    esperadas = [
        "Fecha contable",
        "Concepto",
        "Debito en $",
        "Credito en $",
        "Saldo en $",
    ]
    leidas = [hoja.cell(row=8, column=i + 1).value for i in range(5)]

    assert leidas == esperadas
    # Las columnas que sobraban (codigos, banco, referencia, etc.) ya no van.
    assert hoja.cell(row=8, column=6).value is None


def test_la_hoja_de_movimientos_vuelca_todo_el_extracto():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    assert _celda(hoja, "A9") == date(2026, 7, 2)
    assert hoja["B9"].value == "COBRO"
    assert hoja["C9"].value == 0
    assert hoja["D9"].value == 1000

    assert _celda(hoja, "A10") == date(2026, 7, 5)
    assert hoja["B10"].value == "COMISION"
    assert hoja["C10"].value == 150


def test_la_hoja_de_movimientos_acumula_credito_menos_debito():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    assert hoja["E9"].value == "=D9-C9"
    assert hoja["E10"].value == "=E9+D10-C10"


def test_la_hoja_de_movimientos_totaliza_debitos_y_creditos_al_lado():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    # El cuadro de sumas va al lado de la tabla, en G8:H9: total de la columna
    # Debito (C) y total de la columna Credito (D).
    assert hoja["G8"].value == "Total Débitos"
    assert hoja["H8"].value == "=SUM(C9:C10)"
    assert hoja["G9"].value == "Total Créditos"
    assert hoja["H9"].value == "=SUM(D9:D10)"
    # Ya no hay una fila TOTALES abajo de la tabla.
    assert hoja["A11"].value is None


def test_la_hoja_de_movimientos_sin_filas_igual_muestra_el_cuadro():
    hoja = _movimientos(exportador.exportar(_solicitud(movimientos_banco=[])))

    # Sin movimientos el rango de las sumas queda en la unica fila: da 0.
    assert hoja["G8"].value == "Total Débitos"
    assert hoja["H8"].value == "=SUM(C9:C9)"
    assert hoja["G9"].value == "Total Créditos"
    assert hoja["H9"].value == "=SUM(D9:D9)"


def test_la_hoja_de_movimientos_no_lleva_control_de_diferencia():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    # El spec saco el control de esta pestana: no hay etiqueta ni formula que
    # mire al Libro Mayor.
    assert "Control de diferencia" not in _valores(hoja)


def test_la_hoja_de_movimientos_escribe_una_sola_vez_las_lineas_repetidas():
    hoja = _movimientos(
        exportador.exportar(
            _solicitud(
                movimientos_banco=[
                    {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000},
                    {"fecha": "2026-07-05", "concepto": "COMISION", "debe": 150, "saldo": 850},
                    {"fecha": "2026-07-05", "concepto": "COMISION", "debe": 150, "saldo": 850},
                ]
            )
        )
    )

    # La comision repetida se escribe una sola vez: la fila 11 queda libre y el
    # cuadro de sumas totaliza nada mas que las dos filas que quedaron.
    assert hoja["B10"].value == "COMISION"
    assert hoja["A11"].value is None
    assert hoja["H8"].value == "=SUM(C9:C10)"


# ----------------------------------------------------------------------
# Formatos
# ----------------------------------------------------------------------


def test_los_importes_tienen_formato_contable_de_dos_decimales():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # D10, E10, F10, F11 son las filas de la Tabla 1 (saldo inicial + 2 movimientos)
    # F11 es la ultima fila de saldo de la Tabla 1
    for coordenada in ("D10", "E10", "F10", "F11"):
        assert hoja[coordenada].number_format == FORMATO_CONTABLE


def test_las_fechas_van_en_formato_dd_mm_yyyy():
    hoja = _mayor(exportador.exportar(_solicitud()))

    assert hoja["A10"].number_format == "dd/mm/yyyy"


def test_los_encabezados_quedan_resaltados():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # El azul 00B0F0 es el de las etiquetas del propio formulario (celda A5
    # "Empresa:"). Con otro color el papel deja de parecer del mismo proceso.
    assert hoja["A5"].fill.fgColor.rgb == "FF00B0F0"
    assert hoja["A8"].fill.fgColor.rgb == "FF00B0F0"
    assert hoja["A8"].font.bold


def test_los_importes_conciliados_del_mayor_van_en_amarillo():
    hoja = _mayor(exportador.exportar(_solicitud()))

    # Las dos filas del mayor cruzaron. Cada fila trae un importe solo: se pinta
    # su celda, no las dos (FCA-1 es un debe, FCA-2 un haber).
    assert hoja["D10"].fill.fgColor.rgb == "FFFFFF00"
    assert hoja["E10"].fill.patternType is None
    assert hoja["E11"].fill.fgColor.rgb == "FFFFFF00"
    assert hoja["D11"].fill.patternType is None
    # La fila de Saldo Inicial no es un movimiento que cruce: no se pinta.
    assert hoja["D9"].fill.patternType is None
    assert hoja["E9"].fill.patternType is None


def test_una_fila_del_mayor_sin_cruzar_no_se_pinta():
    hoja = _mayor(
        exportador.exportar(
            _solicitud(
                pendientes_xubio=[
                    {
                        "origen": "xubio",
                        "fecha": "2026-07-02",
                        "comprobante": "FCA-1",
                        "concepto": "Factura 1",
                        "debe": 1000,
                    }
                ]
            )
        )
    )

    # FCA-1 (fila 10) esta en los pendientes: no se pinta. La fila 11 si
    # (FCA-2 es un haber: el amarillo va en la celda E).
    assert hoja["D10"].fill.patternType is None
    assert hoja["E10"].fill.patternType is None
    assert hoja["E11"].fill.fgColor.rgb == "FFFFFF00"
    assert hoja["D11"].fill.patternType is None


def test_la_hoja_de_movimientos_pinta_conciliados_y_pendientes():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    # COBRO (fila 9) cruzo: su credito (col. D) va en amarillo. COMISION (fila
    # 10) es un debito pendiente de registracion contable: su debito (col. C) va
    # en verde claro.
    assert hoja["D9"].fill.fgColor.rgb == "FFFFFF00"
    assert hoja["C9"].fill.patternType is None
    assert hoja["C10"].fill.fgColor.rgb == "FF93C47D"
    assert hoja["D10"].fill.patternType is None


def test_la_hoja_de_movimientos_no_pinta_un_pendiente_que_no_es_gasto():
    hoja = _movimientos(
        exportador.exportar(
            _solicitud(
                pendientes_banco=[
                    {"origen": "banco", "fecha": "2026-07-06", "concepto": "PAGO PROVEEDOR", "debe": 500}
                ],
                movimientos_banco=[
                    {"fecha": "2026-07-02", "concepto": "COBRO", "haber": 1000, "saldo": 1000},
                    {"fecha": "2026-07-06", "concepto": "PAGO PROVEEDOR", "debe": 500, "saldo": 500},
                ],
            )
        )
    )

    # Un pago pendiente no es un gasto del banco: no lleva el verde de la Seccion 3.
    assert hoja["C10"].fill.patternType is None
    assert hoja["D10"].fill.patternType is None


def test_las_columnas_de_importe_entran_los_numeros_y_no_quedan_en_piquitos():
    # Con el ancho viejo (14) un importe como 99.999.999.999,99 no entraba y
    # Excel lo tapaba con "#######". Se pide un piso de ancho y, ademas, que
    # las celdas de importe tengan shrink_to_fit como red de seguridad.
    contenido = exportador.exportar(_solicitud())
    libro = _libro(contenido)

    # El mayor guarda los importes en D/E/F; el extracto, en C/D/E.
    for hoja, columnas in (
        (_mayor(contenido), ("D", "E", "F")),
        (_movimientos(contenido), ("C", "D", "E")),
    ):
        for columna in columnas:
            ancho = hoja.column_dimensions[columna].width
            assert ancho is not None and ancho >= 18, (hoja.title, columna, ancho)

    for hoja, coordenadas in (
        (_mayor(contenido), ("D10", "E10", "F10")),
        (_movimientos(contenido), ("C9", "D9", "E10")),
    ):
        for coordenada in coordenadas:
            assert hoja[coordenada].number_format == FORMATO_CONTABLE
            assert hoja[coordenada].alignment.shrink_to_fit is True
            assert hoja[coordenada].alignment.horizontal == "right"



# ----------------------------------------------------------------------
# Casos borde
# ----------------------------------------------------------------------


def test_una_conciliacion_vacia_no_falla():
    contenido = exportador.exportar(
        _solicitud(
            movimientos_mayor=[],
            pendientes_xubio=[],
            pendientes_banco=[],
            movimientos_banco=[],
            saldo_inicial_mayor=0,
        )
    )
    hoja = _mayor(contenido)

    assert hoja["I1"].value == "FO 02-03"
    assert hoja["G9"].value == "Saldo Inicial"
    assert hoja["F9"].value == 0
    # Sin filas no hay control final con formula, pero el pie queda igual.
    assert hoja["A17"].value == "Saldo Ajustado"


def test_muchas_filas_no_se_pisan_entre_secciones():
    movimientos = [
        {
            "fecha": f"2026-07-{dia:02d}",
            "comprobante": f"FCA-{dia}",
            "concepto": f"MOV {dia}",
            "debe": dia,
        }
        for dia in range(1, 29)
    ]
    hoja = _mayor(exportador.exportar(_solicitud(movimientos_mayor=movimientos)))

    # Fila 9: saldo inicial. 28 movimientos: 10 a 37.
    assert hoja["G9"].value == "Saldo Inicial"
    assert _celda(hoja, "A10") == date(2026, 7, 1)
    assert hoja["G37"].value == "MOV 28"
    # La Tabla 2 arranca recien despues, en la 39.
    assert hoja["A39"].value == "Partidas contables no registradas en banco."


def test_un_importe_que_no_es_numero_se_rechaza_en_vez_de_ponerse_en_cero():
    # Poner 0 donde el papel de trabajo dice 500 es peor que no exportar: el
    # auditor ve una partida de importe cero y la da por buena. El schema lo
    # corta antes, con un 422 que el frontend puede mostrar.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _solicitud(
            pendientes_banco=[
                {"fecha": "2026-07-03", "concepto": "X", "debe": "no es numero"}
            ]
        )


def test_un_importe_que_viene_nan_no_rompe_el_archivo():
    # El NaN si puede pasar por JSON (Python lo serializa como NaN y el parser
    # de JavaScript lo acepta), asi que el exportador lo tiene que tolerar.
    solicitud = _solicitud(
        pendientes_banco=[
            {"fecha": "2026-07-03", "concepto": "COMISION", "debe": float("nan")}
        ]
    )
    hoja = _mayor(exportador.exportar(solicitud))

    assert hoja["E19"].value == 0
    assert hoja["F19"].value == "=F18+D19-E19"


# ----------------------------------------------------------------------
# Nombre del archivo
# ----------------------------------------------------------------------


def test_el_nombre_del_archivo_no_tiene_caracteres_que_rompan_el_sistema():
    solicitud = _solicitud(encabezado={"empresa": "ACME / S.A. \"Premium\"", "banco": "SANT"})
    nombre = exportador.nombre_archivo(solicitud, hoy=date(2026, 7, 6))

    assert nombre.startswith("FO 02-03 ")
    assert nombre.endswith("06-07-2026.xlsx")
    for prohibido in '/\\:*?"<>|':
        assert prohibido not in nombre


def test_el_nombre_usa_el_banco_cuando_no_hay_empresa():
    nombre = exportador.nombre_archivo(
        _solicitud(encabezado={"empresa": "", "banco": "GAL"}), hoy=date(2026, 7, 6)
    )

    assert "GAL" in nombre


def test_el_nombre_lleva_el_periodo_y_no_la_fecha_de_hoy():
    solicitud = _solicitud(
        encabezado={"empresa": "ACME S.A.", "banco": "SANT", "periodo": "2026-07"}
    )
    nombre = exportador.nombre_archivo(solicitud, hoy=date(2026, 10, 6))

    assert "2026-07" in nombre
    assert "06-10-2026" not in nombre


def test_sin_periodo_el_nombre_cae_a_la_fecha_de_hoy():
    solicitud = _solicitud(encabezado={"empresa": "ACME S.A.", "banco": "SANT"})
    nombre = exportador.nombre_archivo(solicitud, hoy=date(2026, 7, 6))

    assert nombre.endswith("06-07-2026.xlsx")


def test_un_periodo_con_caracteres_raros_no_rompe_el_header():
    solicitud = _solicitud(
        encabezado={"empresa": "ACME", "banco": "SANT", "periodo": "2026/07\nX-Injected: 1"}
    )
    nombre = exportador.nombre_archivo(solicitud, hoy=date(2026, 7, 6))

    for prohibido in '/\\:*?"<>|\r\n':
        assert prohibido not in nombre


def test_falta_la_plantilla_da_un_error_que_se_entiende(monkeypatch):
    monkeypatch.setattr(exportador, "ruta_plantilla", lambda: exportador.DIRECTORIO_PLANTILLAS / "no-existe.xlsx")

    with pytest.raises(FileNotFoundError):
        exportador.exportar(_solicitud())
