"""Tests de las reglas de negocio de partidas sin coincidencia (reglas_conciliacion.py).

Son las reglas del pedido de produccion (FO 02-03):
    - Extracto + gasto / retencion-impuesto -> asiento automatico.
    - Extracto + debito que no es gasto ni impuesto -> debito automatico, a revisar.
    - Extracto + acreditacion -> ingreso no registrado, revision manual, sin asiento.
    - Mayor -> diferencia temporal, sin asiento.
"""

import pytest

from app.core.config import settings
from app.services.reglas_conciliacion import (
    ACCION_ASIENTO,
    ACCION_PENDIENTE,
    ACCION_REVISAR,
    CONTRACUENTA_GASTOS,
    CONTRACUENTA_RETENCIONES,
    TIPO_DEBITO_AUTOMATICO,
    TIPO_GASTO_BANCARIO,
    TIPO_INGRESO_NO_REGISTRADO,
    TIPO_PENDIENTE_TEMPORAL,
    TIPO_RETENCION_IMPUESTO,
    clasificar_sin_coincidencia,
)


@pytest.mark.parametrize(
    "concepto",
    ["COMISION", "COM MANT CT", "MANTENIMIENTO", "CHEQUERA", "DEB LIQ INTER", "IVA REDUCIDA"],
)
def test_gastos_bancarios_generan_asiento(concepto):
    clasificacion = clasificar_sin_coincidencia("banco", concepto, entra=False)
    assert clasificacion.tipo == TIPO_GASTO_BANCARIO
    assert clasificacion.accion == ACCION_ASIENTO
    assert clasificacion.contracuenta == CONTRACUENTA_GASTOS
    assert clasificacion.revisar_manual is False


@pytest.mark.parametrize(
    "concepto",
    ["SIRCREB", "RETENCION IIBB", "IMPUESTO LEY 25413", "IMP S/CRED CT", "SELLADO"],
)
def test_retenciones_e_impuestos_generan_asiento(concepto):
    clasificacion = clasificar_sin_coincidencia("banco", concepto, entra=False)
    assert clasificacion.tipo == TIPO_RETENCION_IMPUESTO
    assert clasificacion.accion == ACCION_ASIENTO
    assert clasificacion.contracuenta == CONTRACUENTA_RETENCIONES


def test_impuesto_sobre_credito_gana_sobre_el_signo():
    # IMP S/CRED es una acreditacion del extracto, pero sigue siendo impuesto:
    # la regla de retencion/impuesto se prueba antes que el signo.
    clasificacion = clasificar_sin_coincidencia("banco", "IMP S/CRED CT", entra=True)
    assert clasificacion.tipo == TIPO_RETENCION_IMPUESTO


def test_acreditacion_sin_comprobante_es_ingreso_no_registrado():
    clasificacion = clasificar_sin_coincidencia("banco", "TRANSFERENCIA RECIBIDA", entra=True)
    assert clasificacion.tipo == TIPO_INGRESO_NO_REGISTRADO
    assert clasificacion.accion == ACCION_REVISAR
    assert clasificacion.revisar_manual is True
    assert clasificacion.contracuenta is None


def test_debito_que_no_es_gasto_ni_impuesto_es_debito_automatico():
    clasificacion = clasificar_sin_coincidencia("banco", "PAGO PROVEEDOR", entra=False)
    assert clasificacion.tipo == TIPO_DEBITO_AUTOMATICO
    assert clasificacion.accion == ACCION_ASIENTO
    assert clasificacion.revisar_manual is True


def test_mayor_siempre_es_diferencia_temporal_sin_asiento():
    clasificacion = clasificar_sin_coincidencia("mayor", "COMISION", entra=False)
    assert clasificacion.tipo == TIPO_PENDIENTE_TEMPORAL
    assert clasificacion.accion == ACCION_PENDIENTE
    assert clasificacion.contracuenta is None


def test_los_nombres_genericos_salen_de_la_config():
    # Sin subcategoria, el nombre de la contracuenta es la cuenta configurada:
    # asi el plan de cuentas de cada empresa se cambia desde el .env.
    gasto = clasificar_sin_coincidencia("banco", "INTERESES VARIOS", entra=False)
    assert gasto.regla == settings.CUENTA_GASTOS_BANCARIOS
    retencion = clasificar_sin_coincidencia("banco", "PERCEPCION VARIOS", entra=False)
    assert retencion.regla == settings.CUENTA_RETENCIONES
