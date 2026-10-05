"""
Tests del pipeline de extractos.

La idea es que cada bug que encontramos tenga un test que lo vuelva a romper si
alguien lo reintroduce. Los que mas importan:

  - el SALDO que los extractores escriben como formula de Excel nunca se evalua
  - TrackerSaldo esta incompleto y sin el los bancos CMF, RIO, SUPV y PBA dies
  - limpiar_numero no tenia el parametro es_formato_ingles y HIPO y PBA hacian
    TypeError al llamarlo
  - xubio no estaba en el router, asi que sus rutas daban 404
  - el cruce con Xubio multiplicaba las filas por cantidad, no por movimiento

Para correr los extractores contra un PDF real hay que pasar la variable de
entorno PDF_BANCO_TEST con la ruta y BANCO_TEST con el codigo del banco.
"""

import base64
import os
import re
from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

from app.models.schemas import MovimientoBancario
from app.services.Tools import TrackerSaldo, es_numero_bancario, limpiar_numero
from app.services.bancos import (
    BcoBBK,
    BcoBBVA,
    BcoCMF,
    BcoGAL,
    BcoHIPO,
    BcoICBC,
    BcoMP,
    BcoPBA,
    BcoRIO,
    BcoSUPV,
)
from app.services.conciliador import conciliar_movimientos
from app.services.procesador_central import (
    BANCOS,
    ErrorDeExtraccion,
    _df_to_movimientos,
    procesar_archivo,
)


# --------------------------------------------------------------------------
# Tools: limpiar_numero
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("1.234,56", 1234.56),
        ("$ 1.234,56", 1234.56),
        ("-$ 29.000,00", -29000.0),
        ("1,234.56", 1234.56),
        ("29.000,00", 29000.0),
        ("0,00", 0.0),
        ("-49728.18", -49728.18),
        ("", 0.0),
        (None, 0.0),
        ("$", 0.0),
    ],
)
def test_limpiar_numero_lee_las_dos_convenciones(entrada, esperado):
    assert limpiar_numero(entrada) == pytest.approx(esperado)


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("-49728.18", -49728.18),
        ("1,234.56", 1234.56),
        ("1234.56", 1234.56),
    ],
)
def test_limpiar_numero_con_formato_ingles(entrada, esperado):
    # BcoHIPO y BcoPBA llaman limpiar_numero con es_formato_ingles=True.
    # Sin este parametro, ambos bancos reventaban con TypeError.
    assert limpiar_numero(entrada, es_formato_ingles=True) == pytest.approx(esperado)


def test_limpiar_numero_trata_nan_como_vacio():
    nan = float("nan")
    assert limpiar_numero(nan) == 0.0


def test_limpiar_numero_acepta_el_parametro_ingles_por_posicion():
    # Por si algun extractor lo pasa posicional
    assert limpiar_numero("1,234.56", True) == pytest.approx(1234.56)


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("1.234", True),
        ("$ 100,50", True),
        ("-500", True),
        ("", False),
        (None, False),
        ("PAGO", False),
        ("$", False),
    ],
)
def test_es_numero_bancario(entrada, esperado):
    assert es_numero_bancario(entrada) is esperado


# --------------------------------------------------------------------------
# Tools: TrackerSaldo
# --------------------------------------------------------------------------


def test_tracker_arranca_en_cero_y_necesita_iniciar():
    tracker = TrackerSaldo()
    assert tracker.saldo_actual == 0.0
    with pytest.raises(RuntimeError):
        tracker.identificar_movimiento(1000.0, 9000.0)


def test_tracker_detecta_debe_y_haber():
    tracker = TrackerSaldo()
    tracker.iniciar(100000.0)

    assert tracker.identificar_movimiento(25000.0, 75000.0) == "DEBE"
    assert tracker.saldo_actual == 75000.0

    assert tracker.identificar_movimiento(10000.0, 85000.0) == "HABER"
    assert tracker.saldo_actual == 85000.0


def test_tracker_tolera_redondeo_del_banco():
    tracker = TrackerSaldo()
    tracker.iniciar(1000.0)
    # El banco redondeo un centavo: sigue siendo el mismo movimiento
    assert tracker.identificar_movimiento(100.01, 899.99) == "DEBE"


def test_tracker_devuelve_none_cuando_no_cuadra_y_no_avanza():
    tracker = TrackerSaldo()
    tracker.iniciar(100000.0)

    # No hay forma de llegar de 100000 a 123456 con un importe de 1000
    assert tracker.identificar_movimiento(1000.0, 123456.0) is None
    # Clave: el saldo sigue en el ultimo valor bueno, asi la linea siguiente
    # todavia puede compararse contra el.
    assert tracker.saldo_actual == 100000.0
    assert tracker.descartes == 1


