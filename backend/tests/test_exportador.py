"""Tests del papel de trabajo FO 02-03.

Cada test vuelve a leer el .xlsx generado con openpyxl. No se chequea que el
archivo "no este vacio": se chequean las celdas donde caeria cada dato, porque
un archivo que se abre y esta vacio pasa cualquier prueba de bytes.
"""

import io
from datetime import date, datetime

import openpyxl
import pytest

from app.models.schemas import SolicitudExportacion
from app.services import exportador


def _libro(contenido: bytes):
    return openpyxl.load_workbook(io.BytesIO(contenido))


def _movimientos(contenido: bytes):
    """La hoja de los tres bloques lado a lado."""
    return openpyxl.load_workbook(io.BytesIO(contenido))["Movimientos Bancarios"]


def _celda(hoja, coordenada: str):
    """La celda, con la fecha como date y no como datetime.

    Al releer el archivo, openpyxl devuelve datetime para cualquier celda con
    formato de fecha, aunque lo escrito haya sido un date. Comparar contra un
    date sin normalizar hace fallar la prueba por una diferencia de tipo que no
    existe en la hoja.
    """
    celda = hoja[coordenada]
    if isinstance(celda.value, datetime):
        celda.value = celda.value.date()
    return celda.value


def _solicitud(**cambios) -> SolicitudExportacion:
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
                "concepto_banco": "COBRO CLIENTE",
                "concepto_xubio": "Factura 1001",
                "debe": 0,
                "haber": 1000,
                "saldo": 1000,
                "importe": 1000,
                "categoria": "operativo",
            }
        ],
        "pendientes_banco": [
            {
                "origen": "banco",
                "fecha": "2026-07-03",
                "concepto": "COMISION",
                "debe": 150,
                "haber": 0,
                "saldo": 350,
                "categoria": "impuesto",
            }
        ],
        "pendientes_xubio": [
            {"origen": "xubio", "fecha": "2026-07-04", "concepto": "ALQUILER", "debe": 300}
        ],
    }
    base.update(cambios)
    return SolicitudExportacion.model_validate(base)


# ----------------------------------------------------------------------
# El membrete
# ----------------------------------------------------------------------


def test_conserva_el_membrete_de_la_plantilla():
    libro = _libro(exportador.exportar(_solicitud()))
    hoja = libro["Libro Mayor"]

    # Si el exportador rehace el archivo en vez de partir de la plantilla, esto
    # es lo primero que se pierde: el formulario con su codigo y su revision.
    assert hoja["I1"].value == "FO 02-03"
    assert hoja["I2"].value == "Rev 0"
    assert "Papeles de Trabajo" in hoja["C2"].value
    assert hoja["A10"].value == "Partidas contables no registradas en banco."
    assert (
        hoja["A18"].value
        == "Partidas en banco pendientes de registración contable."
    )


def test_escribe_empresa_banco_cuenta_y_periodo():
    hoja = _libro(exportador.exportar(_solicitud()))["Libro Mayor"]

    assert hoja["B5"].value == "ACME S.A."
    assert hoja["B6"].value == "SANT"
    assert hoja["I6"].value == "0001234"
    # La celda del periodo tiene formato 'mmmm yyyy': tiene que ser una fecha
    # de Excel, no el texto "2026-07", o el papel muestra un string.
    assert _celda(hoja, "I5") == date(2026, 7, 1)


def test_la_hoja_de_movimientos_sigue_al_membrete_por_formula():
    hoja = _libro(exportador.exportar(_solicitud()))["Movimientos Bancarios"]

    # Estas cuatro son formulas de la plantilla, no valores. Si se exportaran
    # como texto, la segunda hoja dejaria de seguir a la primera.
    assert hoja["B5"].value == "=+'Libro Mayor'!B5"
    assert hoja["B6"].value == "=+'Libro Mayor'!B6"
    assert hoja["I5"].value == "=+'Libro Mayor'!I5"
    assert hoja["I6"].value == "=+'Libro Mayor'!I6"


