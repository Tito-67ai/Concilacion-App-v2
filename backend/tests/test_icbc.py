import logging
from pathlib import Path

import pytest

from app.services.bancos.BcoSANT import _anio_del_documento, _importes_de_linea
from app.services.procesador_central import BANCOS, procesar_archivo

# Extracto de muestra sintetico con la estructura del PDF real de ICBC
# (2 paginas, julio 2026, fechas dd-mm sin ano, codigos de comprobante y de
# canal pegados al importe). Va regenerado por tests/generar_muestras.py: el
# extracto real del que salio no se versiona porque el repo es publico y lleva
# CBU, CUIT y movimientos de la empresa.
RUTA_PDF = str(Path(__file__).resolve().parent.parent / "muestras" / "icbc.pdf")

pytestmark = pytest.mark.skipif(
    not Path(RUTA_PDF).exists(),
    reason="falta el PDF de muestra",
)

# Valores que se pueden verificar a ojo en el PDF.
CANTIDAD_ESPERADA = 17
SALDO_INICIAL = 10_000_000.00
SALDO_FINAL = 10_951_513.71
TOTAL_DEBE = 2_510_788.89
TOTAL_HABER = 3_462_302.60


# --------------------------------------------------------------------------
# El bug que hacia que el extracto entero se perdiera
# --------------------------------------------------------------------------


def test_icbc_esta_registrado():
    assert "ICBC" in BANCOS


def test_icbc_extrae_los_17_movimientos_del_pdf():
    # Antes: "ICBC: se leyeron 18 filas pero ninguna tiene una fecha reconocible".
    # Las fechas del PDF son dd-mm sin ano, asi que el motor central las tiraba
    # todas y el extracto no producia ni un movimiento.
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert len(movimientos) == CANTIDAD_ESPERADA


def test_icbc_resuelve_el_anio_que_no_esta_en_la_linea():
    # El ano solo aparece en el encabezado ("PERIODO 01-07-2026 AL 31-07-2026"),
    # nunca en las lineas de movimiento.
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    fechas = [m.fecha for m in movimientos]
    assert min(fechas).isoformat() == "2026-07-01"
    assert max(fechas).isoformat() == "2026-07-31"


def test_el_anio_se_saca_del_periodo_del_encabezado():
    assert _anio_del_documento("PERIODO 01-07-2026 AL 31-07-2026") == 2026


def test_el_anio_acepta_el_periodo_con_barras():
    assert _anio_del_documento("PERIODO 01/07/2026 AL 31/07/2026") == 2026


def test_el_anio_cae_a_otro_ano_del_documento_si_no_hay_periodo():
    # Si el encabezado cambia y no dice PERIODO, que tome el unico año que
    # aparezca en el texto antes de rendirse.
    assert _anio_del_documento("EXTRACTO AL 31/07/2025") == 2025


# --------------------------------------------------------------------------
# El bug que devolvia importes de un billon
# --------------------------------------------------------------------------


def test_icbc_no_toma_el_codigo_de_comprobante_por_importe():
    """
    El parser viejo devolvia 501,00 para "MANTENIMIENTO DE CUENTA" porque el
    codigo de comprobante 0501 parece un numero. Con 90 filas asi el DEBE daba
    un billon.
    """
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    primero = movimientos[0]
    assert primero.debe == pytest.approx(40_000.0)
    assert primero.haber == pytest.approx(0.0)


def test_el_codigo_de_comprobante_no_es_un_importe():
    assert _importes_de_linea(["MANTENIMIENTO", "DE", "CUENTA", "0501"]) == []


def test_el_codigo_de_comprobante_no_queda_en_el_concepto():
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if "0501" in m.concepto.split()] == []


@pytest.mark.parametrize("canal", ["FOND", "DNET", "BS", "CREDIN"])
def test_los_canales_del_banco_no_son_importes(canal):
    # El PDF pone el ORIGEN y el CANAL pegados al importe. "BS" es un canal, no
    # una caja.
    assert _importes_de_linea(["DEPOSITO", "0501", canal]) == []


def test_el_importe_con_canal_pegado_se_lee_como_importe():
    # "1.000.000,00 FOND" tiene que valer 1.000.000 y no "el ultimo token".
    assert _importes_de_linea(["CRED", "RESC", "FCI", "0501", "FOND", "1.000.000,00"])[0][1] == (
        pytest.approx(1_000_000.0)
    )


