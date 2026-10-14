"""Tests de la conciliación avanzada FO 02-03."""

import pytest
from decimal import Decimal

from app.services.conciliador_avanzado import (
    conciliar_avanzado,
    _normalizar_banco,
    _normalizar_mayor,
    _matching_exacto,
    _clasificar_ajustes_y_pendientes,
    _cuadro_control,
    _tabla_dinamica_gastos,
)
from app.models.schemas import MovimientoBancario
from app.services.clasificacion import clasificar, es_gasto_bancario


class TestNormalizacion:
    """Tests de normalización de movimientos."""

    def test_normalizar_banco_importe_unificado(self):
        mov = MovimientoBancario(
            fecha="2026-07-01",
            concepto="COBRO",
            debe=0,
            haber=1000,
            saldo=1000,
            referencia="REF-1",
        )
        n = _normalizar_banco(mov, 0)
        assert n.origen == "banco"
        assert n.importe_unificado == Decimal("1000.00")
        assert n.debe == Decimal("0.00")
        assert n.haber == Decimal("1000.00")

    def test_normalizar_banco_egreso(self):
        mov = MovimientoBancario(
            fecha="2026-07-01",
            concepto="COMISION",
            debe=150,
            haber=0,
            saldo=850,
            referencia="OP-1",
        )
        n = _normalizar_banco(mov, 0)
        assert n.importe_unificado == Decimal("-150.00")

    def test_normalizar_mayor_entrada(self):
        mov = {"fecha": "2026-07-01", "concepto": "FACTURA", "debe": 1000, "haber": 0, "comprobante": "FCA-1"}
        n = _normalizar_mayor(mov, 0)
        assert n.origen == "mayor"
        assert n.importe_unificado == Decimal("1000.00")

    def test_normalizar_mayor_salida(self):
        mov = {"fecha": "2026-07-01", "concepto": "PAGO", "debe": 0, "haber": 500, "comprobante": "PAG-1"}
        n = _normalizar_mayor(mov, 0)
        assert n.importe_unificado == Decimal("-500.00")


class TestMatchingExacto:
    """Tests del algoritmo de matching exacto."""

    def test_matching_mismo_dia_mismo_importe(self):
        banco = [
            {"fecha": "2026-07-01", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "R1"},
            {"fecha": "2026-07-02", "concepto": "PAGO", "debe": 500, "haber": 0, "saldo": 500, "referencia": "R2"},
        ]
        mayor = [
            {"fecha": "2026-07-01", "concepto": "FACTURA", "debe": 1000, "haber": 0, "comprobante": "F1"},
            {"fecha": "2026-07-02", "concepto": "PAGO PROV", "debe": 0, "haber": 500, "comprobante": "P1"},
        ]

        banco_n = [_normalizar_banco(MovimientoBancario(**b), i) for i, b in enumerate(banco)]
        mayor_n = [_normalizar_mayor(m, i) for i, m in enumerate(mayor)]

        pares, usados_b, usados_m = _matching_exacto(banco_n, mayor_n)

        assert len(pares) == 2
        assert 0 in [p[0] for p in pares]  # banco idx 0
        assert 1 in [p[0] for p in pares]  # banco idx 1

    def test_matching_fecha_dentro_tolerancia(self):
        """Fecha banco 1 día después de fecha mayor -> debe matchear."""
        banco = [{"fecha": "2026-07-02", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "R1"}]
        mayor = [{"fecha": "2026-07-01", "concepto": "FACTURA", "debe": 1000, "haber": 0, "comprobante": "F1"}]

        banco_n = [_normalizar_banco(MovimientoBancario(**b), 0) for b in banco]
        mayor_n = [_normalizar_mayor(m, 0) for m in mayor]

        pares, _, _ = _matching_exacto(banco_n, mayor_n)
        assert len(pares) == 1

    def test_matching_fuera_tolerancia_no_matchea(self):
        """Fecha banco 5 días después de fecha mayor -> NO matchea (tolerancia 3)."""
        banco = [{"fecha": "2026-07-06", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "R1"}]
        mayor = [{"fecha": "2026-07-01", "concepto": "FACTURA", "debe": 1000, "haber": 0, "comprobante": "F1"}]

        banco_n = [_normalizar_banco(MovimientoBancario(**b), 0) for b in banco]
        mayor_n = [_normalizar_mayor(m, 0) for m in mayor]

        pares, _, _ = _matching_exacto(banco_n, mayor_n, tolerancia_dias=3)
        assert len(pares) == 0

    def test_un_banco_un_mayor_uno_a_uno(self):
        """Un movimiento de banco no puede emparejarse con dos de mayor."""
        banco = [{"fecha": "2026-07-01", "concepto": "COBRO", "debe": 0, "haber": 1000, "saldo": 1000, "referencia": "R1"}]
        mayor = [
            {"fecha": "2026-07-01", "concepto": "FACTURA 1", "debe": 1000, "haber": 0, "comprobante": "F1"},
            {"fecha": "2026-07-01", "concepto": "FACTURA 2", "debe": 1000, "haber": 0, "comprobante": "F2"},
        ]

        banco_n = [_normalizar_banco(MovimientoBancario(**b), 0) for b in banco]
        mayor_n = [_normalizar_mayor(m, i) for i, m in enumerate(mayor)]

        pares, usados_b, usados_m = _matching_exacto(banco_n, mayor_n)

        assert len(pares) == 1
        assert len(set(p[1] for p in pares)) == 1  # solo un mayor usado