def test_un_periodo_que_no_se_entiende_se_escribe_como_venia():
    hoja = _libro(exportador.exportar(_solicitud(encabezado={"periodo": "julio 26"})))[
        "Libro Mayor"
    ]

    assert hoja["I5"].value == "julio 26"


def test_sin_periodo_la_celda_queda_vacia():
    hoja = _libro(exportador.exportar(_solicitud(encabezado={"periodo": None})))[
        "Libro Mayor"
    ]

    assert hoja["I5"].value is None


# ----------------------------------------------------------------------
# Las dos secciones del Libro Mayor
# ----------------------------------------------------------------------


def test_las_partidas_de_xubio_caen_en_la_primera_seccion():
    hoja = _libro(exportador.exportar(_solicitud()))["Libro Mayor"]

    assert hoja["A11"].value == "Fecha"
    assert hoja["B11"].value == "Concepto"
    assert hoja["C11"].value == "Debe"
    assert hoja["D11"].value == "Haber"
    assert hoja["E11"].value == "Importe"

    assert _celda(hoja, "A12") == date(2026, 7, 4)
    assert hoja["B12"].value == "ALQUILER"
    assert hoja["C12"].value == 300
    # El signo del libro mayor va al revés que el del banco: un DEBE de Xubio
    # es una entrada, y por eso el importe queda positivo.
    assert hoja["E12"].value == 300


def test_las_partidas_del_banco_caen_en_la_segunda_seccion():
    hoja = _libro(exportador.exportar(_solicitud()))["Libro Mayor"]

    assert hoja["B19"].value == "Concepto"
    assert _celda(hoja, "A20") == date(2026, 7, 3)
    assert hoja["B20"].value == "COMISION"
    assert hoja["C20"].value == 150
    # En el banco el DEBE es una salida: por eso el importe va con signo menos.
    assert hoja["E20"].value == -150


def test_cada_seccion_totaliza_sus_propias_filas():
    solicitud = _solicitud(
        pendientes_banco=[
            {"fecha": "2026-07-03", "concepto": "COMISION", "debe": 150, "saldo": 350},
            {"fecha": "2026-07-04", "concepto": "COMISION 2", "debe": 50, "saldo": 300},
        ],
        pendientes_xubio=[
            {"origen": "xubio", "fecha": "2026-07-05", "concepto": "ALQUILER", "debe": 300},
            {"origen": "xubio", "fecha": "2026-07-06", "concepto": "LUZ", "debe": 80},
        ],
    )
    hoja = _libro(exportador.exportar(solicitud))["Libro Mayor"]

    # Seccion de Xubio: filas 12 y 13, total en 14.
    assert hoja["C14"].value == 380
    assert hoja["E14"].value == 380
    # Seccion del banco: filas 20 y 21, total en 22.
    assert hoja["C22"].value == 200
    assert hoja["E22"].value == -200


def test_una_seccion_sin_filas_no_inventa_una_fila_de_total():
    hoja = _libro(exportador.exportar(_solicitud(pendientes_banco=[])))["Libro Mayor"]

    assert hoja["A20"].value is None
    assert hoja["B21"].value is None


def test_los_bloques_de_movimientos_totalizan_el_importe():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    # Bloque de Movimientos Bancarios: una sola fila, total en la 10.
    assert hoja["B10"].value == "Total"
    assert hoja["C10"].value == 150
    assert hoja["E10"].value == -150
    # Bloque de Libro Mayor: la partida de Xubio, total en la 10 de AE.
    assert hoja["AG10"].value == 300
    assert hoja["AI10"].value == 300


def test_el_bloque_de_movimientos_no_suma_el_saldo():
    hoja = _movimientos(exportador.exportar(_solicitud()))

    # El Saldo es un acumulado: sumarlo daria un numero sin significado y
    # dejaria una cifra que no cuadra con nada.
    assert hoja["F10"].value is None


def test_la_fecha_se_acepta_en_los_dos_formatos_que_manda_el_cruce():
    hoja = _libro(
        exportador.exportar(
            _solicitud(
                pendientes_banco=[
                    {"fecha": "03/07/2026", "concepto": "COMISION", "debe": 1, "saldo": 1},
                    {"fecha": "2026-07-05", "concepto": "OTRA", "debe": 2, "saldo": 1},
                ]
            )
        )
    )["Libro Mayor"]

    assert _celda(hoja, "A20") == date(2026, 7, 3)
    assert _celda(hoja, "A21") == date(2026, 7, 5)


