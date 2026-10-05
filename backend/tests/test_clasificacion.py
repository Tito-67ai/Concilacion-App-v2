import pytest

from app.services.clasificacion import (
    IMPUESTO,
    OPERATIVO,
    PERCEPCION,
    clasificar,
    es_no_operativa,
    resumir_categorias,
)

# Conceptos tomados de los extractos reales de ICBC y Santander.
PERCEPCIONES = [
    "PERCEPCION IVA RG",
    "PERCEPCION IVA RG 02-07",
    "ING BRUTOS PERCEP. C.A.B.A",
    "ING BRUTOS PERCEP. BUENOS",
    "R/RECAUDACION IB SIRCREB C",
]

IMPUESTOS = [
    "IMPUESTO AL VALOR AGREGADO",
    "IMP S/DEBITOS EN CTA CTE",
    "IMP S/CRED EN CTA CTE",
    "SELLADO",
]

OPERATIVOS = [
    "MANTENIMIENTO DE CUENTA",
    "CRED RESC FCI 020A999999999",
    "DEBITO TRANSF CONNECTION B",
    "DEPOS. ECHEQ. NRO. : 99999",
    "TR.9999999 A 0501/0103874",
    "PAGO PROVEEDOR",
    "COBRO FACTURA 001-00012345",
]


@pytest.mark.parametrize("concepto", PERCEPCIONES)
def test_las_percepciones_quedan_como_percepcion(concepto):
    # Plata que la empresa retiene de un cliente y le gira a ARCA: no es ingreso
    # ni gasto propio, va a un pasivo.
    assert clasificar(concepto) == PERCEPCION


@pytest.mark.parametrize("concepto", IMPUESTOS)
def test_los_impuestos_del_banco_quedan_como_impuesto(concepto):
    assert clasificar(concepto) == IMPUESTO


@pytest.mark.parametrize("concepto", OPERATIVOS)
def test_las_operaciones_no_se_etiquetan(concepto):
    assert clasificar(concepto) == OPERATIVO


def test_lo_que_no_se_reconoce_es_operativo():
    # Default importante: un concepto nuevo del banco cae en operativo, que es
    # la categoria que el filtro no esconde. Ante la duda, a mano.
    assert clasificar("ALGO QUE NO CONOCEMOS 12345") == OPERATIVO


@pytest.mark.parametrize(
    "concepto",
    ["PERCEPCIÓN IVA RG", "percepción iva rg", "ING BRUTOS PERCEP. C.A.B.A "],
)
def test_clasifica_igual_con_acentos_y_en_minusculas(concepto):
    # El PDF sale sin acentos pero el importador de tablas puede traerlos.
    assert clasificar(concepto) in (PERCEPCION, IMPUESTO)


def test_un_concepto_vacio_no_revienta():
    assert clasificar("") == OPERATIVO
    assert clasificar(None) == OPERATIVO


def test_la_percepcion_gana_cuando_un_concepto_menciona_los_dos():
    # Orden de las reglas: lo especifico primero.
    assert clasificar("PERCEPCION IVA - IMPUESTO AL VALOR AGREGADO") == PERCEPCION


def test_ing_brutos_no_come_una_operacion_que_lo_diga_de_pasada():
    # Cuidado con los patrones sueltos: un traspaso con la palabra en el medio
    # no es una percepcion.
    assert clasificar("TRASPASO A ING BRUTOS SRL") == OPERATIVO


def test_es_no_operativa_distingue_las_dos_categorias():
    assert es_no_operativa(PERCEPCION)
    assert es_no_operativa(IMPUESTO)
    assert not es_no_operativa(OPERATIVO)


def test_resumir_categorias_cuenta_y_no_rompe_si_falta_el_campo():
    conteo = resumir_categorias(
        [
            {"categoria": OPERATIVO},
            {"categoria": PERCEPCION},
            {"categoria": PERCEPCION},
            {"categoria": None},
        ]
    )

    assert conteo == {OPERATIVO: 2, PERCEPCION: 2, IMPUESTO: 0}


# --------------------------------------------------------------------------
# Etiquetar no puede alterar el cruce ni los importes
# --------------------------------------------------------------------------


def _mov(fecha, concepto, debe=0.0, haber=0.0, saldo=0.0):
    from datetime import date

    from app.models.schemas import MovimientoBancario

    return MovimientoBancario(
        fecha=date(2026, 7, 15),
        concepto=concepto,
        debe=debe,
        haber=haber,
        saldo=saldo,
    )


def test_una_percepcion_no_se_concilia_sola_pero_sigue_en_la_bandeja():
    """
    Etiquetar no puede cambiar el resultado del cruce. Una percepcion con el
    mismo importe que un movimiento de Xubio igual se cruza: la categoria es
    una etiqueta para que una persona la pueda esconder, no una regla.
    """
    from app.services.conciliador import conciliar_movimientos

    banco = [
        _mov("2026-07-15", "PERCEPCION IVA RG", debe=1_000.0, saldo=5_000.0),
        _mov("2026-07-15", "COBRO FACTURA", haber=9_000.0, saldo=14_000.0),
    ]
    # En Xubio un ingreso va al DEBE (por eso _importe_xubio es debe - haber).
    xubio = [{"fecha": "2026-07-15", "concepto": "Factura", "debe": 9_000.0, "haber": 0}]

    resultado = conciliar_movimientos(banco, xubio)

    # El cobro de la factura cruza, la percepcion queda pendiente.
    assert len(resultado["conciliados"]) == 1
    assert resultado["conciliados"][0]["concepto_banco"] == "COBRO FACTURA"

    # Y la percepcion sigue en la bandeja, con su etiqueta.
    pendientes = resultado["pendientes_banco"]
    assert len(pendientes) == 1
    assert pendientes[0]["concepto"] == "PERCEPCION IVA RG"
    assert pendientes[0]["categoria"] == PERCEPCION
    # El importe intacto: 1.000 de salida.
    assert pendientes[0]["importe"] == pytest.approx(-1_000.0)


