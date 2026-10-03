from pathlib import Path

import pytest

from app.services.procesador_central import BANCOS, procesar_archivo

# Extracto de muestra sintetico con la estructura del portal de Santander
# (4 paginas, julio 2026, fechas dd-mm, signo pegado al final). Va regenerado
# por tests/generar_muestras.py: el extracto real del que salio no se versiona
# porque el repo es publico y lleva CBU, CUIT y movimientos de la empresa.
RUTA_PDF = str(Path(__file__).resolve().parent.parent / "muestras" / "santander.pdf")

pytestmark = pytest.mark.skipif(
    not Path(RUTA_PDF).exists(),
    reason="falta el PDF de muestra",
)


# Valores que se pueden verificar a ojo en el PDF.
CANTIDAD_ESPERADA = 133
SALDO_INICIAL = 725260.36
SALDO_FINAL = 556238.11


def test_sant_esta_registrado():
    assert "SANT" in BANCOS


def test_sant_extrae_los_133_movimientos_del_pdf():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    assert len(movimientos) == CANTIDAD_ESPERADA


def test_sant_arma_la_cadena_de_saldos_desde_el_saldo_inicial():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    # El PDF cierra con "SALDO FINAL AL 31/07/2026 556.238,11".
    assert movimientos[-1].saldo == pytest.approx(SALDO_FINAL, abs=0.01)


def test_sant_usa_las_fechas_del_periodo_con_anio():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    fechas = [m.fecha for m in movimientos]
    assert min(fechas).isoformat() == "2026-07-01"
    assert max(fechas).isoformat() == "2026-07-31"


def test_sant_no_deja_movimientos_sin_importe():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    sin_importe = [m for m in movimientos if not m.debe and not m.haber]
    assert sin_importe == []


def test_sant_interpreta_el_signo_pegado_al_final():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    # "01-07 MANTENIMIENTO DE CUENTA ... 55.000,00-" es un debito de 55.000.
    primero = movimientos[0]
    assert primero.debe == pytest.approx(55000.0)
    assert primero.haber == pytest.approx(0.0)


def test_sant_no_deja_el_codigo_de_sucursal_en_el_concepto():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    con_codigo = [m for m in movimientos if "0543" in m.concepto.split()]
    assert con_codigo == []


def test_sant_no_deja_conceptos_vacios():
    movimientos = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)

    assert [m for m in movimientos if not m.concepto.strip()] == []


# --------------------------------------------------------------------------
# El motor generico tiene que cair a este mismo PDF sin adaptador
# --------------------------------------------------------------------------


def test_el_motor_generico_also_lee_el_pdf_de_santander():
    from app.api.rutas.extractos import _leer_pdf

    movimientos, motor = _leer_pdf("GENERICO", RUTA_PDF)

    assert motor == "GENERICO"
    assert len([m for m in movimientos if m.debe or m.haber]) == CANTIDAD_ESPERADA


def test_el_motor_generico_llega_al_saldo_final_del_pdf():
    from app.api.rutas.extractos import _leer_pdf

    movimientos, _ = _leer_pdf("GENERICO", RUTA_PDF)

    assert movimientos[-1].saldo == pytest.approx(SALDO_FINAL, abs=0.01)


def test_un_banco_sin_adapter_cae_al_motor_generico():
    from app.api.rutas.extractos import _leer_pdf

    # BBVA no esta soportado: en vez de un error seco, entra el generico.
    movimientos, motor = _leer_pdf("BBVA", RUTA_PDF)

    assert motor == "GENERICO"
    assert len([m for m in movimientos if m.debe or m.haber]) == CANTIDAD_ESPERADA


def test_el_generico_y_el_banco_coinciden_en_las_sumas():
    from app.api.rutas.extractos import _leer_pdf

    sant = procesar_archivo(banco_id="SANT", ruta_pdf=RUTA_PDF)
    generico, _ = _leer_pdf("GENERICO", RUTA_PDF)

    def totales(movs):
        return (
            round(sum(m.debe for m in movs), 2),
            round(sum(m.haber for m in movs), 2),
        )

    assert totales(generico) == totales(sant)


def test_el_motor_generico_no_borra_el_pdf_que_recibe(tmp_path):
    from app.api.rutas.extractos import _leer_pdf

    copia = tmp_path / "copia.pdf"
    copia.write_bytes(Path(RUTA_PDF).read_bytes())

    _leer_pdf("GENERICO", str(copia))

    # procesar_archivo borraba el archivo de entrada en su finally: el PDF del
    # llamador desaparecia y el fallback se quedaba sin que leer.
    assert copia.exists()


def test_el_parser_del_banco_no_borra_el_pdf_que_recibe(tmp_path):
    copia = tmp_path / "copia.pdf"
    copia.write_bytes(Path(RUTA_PDF).read_bytes())

    procesar_archivo(banco_id="SANT", ruta_pdf=str(copia))

    assert copia.exists()


# --------------------------------------------------------------------------
# PDF escaneado
# --------------------------------------------------------------------------


@pytest.fixture
def pdf_escaneado(tmp_path):
    """PDF valido pero sin una sola palabra: es lo que ve una foto o escaneo."""
    reportlab = pytest.importorskip("reportlab")
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    ruta = tmp_path / "escaneado.pdf"
    c = canvas.Canvas(str(ruta), pagesize=A4)
    c.rect(60, 400, 480, 340, fill=1)
    c.showPage()
    c.save()
    return str(ruta)


@pytest.mark.parametrize("banco", ["GENERICO", "SANT", "BBVA"])
def test_el_pdf_escaneado_explica_que_hace_falta_ocr(banco, pdf_escaneado):
    from fastapi.testclient import TestClient

    from app.main import app

    with open(pdf_escaneado, "rb") as fh:
        contenido = fh.read()

    respuesta = TestClient(app).post(
        "/api/extractos/procesar",
        data={"banco": banco},
        files={"archivo": ("escaneo.pdf", contenido, "application/pdf")},
    )

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert "escaneo" in detalle
    assert "OCR" in detalle