def test_un_importe_que_no_es_numero_se_rechaza_en_vez_de_ponerse_en_cero():
    # Poner 0 donde el papel de trabajo dice 500 es peor que no exportar: el
    # auditor ve una partida de importe cero y la da por buena. El schema lo
    # corta antes, con un 422 que el frontend puede mostrar.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _solicitud(
            pendientes_banco=[
                {"fecha": "2026-07-03", "concepto": "X", "debe": "no es numero", "saldo": 1}
            ]
        )


def test_un_importe_que_viene_nan_no_rompe_el_archivo():
    # El NaN si puede pasar por JSON (Python lo serializa como NaN y el parser
    # de JavaScript lo acepta), asi que el exportador lo tiene que tolerar.
    solicitud = _solicitud(
        pendientes_banco=[
            {"fecha": "2026-07-03", "concepto": "X", "debe": float("nan"), "saldo": 1}
        ]
    )
    hoja = _libro(exportador.exportar(solicitud))["Libro Mayor"]

    assert hoja["C20"].value == 0
    assert hoja["E20"].value == 0


# ----------------------------------------------------------------------
# Los tres bloques de la hoja Movimientos Bancarios
# ----------------------------------------------------------------------


def test_los_tres_bloques_empiezan_en_las_columnas_del_membrete():
    hoja = _libro(exportador.exportar(_solicitud()))["Movimientos Bancarios"]

    assert hoja["A7"].value == "Movimientos Bancarios"
    assert hoja["AE7"].value == "Libro Mayor"
    assert hoja["BI7"].value == "Conciliación"


def test_cada_bloque_tiene_las_ocho_columnas():
    hoja = _libro(exportador.exportar(_solicitud()))["Movimientos Bancarios"]

    esperadas = ["Fecha", "Concepto", "Debe", "Haber", "Importe", "Saldo", "Categoría", "Origen"]
    for columna_base in (1, 31, 61):
        leidas = [
            hoja.cell(row=8, column=columna_base + i).value for i in range(len(esperadas))
        ]
        assert leidas == esperadas


def test_el_bloque_del_banco_lleva_saldo_categoria_y_origen():
    hoja = _libro(exportador.exportar(_solicitud()))["Movimientos Bancarios"]

    assert _celda(hoja, "A9") == date(2026, 7, 3)
    assert hoja["B9"].value == "COMISION"
    assert hoja["C9"].value == 150
    assert hoja["E9"].value == -150
    assert hoja["F9"].value == 350
    assert hoja["G9"].value == "Impuesto"
    assert hoja["H9"].value == "Banco"


def test_el_bloque_de_xubio_no_inventa_saldo_ni_categoria():
    # El cruce con Xubio no manda saldo ni categoria: si se escriben vacios,
    # el papel muestra una columna de ceros que parece un dato real.
    hoja = _libro(exportador.exportar(_solicitud()))["Movimientos Bancarios"]

    assert _celda(hoja, "AE9") == date(2026, 7, 4)
    assert hoja["AF9"].value == "ALQUILER"
    assert hoja["AI9"].value == 300
    assert hoja["AJ9"].value is None
    assert hoja["AK9"].value is None
    assert hoja["AL9"].value == "Libro Mayor"


def test_el_bloque_de_conciliados_distingue_el_cruce_del_pareo_a_mano():
    solicitud = _solicitud(
        conciliados=[
            {
                "fecha": "2026-07-01",
                "concepto_banco": "COBRO",
                "concepto_xubio": "Factura 1",
                "debe": 0,
                "haber": 1000,
                "saldo": 1000,
                "categoria": "operativo",
            },
            {
                "fecha": "2026-07-02",
                "concepto_banco": "PAGO",
                "concepto_xubio": "Factura 2",
                "debe": 500,
                "haber": 0,
                "saldo": 500,
                "manual": True,
                "diferencia": -20,
            },
        ]
    )
    hoja = _libro(exportador.exportar(solicitud))["Movimientos Bancarios"]

    assert _celda(hoja, "BI9") == date(2026, 7, 1)
    assert hoja["BJ9"].value == "COBRO / Factura 1"
    assert hoja["BP9"].value == "Automático"

    # Un par a mano con diferencia tiene que quedar a la vista: en el papel de
    # trabajo es la diferencia entre lo que dijo el banco y lo que dijo Xubio.
    assert hoja["BJ10"].value == "PAGO / Factura 2"
    assert hoja["BP10"].value == "A mano (dif. -20.00)"