def test_una_percepcion_tambien_se_cruza_si_el_importe_esta_en_xubio():
    """
    Si en la contabilidad esta en la cuenta bancaria, tiene que cruzar igual. La
    etiqueta no bloquea el cruce ni lo fuerza.
    """
    from app.services.conciliador import conciliar_movimientos

    banco = [_mov("2026-07-15", "PERCEPCION IVA RG", debe=1_000.0, saldo=5_000.0)]
    # Salida de 1.000 en el banco, salida de 1.000 en Xubio: mismo signo, cruza.
    xubio = [{"fecha": "2026-07-15", "concepto": "IVA a perceptual", "debe": 0, "haber": 1_000.0}]

    resultado = conciliar_movimientos(banco, xubio)

    assert len(resultado["conciliados"]) == 1
    # Y sigue dejando saber que es una percepcion, para que en la pantalla se
    # pueda marcar aunque haya cruzado.
    assert resultado["conciliados"][0]["categoria"] == PERCEPCION


def test_las_tres_bandejas_llevan_la_categoria():
    from app.services.conciliador import conciliar_movimientos

    banco = [
        _mov("2026-07-15", "COBRO FACTURA", haber=9_000.0, saldo=14_000.0),
        _mov("2026-07-15", "PAGO PROVEEDOR", debe=3_000.0, saldo=11_000.0),
        _mov("2026-07-15", "PERCEPCION IVA RG", debe=1_000.0, saldo=10_000.0),
        _mov("2026-07-15", "COMPRA", debe=500.0, saldo=9_500.0),
    ]
    xubio = [{"fecha": "2026-07-15", "concepto": "Factura", "debe": 9_000.0, "haber": 0}]

    resultado = conciliar_movimientos(banco, xubio)

    assert resultado["conciliados"][0]["categoria"] == OPERATIVO
    assert all("categoria" in row for row in resultado["pendientes_banco"])
    assert resultado["categorias"] == {OPERATIVO: 3, PERCEPCION: 1, IMPUESTO: 0}


def test_la_respuesta_viene_con_el_conteo_para_la_pantalla():
    # El frontend lo usa para el toggle: sin esto no puede decir "38 de 90 son
    # impuestos y percepciones".
    from app.services.conciliador import conciliar_movimientos

    banco = [
        _mov("2026-07-15", "COBRO FACTURA", haber=9_000.0, saldo=14_000.0),
        _mov("2026-07-15", "IMPUESTO AL VALOR AGREGADO", debe=1_000.0, saldo=13_000.0),
    ]

    resultado = conciliar_movimientos(banco, [])

    assert resultado["categorias"] == {OPERATIVO: 1, PERCEPCION: 0, IMPUESTO: 1}


# --------------------------------------------------------------------------
# Sobre el PDF de muestra
# --------------------------------------------------------------------------


def test_el_fixture_de_icbc_se_parte_en_las_tres_categorias():
    from pathlib import Path

    from app.services.procesador_central import procesar_archivo

    ruta = Path(__file__).resolve().parent.parent / "muestras" / "icbc.pdf"
    if not ruta.exists():
        pytest.skip("falta el PDF de muestra")

    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=str(ruta))
    conteo = resumir_categorias([{"categoria": m.categoria} for m in movimientos])

    # De los 17 movimientos del fixture: 4 percepciones (PERCEPCION IVA RG, ING
    # BRUTOS PERCEP y dos R/RECAUDACION SIRCREB), 4 impuestos (dos IVA y dos
    # IMP S/...) y 9 operativos.
    assert conteo == {OPERATIVO: 9, PERCEPCION: 4, IMPUESTO: 4}
    assert sum(conteo.values()) == len(movimientos) == 17


def test_el_fixture_de_icbc_no_deja_conceptos_sin_clasificar():
    """
    Chequeo de que el filtro no se coma una operacion: los 9 operativos del
    fixture tienen que ser los que uno esperaria.
    """
    from pathlib import Path

    from app.services.procesador_central import procesar_archivo

    ruta = Path(__file__).resolve().parent.parent / "muestras" / "icbc.pdf"
    if not ruta.exists():
        pytest.skip("falta el PDF de muestra")

    movimientos = procesar_archivo(banco_id="ICBC", ruta_pdf=str(ruta))

    operativo_esperado = {
        "MANTENIMIENTO DE CUENTA",
        "CRED RESC FCI",
        "DEBITO TRANSF CONNECTION B",
        "COM MPAY TRF",
        "DEB SUSCR FCI",
        # "DBTO CREDIN" es el canal de un debito a tarjeta, no el impuesto
        # "IMP S/CRED": tiene que quedar operativo.
        "DEBITO INMEDIATO",
        "DEPOS. ECHEQ. NRO.",
        "TR.",  # el traspaso: contiene numeros de cuenta pero es operacion
    }
    for m in movimientos:
        if m.categoria == OPERATIVO:
            assert any(m.concepto.startswith(p) for p in operativo_esperado), (
                f"{m.concepto!r} quedo como operativa sin esperarlo"
            )