import logging
from pathlib import Path

import pytest

from app.services.bancos.BcoBBVA import _anio_del_documento
from app.services.procesador_central import BANCOS, procesar_archivo

# Extracto de muestra sintetico con la estructura del PDF real de BBVA (2
# paginas, julio 2026, fechas dd/mm sin anio, debitos en negativo). Va
# regenerado por tests/generar_muestras.py: el extracto real del que salio no se
# versiona porque el repo es publico y lleva CBU, CUIT y movimientos de la
# empresa.
RUTA_PDF = str(Path(__file__).resolve().parent.parent / "muestras" / "bbva.pdf")

pytestmark = pytest.mark.skipif(
    not Path(RUTA_PDF).exists(),
    reason="falta el PDF de muestra",
)


# Valores que se pueden verificar a ojo en el PDF.
CANTIDAD_ESPERADA = 6
DEBE_TOTAL = 17000.00
HABER_TOTAL = 70000.00
SALDO_FINAL = 153000.00


# --------------------------------------------------------------------------
# El anio sale del periodo del extracto
# --------------------------------------------------------------------------


def test_anio_sale_de_la_linea_de_periodo():
    assert _anio_del_documento("PERIODO 01/07/2026 AL 31/07/2026") == 2026


def test_anio_cae_al_primer_anio_del_texto():
    assert _anio_del_documento("Resumen de cuenta JULIO 2026") == 2026


def test_anio_es_none_si_el_pdf_no_trae_ninguno():
    assert _anio_del_documento("sin fechas con anio") is None


# --------------------------------------------------------------------------
# Extraccion contra el PDF de muestra
# --------------------------------------------------------------------------


def test_bbva_esta_registrado():
    assert "BBVA" in BANCOS


def test_bbva_extrae_los_seis_movimientos_del_pdf():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    assert len(movimientos) == CANTIDAD_ESPERADA


def test_bbva_resuelve_el_anio_de_las_fechas_dd_mm():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    fechas = [m.fecha for m in movimientos]
    assert min(fechas).isoformat() == "2026-07-01"
    assert max(fechas).isoformat() == "2026-07-15"


def test_bbva_interpreta_el_signo_del_importe():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    # "01/07 IMP.LEY 25413 ... -5.000,00" es un debito de 5.000.
    assert movimientos[0].debe == pytest.approx(5000.0)
    assert movimientos[0].haber == pytest.approx(0.0)

    # "03/07 COBRO DE PROVEEDORES ... 20.000,00" es un credito de 20.000.
    assert movimientos[2].debe == pytest.approx(0.0)
    assert movimientos[2].haber == pytest.approx(20000.0)


def test_bbva_arma_la_cadena_de_saldos_desde_el_saldo_inicial():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    # El PDF cierra con "SALDO AL 31 DE JULIO 153.000,00".
    assert movimientos[-1].saldo == pytest.approx(SALDO_FINAL, abs=0.01)


def test_bbva_los_totales_coinciden_con_el_resumen():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    assert sum(m.debe for m in movimientos) == pytest.approx(DEBE_TOTAL, abs=0.01)
    assert sum(m.haber for m in movimientos) == pytest.approx(HABER_TOTAL, abs=0.01)


def test_bbva_no_deja_movimientos_sin_importe_ni_concepto():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if not m.debe and not m.haber] == []
    assert [m for m in movimientos if not m.concepto.strip()] == []


def test_bbva_ignora_la_fila_sin_movimientos():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    # La cuenta sin actividad imprime "00/00 SIN MOVIMIENTOS": no es un
    # movimiento y antes entraba como una fila en cero.
    assert [m for m in movimientos if m.concepto.upper().startswith("SIN MOVIMIENTOS")] == []


def test_bbva_ignora_el_anexo_de_transferencias():
    movimientos = procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)

    # Despues del ultimo TOTAL MOVIMIENTOS el banco imprime un anexo de
    # transferencias ("TR. E/CTAS.") con importes de millones que no son
    # movimientos de la cuenta.
    assert [m for m in movimientos if m.haber >= 1000000] == []
    assert [m for m in movimientos if "TR. E/CTAS" in m.concepto] == []


def test_bbva_no_descuadra_ningun_saldo_impreso():
    """
    El saldo de cada linea lo imprime el banco. Si el parser se come o invierte
    un movimiento, la cadena deja de coincidir con lo impreso: este es el
    control que delata un parser "que anda pero miente".
    """

    captura = []

    class _Handler(logging.Handler):
        def emit(self, record):
            captura.append(record.getMessage())

    logger = logging.getLogger("app.services.procesador_central")
    handler = _Handler()
    logger.addHandler(handler)
    try:
        procesar_archivo(banco_id="BBVA", ruta_pdf=RUTA_PDF)
    finally:
        logger.removeHandler(handler)

    assert [m for m in captura if "no cuadra" in m] == []