def test_icbc_no_deja_movimientos_sin_importe():
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if not m.debe and not m.haber] == []


# --------------------------------------------------------------------------
# Signo
# --------------------------------------------------------------------------


def test_icbc_interpreta_el_signo_pegado_al_final():
    # "01-07 MANTENIMIENTO DE CUENTA 0501 40.000,00-" es plata que sale.
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    primero = movimientos[0]
    assert primero.debe == pytest.approx(40_000.0)
    assert primero.haber == pytest.approx(0.0)


def test_icbc_lee_el_credito_como_haber():
    # "01-07 CRED RESC FCI ... 2.000.000,00" no trae signo: entra plata.
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    credito = movimientos[6]
    assert credito.haber == pytest.approx(2_000_000.0)
    assert credito.debe == pytest.approx(0.0)


def test_icbc_no_deja_conceptos_vacios():
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if not m.concepto.strip()] == []


def test_icbc_no_convierte_el_saldo_de_pagina_anterior_en_movimiento():
    # La pagina 2 arranca con "SALDO PAGINA ANTERIOR 9.915.061,08". Esa linea no
    # es un movimiento.
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if "PAGINA ANTERIOR" in m.concepto] == []


# --------------------------------------------------------------------------
# Cierre de la cuenta
# --------------------------------------------------------------------------


def test_icbc_llega_al_saldo_final_del_pdf():
    # El PDF cierra con "SALDO FINAL AL 31/07/2026 10.951.513,71".
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert movimientos[-1].saldo == pytest.approx(SALDO_FINAL, abs=0.01)


def test_icbc_suma_las_columnas_como_el_pdf():
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    assert sum(m.debe for m in movimientos) == pytest.approx(TOTAL_DEBE, abs=0.01)
    assert sum(m.haber for m in movimientos) == pytest.approx(TOTAL_HABER, abs=0.01)


def test_el_saldo_de_cada_fila_es_el_acumulado_desde_el_inicial():
    """
    El saldo de cada fila tiene que coincidir con el acumulado desde el saldo
    inicial. El recalculo central delega en que DEBE y HABER sean correctos, asi
    que esto es la red que atrapa cualquier movimiento invertido.
    """
    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    saldo = SALDO_INICIAL
    for m in movimientos:
        saldo = saldo - m.debe + m.haber
        assert m.saldo == pytest.approx(saldo, abs=0.01), (
            f"el saldo de {m.concepto!r} no es el acumulado: "
            f"el banco imprime {m.saldo}, del acumulado sale {saldo}"
        )


def test_el_saldo_impreso_por_el_banco_cuadra_en_todas_las_filas(caplog):
    """
    Ninguna fila puede quedar con el saldo calculado distinto del que imprime
    el banco. Este es el control que detecta que el parser se come un
    movimiento o pierde el signo de un saldo.
    """
    with caplog.at_level(logging.WARNING):
        procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)

    descuadres = [r.getMessage() for r in caplog.records if "no cuadra" in r.getMessage()]

    assert descuadres == [], (
        f"{len(descuadres)} filas con el saldo impreso distinto del calculado. "
        f"Primero: {descuadres[0]}"
    )


# --------------------------------------------------------------------------
# ICBC usa el layout del portal, asi que cae al motor generico sin adaptador
# --------------------------------------------------------------------------


def test_el_motor_generico_tambien_lee_el_pdf_de_icbc():
    from app.api.rutas.extractos import _leer_pdf

    movimientos, motor = _leer_pdf("GENERICO", RUTA_PDF)

    assert motor == "GENERICO"
    assert len(movimientos) == CANTIDAD_ESPERADA
    assert [m for m in movimientos if not m.fecha] == []


def test_el_motor_generico_y_el_banco_coinciden():
    from app.api.rutas.extractos import _leer_pdf

    icbc = procesar_archivo(banco_id="ICBC", ruta_pdf=RUTA_PDF)
    generico, _ = _leer_pdf("GENERICO", RUTA_PDF)

    def totales(movs):
        return (
            len(movs),
            round(sum(m.debe for m in movs), 2),
            round(sum(m.haber for m in movs), 2),
        )

    assert totales(generico) == totales(icbc)