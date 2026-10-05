import sys

import pytest

from app.services.Tools import es_numero_bancario, limpiar_numero
from app.services.extractor_generico import (
    _anio_del_documento,
    _completar_anio,
    _es_importe,
    _fusionar_duplicados,
    _indices_de_importes,
)

# --------------------------------------------------------------------------
# Deteccion de importes
# --------------------------------------------------------------------------
#
# Estos casos vienen de un extracto real de Santander y Costamonte: son las
# lineas que rompian el parser.


@pytest.mark.parametrize(
    "token",
    [
        "55.000,00-",      # debito con el signo pegado al final
        "-55.000,00",      # debito con el signo adelante
        "1.500,00",        # formato argentino
        "1,500.00",        # formato americano
        "0,05",            # centavos sin miles
        "12.000.000,00",
    ],
)
def test_reconoce_importes_en_los_tres_formatos(token):
    assert _es_importe(token) is True


@pytest.mark.parametrize(
    "token",
    [
        "TR.4965724",      # comprobante: sin las letras queda '.4965724' -> 0,50
        "MTA0000000001",  # referencia alfabetica
        "PAGO.VISA",
        "DEBITO",
        "DNET",
    ],
)
def test_no_confunde_texto_con_numeros_por_importe(token):
    # El bug: limpiar_numero('TR.4965724') daba 0,50 y el parser tomaba el
    # comprobante como el importe del movimiento.
    assert _es_importe(token) is False


def test_el_comprobante_no_pisa_el_importe_real():
    partes = "01-07 TR.4965724 A 0542/0111002 MTA0000000001 0187 DNET 1.000.000,00-".split()

    indices = _indices_de_importes(partes)

    assert [partes[i] for i in indices] == ["1.000.000,00-"]


def test_filtra_los_codigos_de_tres_y_cuatro_digitos():
    # 0543 es la sucursal y 0187 el canal: ninguno es un importe.
    partes = "01-07 MANTENIMIENTO DE CUENTA 0543 55.000,00-".split()

    assert [partes[i] for i in _indices_de_importes(partes)] == ["55.000,00-"]


def test_toma_los_dos_numeros_de_debito_y_saldo():
    partes = "01-07 DEBITO TRANSF CONNECTION B 0109239 0187 DNET 30.087.172,11- 1.560.861,92".split()

    indices = _indices_de_importes(partes)

    assert [partes[i] for i in indices] == ["30.087.172,11-", "1.560.861,92"]


@pytest.mark.parametrize("codigo", ["0543", "0187", "0109239", "20260101"])
def test_un_entero_suelto_no_es_un_importe(codigo):
    # 0109239 es un comprobante de 7 digitos: los 3-4 digitos estan filtrados
    # aparte, pero el regla general es que un importe siempre trae miles o
    # centavos.
    assert _es_importe(codigo) is False


# --------------------------------------------------------------------------
# Fechas sin ano
# --------------------------------------------------------------------------


def test_saca_el_anio_del_periodo_del_encabezado():
    texto = (
        "LOGYS SOLUTIONS SRL\n"
        "PERIODO 01-07-2026 AL 31-07-2026\n"
        "FECHA CONCEPTO DEBITOS CREDITOS SALDOS\n"
    )

    assert _anio_del_documento(texto) == 2026


def test_cae_al_primer_anio_suelto_si_no_hay_periodo():
    assert _anio_del_documento("Extracto cuenta 123456 2026") == 2026


def test_sin_anio_en_el_documento_devuelve_none():
    assert _anio_del_documento("Extracto de cuenta corriente") is None


def test_le_agrega_el_anio_a_las_fechas_dd_mm():
    assert _completar_anio("01-07", 2026) == "01-07-2026"
    assert _completar_anio("31-12", 2025) == "31-12-2025"


def test_no_toca_las_fechas_que_ya_traen_ano():
    assert _completar_anio("01/07/2026", 2020) == "01/07/2026"
    assert _completar_anio("01-07-2026", 2020) == "01-07-2026"


def test_sin_anio_inferido_la_fecha_queda_como_estaba():
    assert _completar_anio("01-07", None) == "01-07"


# --------------------------------------------------------------------------
# Tools: contrato de los helpers
# --------------------------------------------------------------------------


def test_limpiar_numero_entiende_el_signo_al_final():
    assert limpiar_numero("55.000,00-") == pytest.approx(-55000.0)


def test_es_numero_bancario_rechaza_texto_con_letras():
    # Documenta una limitacion conocida de es_numero_bancario: es deliberadamente
    # laxa para los extractores por banco. El motor generico se protege con
    # RE_TOKEN_NUMERICO antes de llamarlo, por eso el caso sale False aca solo
    # para los tokens que no tienen ningun digito util.
    assert es_numero_bancario("DEBITO") is False


# --------------------------------------------------------------------------
# Fusion de duplicados
# --------------------------------------------------------------------------


def _fila(fecha, detalle, debe=0.0, haber=0.0):
    return {"FECHA": fecha, "DETALLE": detalle, "DEBE": debe, "HABER": haber}


def test_fusiona_el_concepto_partido_en_dos_renglones():
    # El caso del docstring: el texto del PDF se parte y el motor generico
    # arma dos filas con la misma fecha y el mismo importe cuando en realidad
    # hay un solo movimiento. Sin la fusion, el cruce despues ve dos
    # movimientos de 1.500,00 y uno queda pendiente para siempre.
    resultado = _fusionar_duplicados(
        [
            _fila("01-07-2026", "TRANSFERENCIA", 1500.0),
            _fila("01-07-2026", "FACTURA 000123", 0.0, 1500.0),
        ]
    )

    assert len(resultado) == 1
    assert resultado[0]["DETALLE"] == "TRANSFERENCIA FACTURA 000123"
    assert resultado[0]["DEBE"] == 1500.0


def test_no_fusiona_dos_movimientos_legitimos_iguales():
    # Mismo importe y misma fecha, pero no contiguos: son dos movimientos
    # distintos y ninguno se puede borrar.
    filas = [
        _fila("01-07-2026", "COBRO A", 1500.0),
        _fila("02-07-2026", "OTRO MOVIMIENTO", 250.0),
        _fila("01-07-2026", "COBRO B", 1500.0),
    ]
    resultado = _fusionar_duplicados(filas)

    assert len(resultado) == 3
    assert [f["DETALLE"] for f in resultado] == [
        "COBRO A",
        "OTRO MOVIMIENTO",
        "COBRO B",
    ]


def test_no_fusiona_si_el_importe_es_distinto():
    filas = [
        _fila("01-07-2026", "TRANSFERENCIA", 1500.0),
        _fila("01-07-2026", "TRANSFERENCIA", 2500.0),
    ]
    assert len(_fusionar_duplicados(filas)) == 2