def test_un_par_a_mano_sin_diferencia_no_muestra_el_diferencial():
    solicitud = _solicitud(
        conciliados=[
            {
                "fecha": "2026-07-02",
                "concepto_banco": "PAGO",
                "concepto_xubio": "Factura 2",
                "debe": 500,
                "saldo": 500,
                "manual": True,
                "diferencia": 0,
            }
        ]
    )
    hoja = _libro(exportador.exportar(solicitud))["Movimientos Bancarios"]

    assert hoja["BP9"].value == "A mano"


def test_el_importe_de_un_par_se_recalcula_si_no_vino():
    # El frontend manda 'importe' con el signo ya unificado. Si no lo manda,
    # sale del debe/haber del banco: un par con 0 de debe y 1000 de haber es
    # un ingreso de 1000.
    solicitud = _solicitud(
        conciliados=[
            {
                "fecha": "2026-07-01",
                "concepto_banco": "COBRO",
                "concepto_xubio": "Factura 1",
                "debe": 0,
                "haber": 1000,
                "saldo": 1000,
            }
        ]
    )
    hoja = _libro(exportador.exportar(solicitud))["Movimientos Bancarios"]

    assert hoja["BM9"].value == 1000


def test_los_formatos_de_importe_y_fecha_vienen_de_la_plantilla():
    hoja = _libro(exportador.exportar(_solicitud()))["Libro Mayor"]

    assert "#,##0.00" in hoja["C20"].number_format
    assert hoja["A20"].number_format == "dd/mm/yyyy"


def test_los_encabezados_de_columna_quedan_resaltados():
    hoja = _libro(exportador.exportar(_solicitud()))["Libro Mayor"]

    # El azul 00B0F0 es el de las etiquetas del propio formulario (celda A5
    # "Empresa:"). Con otro color el papel deja de parecer del mismo proceso.
    assert hoja["A5"].fill.fgColor.rgb == "FF00B0F0"
    assert hoja["A11"].fill.fgColor.rgb == "FF00B0F0"
    assert hoja["A11"].font.bold


# ----------------------------------------------------------------------
# Casos borde
# ----------------------------------------------------------------------


def test_una_conciliacion_vacia_no_falla():
    contenido = exportador.exportar(_solicitud(conciliados=[], pendientes_banco=[], pendientes_xubio=[]))
    hoja = _libro(contenido)["Libro Mayor"]

    assert hoja["I1"].value == "FO 02-03"
    assert hoja["A12"].value is None


def test_muchas_filas_no_se_pisan_entre_sections():
    pendientes = [
        {"fecha": f"2026-07-{dia:02d}", "concepto": f"MOV {dia}", "debe": dia, "saldo": 1000 - dia}
        for dia in range(1, 29)
    ]
    hoja = _libro(exportador.exportar(_solicitud(pendientes_banco=pendientes)))["Libro Mayor"]

    # 28 filas arrancan en la 20 y terminan en la 47; el total va en la 48 y no
    # puede pisarse con la segunda seccion, que arranca en la 18.
    assert hoja["B47"].value == "MOV 28"
    assert hoja["B48"].value == "Total"
    assert hoja["C48"].value == sum(range(1, 29))


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
    # Si el nombre dice la fecha en que se bajo el archivo, cinco
    # conciliaciones del mismo dia son cinco archivos iguales de nombre. El
    # periodo es lo que las distingue.
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
    # El header HTTP no admite "/" ni saltos de linea: un periodo tecleado con
    # barra rompe la descarga en el navegador, no en Python.
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