class TestClasificacionAjustesPendientes:
    """Tests de clasificación de no emparejados."""

    def test_gasto_bancario_se_clasifica_como_ajuste(self):
        banco = [
            {"fecha": "2026-07-01", "concepto": "COMISION", "debe": 150, "haber": 0, "saldo": 850, "referencia": "OP-1"},
        ]
        mayor = []

        banco_n = [_normalizar_banco(MovimientoBancario(**b), 0) for b in banco]
        mayor_n = []

        _, usados_b, usados_m = _matching_exacto(banco_n, mayor_n)
        ajustes, pendientes = _clasificar_ajustes_y_pendientes(banco_n, mayor_n, usados_b, usados_m)

        assert len(ajustes) == 1
        assert ajustes[0]["origen"] == "ajuste_contable"
        assert ajustes[0]["concepto"] == "COMISION"

    def test_pago_operativo_en_banco_sin_par_es_pendiente_banco(self):
        """Pago a proveedor en banco sin par -> pendiente_banco (no es gasto)."""
        banco = [{"fecha": "2026-07-01", "concepto": "PAGO PROVEEDOR", "debe": 500, "haber": 0, "saldo": 500, "referencia": "OP-1"}]
        mayor = []

        banco_n = [_normalizar_banco(MovimientoBancario(**b), 0) for b in banco]
        mayor_n = []

        _, usados_b, usados_m = _matching_exacto(banco_n, mayor_n)
        ajustes, pendientes = _clasificar_ajustes_y_pendientes(banco_n, mayor_n, usados_b, usados_m)

        assert len(ajustes) == 0
        assert len(pendientes) == 1
        assert pendientes[0]["origen"] == "pendiente_banco"

    def test_movimiento_mayor_sin_par_es_pendiente_mayor(self):
        banco = []
        mayor = [{"fecha": "2026-07-01", "concepto": "PAGO PROVEEDOR", "debe": 0, "haber": 500, "comprobante": "CH-123"}]

        banco_n = []
        mayor_n = [_normalizar_mayor(m, 0) for m in mayor]

        _, usados_b, usados_m = _matching_exacto(banco_n, mayor_n)
        ajustes, pendientes = _clasificar_ajustes_y_pendientes(banco_n, mayor_n, usados_b, usados_m)

        assert len(ajustes) == 0
        assert len(pendientes) == 1
        assert pendientes[0]["origen"] == "pendiente_mayor"


class TestCuadroControl:
    """Tests del cuadro de control FO 02-03."""

    def test_cuadro_control_totales(self):
        banco = [
            _normalizar_banco(MovimientoBancario(fecha="2026-07-01", concepto="COBRO", debe=0, haber=1000, saldo=1000, referencia="R1"), 0),
            _normalizar_banco(MovimientoBancario(fecha="2026-07-02", concepto="PAGO", debe=500, haber=0, saldo=500, referencia="R2"), 1),
        ]
        mayor = [
            _normalizar_mayor({"fecha": "2026-07-01", "concepto": "FACTURA", "debe": 1000, "haber": 0, "comprobante": "F1"}, 0),
            _normalizar_mayor({"fecha": "2026-07-02", "concepto": "PAGO", "debe": 0, "haber": 500, "comprobante": "P1"}, 1),
        ]
        pares = [(0, 0), (1, 1)]  # banco idx 0 con mayor idx 0, banco 1 con mayor 1
        ajustes = []
        pendientes_banco = []
        pendientes_mayor = []

        control = _cuadro_control(banco, mayor, pares, ajustes, [], [])

        assert control["ingresos"]["empresa_total"] == 1000  # mayor debe=1000
        assert control["ingresos"]["banco_total"] == 1000
        assert control["egresos"]["empresa_total"] == 500
        assert control["egresos"]["banco_total"] == 500