def test_tracker_sigue_cuadrando_despues_de_un_descarte():
    tracker = TrackerSaldo()
    tracker.iniciar(50000.0)
    assert tracker.identificar_movimiento(99999.0, 1.0) is None
    assert tracker.identificar_movimiento(5000.0, 45000.0) == "DEBE"


# --------------------------------------------------------------------------
# El SALDO como formula de Excel
# --------------------------------------------------------------------------


def _roundtrip(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reproduce el viaje real: el extractor escribe el xlsx y el procesador lo relee.

    Es importante pasar por el archivo porque ahi es donde la formula de Excel se
    convierte en vacio: pandas lee con data_only=True y openpyxl no calcula.
    """
    ruta = os.path.join(os.path.dirname(__file__), "_roundtrip.xlsx")
    df.to_excel(ruta, index=False)
    try:
        releido = pd.read_excel(ruta)
        return releido
    finally:
        if os.path.exists(ruta):
            os.remove(ruta)


def test_la_formula_de_excel_vuelve_vacia():
    """
    Este es el bug de fondo: los 10 extractores escriben SALDO como
    '=F2-E3+D3'. Al releerlo no hay ningun valor. Hay que dejarlo explicito
    para que nadie vuelva a confiar en persistir esa formula.
    """
    df = pd.DataFrame(
        [
            {"CUENTA": "C", "FECHA": "", "DETALLE": "SALDO INICIAL",
             "DEBE": 0.0, "HABER": 0.0, "SALDO": 100000.0},
            {"CUENTA": "C", "FECHA": "02/07/2026", "DETALLE": "Compra",
             "DEBE": 25000.0, "HABER": 0.0, "SALDO": "=F2-E3+D3"},
        ]
    )
    releido = _roundtrip(df)

    assert releido["SALDO"].isna().tolist() == [False, True]
    # Por eso el saldo hay que recalcularlo, no leerlo
    assert pd.isna(releido["SALDO"].iloc[1])


def test_saldo_se_recalcula_a_partir_de_debe_y_haber():
    df = pd.DataFrame(
        [
            {"CUENTA": "C", "FECHA": "", "DETALLE": "SALDO INICIAL",
             "DEBE": 0.0, "HABER": 0.0, "SALDO": 100000.0},
            {"CUENTA": "C", "FECHA": "02/07/2026", "DETALLE": "Compra",
             "DEBE": 25000.0, "HABER": 0.0, "SALDO": "=F2-E3+D3"},
            {"CUENTA": "C", "FECHA": "03/07/2026", "DETALLE": "Venta",
             "DEBE": 0.0, "HABER": 10000.0, "SALDO": "=F3-E4+D4"},
            {"CUENTA": "C", "FECHA": "04/07/2026", "DETALLE": "Alquiler",
             "DEBE": 80000.0, "HABER": 0.0, "SALDO": "=F4-E5+D5"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "TEST")

    # La fila de saldo inicial no se emite: solo siembra la cadena. Lo que se
    # verifica es que el saldo de apertura (100000) se aplico bien.
    # 100000 - 25000 + 10000 - 80000 = 5000
    assert [m.saldo for m in movimientos] == [75000.0, 85000.0, 5000.0]
    assert movimientos[-1].fecha == date(2026, 7, 4)


def test_la_fila_de_saldo_inicial_no_se_emite_como_movimiento():
    """
    La fila de saldo inicial no es un movimiento: no tiene DEBE ni HABER y nunca
    va a cruzar con Xubio, asi que emitirla deja una fila 0/00 perpetua en la
    bandeja de pendientes. El saldo de apertura sigue disponible yendo al
    primer movimiento y desandolo.
    """
    df = pd.DataFrame(
        [
            {"FECHA": "", "DETALLE": "SALDO ULTIMO EXTRACTO AL 30/06/2026",
             "DEBE": 0.0, "HABER": 0.0, "SALDO": 5000.0},
            {"FECHA": "15/08/2026", "DETALLE": "Transferencia", "DEBE": 0.0,
             "HABER": 1000.0, "SALDO": "=E2+C3-D3"},
            {"FECHA": "16/08/2026", "DETALLE": "Pago", "DEBE": 500.0,
             "HABER": 0.0, "SALDO": "=E3+C4-D4"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "TEST")

    assert [m.concepto for m in movimientos] == ["Transferencia", "Pago"]
    assert [m.saldo for m in movimientos] == [6000.0, 5500.0]
    # El saldo de apertura se sigue pudiendo deducir del primer movimiento.
    primero = movimientos[0]
    assert primero.saldo + primero.debe - primero.haber == pytest.approx(5000.0)


def test_una_fila_marcada_como_saldo_inicial_con_importe_es_un_movimiento():
    """
    Si un banco marca la fila de saldo inicial pero le pone un importe, el
    importe manda: la fila es un movimiento real y descartarla seria perder
    plata del extracto.
    """
    df = pd.DataFrame(
        [
            {"FECHA": "02/07/2026", "DETALLE": "SALDO INICIAL", "DEBE": 250.0,
             "HABER": 0.0, "SALDO": "=E2+C3-D3"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "TEST")

    assert len(movimientos) == 1
    assert movimientos[0].debe == pytest.approx(250.0)


def test_la_fila_de_saldo_inicial_no_inventa_la_fecha_de_hoy():
    # El saldo inicial no tiene fecha propia y antes se le ponia la fecha de
    # hoy, que hacia que un extracto de julio pareciera de octubre. Hoy la fila
    # no se emite, asi que el problema es estructuralmente imposible: lo que
    # queda es que ningun movimiento tome una fecha que no sea la suya.
    df = pd.DataFrame(
        [
            {"FECHA": "", "DETALLE": "SALDO INICIAL", "DEBE": 0.0,
             "HABER": 0.0, "SALDO": 5000.0},
            {"FECHA": "15/08/2026", "DETALLE": "Transferencia", "DEBE": 0.0,
             "HABER": 1000.0, "SALDO": "=E2+C3-D3"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "TEST")

    assert [m.fecha for m in movimientos] == [date(2026, 8, 15)]


def test_saldo_no_drift_con_centavos():
    df = pd.DataFrame(
        [
            {"FECHA": "", "DETALLE": "SALDO INICIAL", "DEBE": 0.0,
             "HABER": 0.0, "SALDO": 0.10},
            {"FECHA": "02/07/2026", "DETALLE": "A", "DEBE": 0.10,
             "HABER": 0.0, "SALDO": "=E2+C3-D3"},
            {"FECHA": "03/07/2026", "DETALLE": "B", "DEBE": 0.0,
             "HABER": 0.10, "SALDO": "=E3+C4-D4"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "TEST")
    # 0.10 - 0.10 + 0.10 = 0.10, sin error de coma flotante
    assert movimientos[-1].saldo == pytest.approx(0.10)


def test_columna_importe_con_signo_de_mercadopago():
    # BcoMP no usa DEBE/HABER: trae una sola columna IMPORTE con el signo.
    df = pd.DataFrame(
        [
            {"FECHA": "", "DETALLE": "SALDO ANTERIOR (Automatico)",
             "ID_OPERACION": "-", "IMPORTE": 0.0, "SALDO": 30000.0},
            {"FECHA": "02/07/2026", "DETALLE": "Cobro", "ID_OPERACION": "12345",
             "IMPORTE": 5000.0, "SALDO": "=E2+D3"},
            {"FECHA": "03/07/2026", "DETALLE": "Pago", "ID_OPERACION": "12346",
             "IMPORTE": -1500.0, "SALDO": "=E3+D4"},
        ]
    )
    movimientos = _df_to_movimientos(_roundtrip(df), "MP")

    assert movimientos[0].haber == 5000.0 and movimientos[0].debe == 0.0
    assert movimientos[1].debe == 1500.0 and movimientos[1].haber == 0.0
    assert movimientos[0].referencia == "12345"
    assert [m.saldo for m in movimientos] == [35000.0, 33500.0]


def test_error_cuando_ninguna_fila_tiene_fecha():
    df = pd.DataFrame(
        [
            {"FECHA": "S/D", "DETALLE": "SALDO INICIAL", "DEBE": 0.0,
             "HABER": 0.0, "SALDO": 100.0},
            {"FECHA": "S/D", "DETALLE": "Algo", "DEBE": 10.0,
             "HABER": 0.0, "SALDO": "=E2+C3-D3"},
        ]
    )
    with pytest.raises(ErrorDeExtraccion, match="fecha"):
        _df_to_movimientos(_roundtrip(df), "TEST")


def test_error_cuando_faltan_las_columnas_base():
    with pytest.raises(ErrorDeExtraccion, match="columnas"):
        _df_to_movimientos(pd.DataFrame({"OTRA": [1, 2, 3]}), "TEST")


def test_excel_sin_columnas_falla_con_mensaje_util():
    # Un DataFrame sin columnas no puede venir de un extractor: hay que decirlo,
    # no devolver una lista vacia que parece un extracto sin movimientos.
    with pytest.raises(ErrorDeExtraccion, match="columnas"):
        _df_to_movimientos(pd.DataFrame(), "TEST")


# --------------------------------------------------------------------------
# procesar_archivo
# --------------------------------------------------------------------------


def test_banco_no_soportado_falla_con_mensaje_util():
    with pytest.raises(ValueError, match="no esta soportado"):
        procesar_archivo(banco_id="NARANJA", ruta_pdf="no-importa.pdf")


def test_bancos_tienen_los_once_registrados():
    esperados = {
        "BBK", "BBVA", "CMF", "GAL", "HIPO", "ICBC", "MP", "PBA", "RIO", "SANT",
        "SUPV",
    }
    assert set(BANCOS) == esperados


def test_pdf_inexistente_falla_en_vez_de_devolver_vacio():
    # Antes un archivo que no existia terminaba en una lista vacia con exito.
    with pytest.raises(ErrorDeExtraccion, match="No se encuentra"):
        procesar_archivo(banco_id="BBVA", ruta_pdf="no-existe-jamas.pdf")


# --------------------------------------------------------------------------
# Cruce con Xubio
# --------------------------------------------------------------------------


def _mov(fecha: date, debe=0.0, haber=0.0, concepto="x", saldo=0.0):
    return MovimientoBancario(
        fecha=fecha, concepto=concepto, debe=debe, haber=haber, saldo=saldo
    )


def test_el_cruce_no_multiplica_filas():
    """
    El merge anterior cruzaba solo por monto. Con 3 movimientos iguales en el
    banco y 2 en Xubio devolvia 6 filas, todas marcadas como conciliadas.
    """
    banco = [
        _mov(date(2026, 7, 1), debe=50000.0),
        _mov(date(2026, 7, 2), debe=50000.0),
        _mov(date(2026, 7, 3), debe=50000.0),
    ]
    xubio = [
        {"fecha": "2026-07-01", "concepto": "Pago 1", "debe": 0.0, "haber": 50000.0},
        {"fecha": "2026-07-03", "concepto": "Pago 3", "debe": 0.0, "haber": 50000.0},
    ]

    resultado = conciliar_movimientos(banco, xubio)

    assert len(resultado["conciliados"]) == 2
    assert len(resultado["pendientes_banco"]) == 1
    assert resultado["pendientes_banco"][0]["fecha"] == date(2026, 7, 2)
    assert resultado["pendientes_xubio"] == []


def test_el_cruce_exige_que_la_fecha_este_cerca():
    banco = [_mov(date(2026, 7, 1), debe=50000.0)]
    lejanisimo = [{"fecha": "2026-09-20", "concepto": "Otro mes", "debe": 0.0, "haber": 50000.0}]

    assert conciliar_movimientos(banco, lejanisimo)["conciliados"] == []

    cerca = [{"fecha": "2026-07-02", "concepto": "Mismo periodo", "debe": 0.0, "haber": 50000.0}]
    assert len(conciliar_movimientos(banco, cerca)["conciliados"]) == 1


def test_el_cruce_es_uno_a_uno():
    banco = [_mov(date(2026, 7, 1), debe=1000.0)]
    xubio = [
        {"fecha": "2026-07-01", "concepto": "A", "debe": 0.0, "haber": 1000.0},
        {"fecha": "2026-07-01", "concepto": "B", "debe": 0.0, "haber": 1000.0},
    ]
    resultado = conciliar_movimientos(banco, xubio)

    assert len(resultado["conciliados"]) == 1
    assert len(resultado["pendientes_xubio"]) == 1


def test_cruce_con_listas_vacias():
    vacio = conciliar_movimientos([], [])
    assert vacio["conciliados"] == []

    solo_banco = conciliar_movimientos([_mov(date(2026, 7, 1), debe=10.0)], [])
    assert len(solo_banco["pendientes_banco"]) == 1
    assert solo_banco["conciliados"] == []


def test_el_cruce_no_mezcla_centavos():
    # El cruce con el mayor de Xubio exige el centimo exacto: si el banco y la
    # contabilidad no dicen lo mismo, la diferencia tiene que quedar a la vista
    # en las bandejas de pendientes. Ojo que esto es distinto del redondeo que
    # tolera TrackerSaldo al leer el extracto, que solo deduce el signo de cada
    # linea y por eso puede perdonar un centavo.
    banco = [_mov(date(2026, 7, 1), debe=1000.0)]
    xubio = [{"fecha": "2026-07-01", "concepto": "Distinto", "debe": 0.0, "haber": 1000.01}]
    resultado = conciliar_movimientos(banco, xubio)

    assert resultado["conciliados"] == []
    # Y no se pierde ninguno de los dos: cada uno cae en su bandeja.
    assert len(resultado["pendientes_banco"]) == 1
    assert len(resultado["pendientes_xubio"]) == 1


def test_importe_con_signo_del_banco():
    # Un DEBE del banco es salida de plata
    assert conciliar_movimientos(
        [_mov(date(2026, 7, 1), debe=100.0)], []
    )["pendientes_banco"][0]["importe"] == -100.0
    # Un HABER del banco es entrada
    assert conciliar_movimientos(
        [_mov(date(2026, 7, 1), haber=100.0)], []
    )["pendientes_banco"][0]["importe"] == 100.0


def test_la_convencion_de_debe_y_haber_no_se_puede_invertir():
    """
    Este es el contrato que tienen que cumplir los 11 extractores.

    DEBE es la plata que SALE de la cuenta y HABER la que ENTRA. No es una
    cuestion de gusto: el conciliador arma el importe del banco como
    haber - debe, asi que si un extractor manda el signo al reves, un pago del
    banco aparece como un ingreso, no cruza nunca con el mayor de Xubio y el
    extracto entero queda en la bandeja de pendientes sin avisar.

    BBK, ICBC, HIPO y PBA mandaban el signo al reves y quedaron arreglados. Este
    test es el que dice cual es el lado correcto; cuando aparezca un PDF real de
    alguno de esos bancos, el test del extractor mas el descuadre del
    procesador lo confirman.

    Las dos formas son validas: dos columnas (DEBE/HABER) o una sola columna
    IMPORTE con el signo puesto, que es como viene Mercado Pago.
    """
    from app.services.procesador_central import _importes

    dos_columnas = pd.DataFrame([{"DEBE": 100.0, "HABER": 0.0}])
    assert _importes(dos_columnas.iloc[0]) == (100.0, 0.0)

    dos_columnas_entra = pd.DataFrame([{"DEBE": 0.0, "HABER": 100.0}])
    assert _importes(dos_columnas_entra.iloc[0]) == (0.0, 100.0)

    # Una sola columna con signo: el negativo es plata que sale.
    una_columna_sale = pd.DataFrame([{"IMPORTE": -100.0}])
    assert _importes(una_columna_sale.iloc[0]) == (100.0, 0.0)

    una_columna_entra = pd.DataFrame([{"IMPORTE": 100.0}])
    assert _importes(una_columna_entra.iloc[0]) == (0.0, 100.0)

    # Y el signo unificado del banco sale de ahi: DEBE resta, HABER suma.
    assert conciliar_movimientos(
        [_mov(date(2026, 7, 1), debe=100.0)], []
    )["pendientes_banco"][0]["importe"] < 0
    assert conciliar_movimientos(
        [_mov(date(2026, 7, 1), haber=100.0)], []
    )["pendientes_banco"][0]["importe"] > 0


# --------------------------------------------------------------------------
# Credenciales de Xubio
# --------------------------------------------------------------------------


def test_el_basic_es_id_y_secreto_en_base64(monkeypatch):
    """
    Basic exige base64 de 'id:secreto'. Mandar el secreto suelto, o el secreto
    con un pregio pegado, hace que la API devuelva 401 sin explicar por que.
    """
    from app.core import config
    from app.services.xubio_client import XubioClient

    monkeypatch.setattr(config.settings, "XUBIO_CLIENT_ID", "mi_usuario")
    monkeypatch.setattr(config.settings, "XUBIO_CLIENT_SECRET", "abc:def")

    encabezado = XubioClient().headers["Authorization"]

    assert encabezado.startswith("Basic ")
    crudo = base64.b64decode(encabezado.split(" ", 1)[1]).decode("utf-8")
    assert crudo == "mi_usuario:abc:def"


def test_sin_credenciales_no_se_hace_la_llamada(monkeypatch):
    from app.core import config
    from app.services.xubio_client import XubioClient, XubioNoConfigurado

    monkeypatch.setattr(config.settings, "XUBIO_CLIENT_ID", "")
    monkeypatch.setattr(config.settings, "XUBIO_CLIENT_SECRET", "")

    with pytest.raises(XubioNoConfigurado, match="XUBIO_CLIENT_ID"):
        _ = XubioClient().headers


# --------------------------------------------------------------------------
# Rutas montadas
# --------------------------------------------------------------------------


def _rutas():
    """
    Paths reales segun el esquema OpenAPI.

    No se usa app.routes porque en las versiones nuevas de Starlette hay objetos
    included-router sin atributo 'path'. El esquema es lo que ultimately ve el
    navegador en /docs, asi que ademas de probar el registro prueba que la ruta
    es visible desde afuera.
    """
    from app.main import app

    return set(app.openapi()["paths"].keys())


def test_las_rutas_de_xubio_estan_montadas():
    """
    xubio.py existia pero no estaba en el router: sus rutas davan 404 y no
    aparecian en /docs.
    """
    rutas = _rutas()
    assert "/api/extractos/procesar" in rutas
    assert "/api/xubio/cruzar-datos" in rutas
    assert "/api/extractos/bancos" in rutas


def test_health_y_raiz():
    rutas = _rutas()
    assert "/health" in rutas
    assert "/" in rutas


# --------------------------------------------------------------------------
# Los 10 generadores de Excel
# --------------------------------------------------------------------------


def _fila_ini(detalle, con_cuenta=True):
    base = {"FECHA": "INICIO", "DETALLE": detalle, "DEBE": 0.0, "HABER": 0.0}
    if con_cuenta:
        base["CUENTA"] = "1"
        base["SALDO_CALC"] = 5000.0
    else:
        base["SALDO"] = 5000.0
    return base


def _fila_mov(detalle, debe, haber, con_cuenta=True):
    base = {"FECHA": "02/07/2026", "DETALLE": detalle, "DEBE": debe, "HABER": haber}
    if con_cuenta:
        base["CUENTA"] = "1"
        base["SALDO_CALC"] = 0.0
    else:
        base["SALDO"] = 0.0
    return base


def _fila_mov2(detalle, debe, haber, con_cuenta=True):
    fila = _fila_mov(detalle, debe, haber, con_cuenta)
    fila["FECHA"] = "03/07/2026"
    return fila


# (nombre, generador, filas, saldos esperados)
#
# Cada banco usa un texto distinto para la fila de saldo inicial y unos nombres
# de columna distintos, asi que las fixtures reproducen lo que cada extractor
# arma de verdad. Si uno cambia ese contrato, el test lo dice con el banco y la
# fila, no con un error generico de pandas.
#
# Los saldos esperados arrancan en el saldo ya aplicado del primer movimiento,
# no en el saldo de apertura: la fila de saldo inicial no se emite como
# movimiento (no tiene DEBE ni HABER, nunca cruzaria con Xubio) pero si sembrar
# la cadena. Galicia es el unico que no trae esa fila, y por eso su lista
# arranca en el saldo de su primer movimiento.
GENERADORES = [
    (
        "BBK",
        BcoBBK.generar_excel_brubank,
        [
            {"CUENTA": "1", "FECHA": "INICIO", "REFERENCIA": "", "DETALLE": "SALDO INICIAL",
             "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": 5000.0},
            {"CUENTA": "1", "FECHA": "02/07/2026", "REFERENCIA": "77", "DETALLE": "Compra",
             "DEBE": 1000.0, "HABER": 0.0, "SALDO_CALC": 0.0},
            {"CUENTA": "1", "FECHA": "03/07/2026", "REFERENCIA": "78", "DETALLE": "Venta",
             "DEBE": 0.0, "HABER": 500.0, "SALDO_CALC": 0.0},
        ],
        [4000.0, 4500.0],
    ),
    ("BBVA", BcoBBVA.generar_excel_bbva,
     [_fila_ini("SALDO ANTERIOR (Automatico)"), _fila_mov("Compra", 1000.0, 0.0), _fila_mov2("Venta", 0.0, 500.0)],
     [4000.0, 4500.0]),
    ("CMF", BcoCMF.generar_excel_cmf,
     [_fila_ini("SALDO ANTERIOR (Automatico)"), _fila_mov("Compra", 1000.0, 0.0), _fila_mov2("Venta", 0.0, 500.0)],
     [4000.0, 4500.0]),
    ("GAL", BcoGAL.generar_excel_galicia,
     # Galicia no emite fila de saldo inicial: imprime el saldo de cada linea
     [{"FECHA": "02/07/2026", "DETALLE": "Compra", "DEBE": 1000.0, "HABER": 0.0, "SALDO": 4000.0},
      {"FECHA": "03/07/2026", "DETALLE": "Venta", "DEBE": 0.0, "HABER": 500.0, "SALDO": 4500.0}],
     [4000.0, 4500.0]),
    ("HIPO", BcoHIPO.generar_excel_hipotecario,
     [_fila_ini("SALDO INICIAL", False), _fila_mov("Compra", 1000.0, 0.0, False), _fila_mov2("Venta", 0.0, 500.0, False)],
     [4000.0, 4500.0]),
    ("ICBC", BcoICBC.generar_excel_icbc,
     [{"FECHA": "INICIO", "DETALLE": "SALDO ANTERIOR (Automatico)", "DEBE": 0.0,
       "HABER": 0.0, "SALDO_CALC": 5000.0},
      {"FECHA": "02/07/2026", "DETALLE": "Compra", "DEBE": 1000.0, "HABER": 0.0, "SALDO_CALC": 0.0},
      {"FECHA": "03/07/2026", "DETALLE": "Venta", "DEBE": 0.0, "HABER": 500.0, "SALDO_CALC": 0.0}],
     [4000.0, 4500.0]),
    ("MP", BcoMP.generar_excel_mp,
     [{"FECHA": "INICIO", "DETALLE": "SALDO ANTERIOR (Automatico)", "ID_OPERACION": "-",
       "IMPORTE": 0.0, "SALDO_CALC": 5000.0},
      {"FECHA": "02/07/2026", "DETALLE": "Cobro", "ID_OPERACION": "999",
       "IMPORTE": 1000.0, "SALDO_CALC": 0.0},
      {"FECHA": "03/07/2026", "DETALLE": "Pago", "ID_OPERACION": "1000",
       "IMPORTE": -500.0, "SALDO_CALC": 0.0}],
     [6000.0, 5500.0]),
    ("PBA", BcoPBA.generar_excel_provincia,
     [_fila_ini("SALDO ANTERIOR", False), _fila_mov("Compra", 1000.0, 0.0, False), _fila_mov2("Venta", 0.0, 500.0, False)],
     [4000.0, 4500.0]),
    ("RIO", BcoRIO.generar_excel_santander,
     [_fila_ini("SALDO INICIAL"), _fila_mov("Compra", 1000.0, 0.0), _fila_mov2("Venta", 0.0, 500.0)],
     [4000.0, 4500.0]),
    ("SUPV", BcoSUPV.generar_excel_supervielle,
     [_fila_ini("SALDO ANTERIOR"), _fila_mov("Compra", 1000.0, 0.0), _fila_mov2("Venta", 0.0, 500.0)],
     [4000.0, 4500.0]),
]


@pytest.mark.parametrize(
    "nombre, generador, filas, esperado",
    GENERADORES,
    ids=[c[0] for c in GENERADORES],
)
def test_generador_no_agrega_ni_quita_filas(nombre, generador, filas, esperado, tmp_path):
    """
    Galicia metia una fila de plantilla con SALDO='XXX' para que alguien la
    completara a mano, y esa fila salia despues como un movimiento falso.
    """
    ruta = str(tmp_path / f"{nombre}.xlsx")
    ok, resultado = generador(filas, ruta, lambda m: None)
    assert ok, f"{nombre}: {resultado}"

    df = pd.read_excel(ruta)
    assert len(df) == len(filas), f"{nombre}: {len(filas)} filas entraron, {len(df)} salieron"


@pytest.mark.parametrize(
    "nombre, generador, filas, esperado",
    GENERADORES,
    ids=[c[0] for c in GENERADORES],
)
def test_saldos_de_cada_generador(nombre, generador, filas, esperado, tmp_path):
    """
    Cada generador escribe SALDO como formula de Excel, que nunca se evalua.
    Este test es el que dice si el saldo recalculado coincide con el que
    realmente tendria la cuenta.
    """
    ruta = str(tmp_path / f"{nombre}.xlsx")
    ok, resultado = generador(filas, ruta, lambda m: None)
    assert ok, f"{nombre}: {resultado}"

    movimientos = _df_to_movimientos(pd.read_excel(ruta), nombre)
    assert [round(m.saldo, 2) for m in movimientos] == esperado, nombre


# --------------------------------------------------------------------------
# La formula de Excel tiene que decir lo mismo que el procesador
# --------------------------------------------------------------------------


def _letra_excel(indice: int) -> str:
    """0 -> A, 1 -> B, ... para armar las referencias de celda."""
    letras = ""
    indice += 1
    while indice:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


_REF_CELDA = re.compile(r"\b([A-Z]{1,2})(\d+)\b")


def _evaluar_formula(formula: str, celdas: dict, profundidad: int = 0) -> float:
    """
    Resuelve una formula del Excel del tipo '=G2-E3+F3' con los valores del
    libro. Resuelve recursivamente porque la fila N usa el saldo de la N-1, que
    tambien es formula.
    """
    if profundidad > 20:
        raise AssertionError("referencias circulares en la formula de SALDO")

    def reemplazar(match):
        clave = (match.group(1), int(match.group(2)))
        valor = celdas.get(clave, 0.0)
        if isinstance(valor, str) and valor.startswith("="):
            valor = _evaluar_formula(valor.lstrip("="), celdas, profundidad + 1)
        return repr(float(valor or 0.0))

    return float(eval(_REF_CELDA.sub(reemplazar, formula.lstrip("="))))


@pytest.mark.parametrize(
    "nombre, generador, filas, esperado",
    GENERADORES,
    ids=[c[0] for c in GENERADORES],
)
def test_la_formula_de_excel_no_contradice_al_procesador(
    nombre, generador, filas, esperado, tmp_path
):
    """
    La columna SALDO del xlsx es una formula que openpyxl nunca evalua: el
    procesador recalcula el saldo desde DEBE y HABER. O sea que la formula es
    letra muerta para el sistema... pero el archivo igual se abre en Excel y ahi
    se ve.

    Con laformula al reves (+DEBE -HABER) el xlsx de BBK, ICBC, HIPO, PBA y
    SUPV decia que un pago de 1.000 hacia SUBIR el saldo de 5.000 a 6.000,
    justo al contrario de lo que el sistema calcula. Este test evalua la formula
    con los valores reales y la compara contra los mismos saldos que espera el
    procesador: si divergen, el archivo esta mintiendo.
    """
    ruta = str(tmp_path / f"{nombre}_formula.xlsx")
    ok, resultado = generador(filas, ruta, lambda m: None)
    assert ok, f"{nombre}: {resultado}"

    # data_only=False es lo unico que trae el texto de la formula; con
    # data_only=True (el default de pandas) vuelve vacio.
    libro = load_workbook(ruta, data_only=False)
    hoja = libro.active

    celdas = {
        (_letra_excel(c.column - 1), c.row): c.value
        for fila in hoja.iter_rows()
        for c in fila
    }

    columna_saldo = [c.column for c in hoja[1] if c.value == "SALDO"]
    assert columna_saldo, f"{nombre}: el xlsx no tiene columna SALDO"
    letra_saldo = _letra_excel(columna_saldo[0] - 1)

    formulas = [
        celdas[(letra_saldo, fila)]
        for fila in range(2, hoja.max_row + 1)
        if isinstance(celdas.get((letra_saldo, fila)), str)
        and str(celdas[(letra_saldo, fila)]).startswith("=")
    ]

    if not formulas:
        # Galicia y Santander traen el saldo ya impreso en el PDF.
        return

    evaluados = [round(_evaluar_formula(f, celdas), 2) for f in formulas]
    assert evaluados == esperado, f"{nombre}: la formula del xlsx no cierra igual"


# --------------------------------------------------------------------------
# Extractores contra un PDF real (optativo)
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("PDF_BANCO_TEST"),
    reason="Definir PDF_BANCO_TEST con la ruta de un extracto real para correrlo",
)
def test_extractor_contra_pdf_real():
    """
    Correr un banco contra un PDF de verdad y exigir que salgan movimientos.

    Es el unico test que detecta un extractor roto de verdad: los unitarios de
    Tools pasan igual con un parser completamente al reves.

    Ademas verifica que la cadena de saldos cierre fila por fila, que es donde
    se ve si el parser se comio un movimiento.
    """
    ruta = os.environ["PDF_BANCO_TEST"]
    banco = os.environ.get("BANCO_TEST", "BBVA")

    movimientos = procesar_archivo(banco_id=banco, ruta_pdf=ruta)

    assert movimientos, f"{banco} devolvio cero movimientos sobre {ruta}"
    assert all(not pd.isna(m.saldo) for m in movimientos), "hay saldos sin valor"

    for anterior, actual in zip(movimientos, movimientos[1:]):
        esperado = anterior.saldo - actual.debe + actual.haber
        assert actual.saldo == pytest.approx(esperado, abs=0.01), (
            f"la cadena de saldos se rompe en {actual.concepto!r}: "
            f"esperado {esperado}, obtenido {actual.saldo}"
        )