class TestTablaDinamicaGastos:
    """Tests de la tabla dinámica de gastos bancarios."""

    def test_tabla_dinamica_agrupa_por_concepto_original(self):
        """Agrupa por el concepto original normalizado (mayúsculas, sin espacios extra)."""
        ajustes = [
            {"origen": "ajuste_contable", "concepto": "COMISION", "importe": -150},
            {"origen": "ajuste_contable", "concepto": "IVA", "importe": -200},
            {"origen": "ajuste_contable", "concepto": "COMISION", "importe": -50},
            {"origen": "ajuste_contable", "concepto": "ING BRUTOS PERCEP", "importe": -250},
        ]
        tabla = _tabla_dinamica_gastos(ajustes)

        # Debe agrupar por concepto original normalizado
        por_concepto = {row["concepto"]: row for row in tabla}
        assert por_concepto["COMISION"]["suma"] == 200.0  # 150 + 50
        assert por_concepto["IVA"]["suma"] == 200.0
        assert por_concepto["ING BRUTOS PERCEP"]["suma"] == 250.0
        assert abs(sum(row["suma"] for row in tabla) - 650.0) < 0.01
        # Los gastos del banco son débitos: la suma de débito va en negativo.
        assert por_concepto["COMISION"]["suma_debito"] == -200.0
        assert por_concepto["COMISION"]["suma_credito"] == 0.0

    def test_tabla_dinamica_separa_credito_y_debito(self):
        """Un concepto puede tener crédito y débito: se suman por separado."""
        ajustes = [
            {"origen": "ajuste_contable", "concepto": "IMP S/CRED CT", "debito": 300, "credito": 0},
            {"origen": "ajuste_contable", "concepto": "IMP S/CRED CT", "debito": 0, "credito": 45},
        ]
        tabla = _tabla_dinamica_gastos(ajustes)

        fila = tabla[0]
        assert fila["concepto"] == "IMP S/CRED CT"
        assert fila["suma_credito"] == 45.0
        assert fila["suma_debito"] == -300.0

    def test_tabla_dinamica_orden_descendente(self):
        ajustes = [
            {"origen": "ajuste_contable", "concepto": "IVA", "importe": -100},
            {"origen": "ajuste_contable", "concepto": "COMISION", "importe": -500},
        ]
        tabla = _tabla_dinamica_gastos(ajustes)
        assert tabla[0]["concepto"] == "COMISION"
        assert tabla[1]["concepto"] == "IVA"


class TestReporteMarkdown:
    """Tests del reporte Markdown: cuadro de gastos y acta de conciliación."""

    def test_cuadro_gastos_agrupa_y_cierra_con_suma_total(self):
        from app.services.reporte_markdown import cuadro_gastos_markdown

        tabla = [
            {"concepto": "COM MANT CT", "suma_credito": 0.0, "suma_debito": -55000.0},
            {"concepto": "IVA", "suma_credito": 0.0, "suma_debito": -14076.2},
        ]
        md = cuadro_gastos_markdown(tabla)

        assert "| Concepto | SUM de Credito | SUM de Debito en $ |" in md
        assert "| COM MANT CT | 0.00 | -55,000.00 |" in md
        assert "| IVA | 0.00 | -14,076.20 |" in md
        # La fila final suma los débitos del mes.
        assert "| Suma total | 0.00 | -69,076.20 |" in md

    def test_cuadro_gastos_fuerza_creditos_en_cero(self):
        from app.services.reporte_markdown import cuadro_gastos_markdown

        tabla = [
            {"concepto": "IMP S/CRED CT", "suma_credito": 45.0, "suma_debito": -300.0},
        ]
        md = cuadro_gastos_markdown(tabla)
        # Aunque el concepto tenga un crédito, el cuadro de gastos muestra 0.00.
        assert "| IMP S/CRED CT | 0.00 | -300.00 |" in md

    def test_cuadro_gastos_sin_filas_igual_tiene_suma_total(self):
        from app.services.reporte_markdown import cuadro_gastos_markdown

        md = cuadro_gastos_markdown([])
        assert "| Suma total | 0.00 | 0.00 |" in md

    def test_acta_concilia_y_da_diferencia_cero(self):
        from app.services.reporte_markdown import acta_conciliacion

        # Banco: +1000 cobrado y -100 de gasto; Mayor: +1000 registrado.
        valores, texto = acta_conciliacion(
            total_debe_mayor=1000,
            total_haber_mayor=0,
            total_credito_banco=1000,
            total_debito_banco=100,
            pendientes_banco=[],
            pendientes_mayor=[],
            tabla_gastos=[{"concepto": "COM", "suma_debito": -100.0}],
        )

        assert valores["diferencia"] == 0.0
        assert "Saldo Final según Libro Mayor: $ 1,000.00" in texto
        assert "(-) Egresos bancarios no registrados en Mayor (Total Cuadro Gastos): $ -100.00" in texto
        assert "= Saldo Final según Banco: $ 900.00" in texto
        assert "Diferencia sin justificar: $ 0.00" in texto

    def test_acta_reporta_la_diferencia_sin_justificar(self):
        from app.services.reporte_markdown import acta_conciliacion

        # Un débito del banco que no es gasto (no entra en ninguna categoría).
        valores, _ = acta_conciliacion(
            total_debe_mayor=0,
            total_haber_mayor=0,
            total_credito_banco=0,
            total_debito_banco=48200,
            pendientes_banco=[{"credito": 0.0, "debito": 48200.0}],
            pendientes_mayor=[],
            tabla_gastos=[],
        )
        assert valores["diferencia"] == 48200.0



class TestConciliacionAvanzadaIntegracion:
    """Tests de integración completa."""

    def test_conciliacion_simple_completa(self):
        banco = [
            MovimientoBancario(fecha="2026-07-01", concepto="COBRO", debe=0, haber=1000, saldo=1000, referencia="R1"),
            MovimientoBancario(fecha="2026-07-02", concepto="COMISION", debe=150, haber=0, saldo=850, referencia="OP-1"),
        ]
        mayor = [
            {"fecha": "2026-07-01", "concepto": "FACTURA 1", "debe": 1000, "haber": 0, "comprobante": "F1"},
            {"fecha": "2026-07-02", "concepto": "PAGO COMISION", "debe": 0, "haber": 150, "comprobante": "P1"},
        ]

        resultado = conciliar_avanzado(banco, mayor)

        # El cobro y la comisión matchean (mismo importe 150, misma fecha)
        assert len(resultado.conciliados) == 2
        assert len(resultado.ajustes_contables) == 0  # la comisión matcheó con el mayor
        assert len([p for p in resultado.partidas_pendientes if p["origen"] == "pendiente_mayor"]) == 0
        assert resultado.cuadro_control["ingresos"]["conciliados"] == 1000.0
        assert resultado.estadisticas["conciliados"] == 2
        assert resultado.estadisticas["ajustes_contables"] == 0

    def test_enriquecimiento_extracto_crudo(self):
        """Verifica que el extracto crudo enriquece con CUIT/Nombre."""
        banco = [
            MovimientoBancario(fecha="2026-07-01", concepto="COBRO", debe=0, haber=1000, saldo=1000, referencia="R1"),
        ]
        mayor = [
            {"fecha": "2026-07-01", "concepto": "COBRO", "debe": 1000, "haber": 0, "comprobante": "F1"},
        ]
        extracto = [{
            "Fecha contable": "2026-07-01",
            "Concepto": "COBRO",
            "Debito en $": 0,
            "Credito en $": 1000,
            "Saldo en $": 1000,
            "Nro doc": "30-12345678-9",
            "Nombre": "CLIENTE TEST S.A.",
            "CBU/Alias": "0000000000000000000001",
        }]

        resultado = conciliar_avanzado(banco, mayor, extracto_crudo=extracto)

        assert len(resultado.conciliados) == 1
        conc = resultado.conciliados[0]
        assert conc["cuit"] == "30-12345678-9"
        assert conc["nombre_tercero"] == "CLIENTE TEST S.A."
        assert conc["cbu"] == "0000000000000000000001"

    def test_el_resultado_trae_el_reporte_markdown(self):
        """El cruce avanzado arma el cuadro de gastos y el acta en Markdown."""
        banco = [
            MovimientoBancario(fecha="2026-07-01", concepto="COBRO", debe=0, haber=1000, saldo=1000, referencia="R1"),
            MovimientoBancario(fecha="2026-07-02", concepto="COM MANT CT", debe=150, haber=0, saldo=850, referencia="OP-1"),
        ]
        mayor = [
            {"fecha": "2026-07-01", "concepto": "FACTURA 1", "debe": 1000, "haber": 0, "comprobante": "F1"},
        ]

        resultado = conciliar_avanzado(banco, mayor)

        reporte = resultado.reporte_markdown
        assert "| Concepto | SUM de Credito | SUM de Debito en $ |" in reporte["cuadro_gastos"]
        assert "| COM MANT CT | 0.00 | -150.00 |" in reporte["cuadro_gastos"]
        assert "Diferencia sin justificar:" in reporte["acta_conciliacion"]
        assert reporte["acta"]["saldo_banco"] == 850.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])