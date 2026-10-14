"""
Reporte Markdown de la conciliacion: cuadro de gastos y acta de conciliacion.

Es lo que el analista pega en el informe. Son dos bloques de texto, ya
formateados, que salen del mismo cruce que la pantalla:

1. Cuadro de gastos bancarios: agrupa los conceptos repetidos del extracto
   (comisiones, IVA, impuestos, sellados, percepciones) en un solo renglon y
   suma sus importes. La columna de creditos queda en 0.00 porque son gastos
   (debitos), y la tabla cierra con la fila "Suma total".

2. Acta de conciliacion: el puente matematico entre el saldo del Libro Mayor y
   el saldo del banco, con las cuatro partidas que explican la diferencia
   (cobranzas no registradas, gastos del banco, cheques no cobrados y
   transferencias en transito).

El formato de numeros sigue el ejemplo del spec: separador de miles con coma y
dos decimales ("-561,356.18"), que no es el formato local ("-561.356,18") pero
es el que viene pedido.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

CENTAVO = Decimal("0.01")


def _dec(valor: Any) -> Decimal:
    """Convierte a Decimal con 2 decimales, redondeo bancario."""
    try:
        return Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def formatear_moneda(valor: Any) -> str:
    """Importe con separador de miles y dos decimales: '-561,356.18'."""
    return f"{_dec(valor):,.2f}"


def cuadro_gastos_markdown(tabla: list[dict]) -> str:
    """Tabla Markdown del cuadro de gastos bancarios.

    Los creditos van siempre en 0.00: el cuadro resume lo que el banco debito,
    no lo que acredito. Se incluye la fila "Suma total" con el total del mes.
    """
    lineas = [
        "| Concepto | SUM de Credito | SUM de Debito en $ |",
        "| --- | ---: | ---: |",
    ]

    total_debito = Decimal("0.00")
    for fila in tabla:
        debito = _dec(fila.get("suma_debito"))
        total_debito += debito
        concepto = (fila.get("concepto") or "").strip() or "SIN CONCEPTO"
        lineas.append(f"| {concepto} | 0.00 | {formatear_moneda(debito)} |")

    lineas.append(f"| Suma total | 0.00 | {formatear_moneda(total_debito)} |")
    return "\n".join(lineas)


def acta_conciliacion(
    *,
    total_debe_mayor: Any,
    total_haber_mayor: Any,
    total_credito_banco: Any,
    total_debito_banco: Any,
    pendientes_banco: list[dict],
    pendientes_mayor: list[dict],
    tabla_gastos: list[dict],
) -> tuple[dict, str]:
    """Arma el acta de conciliacion (valores y texto Markdown).

    El saldo del mayor y el del banco son la variacion neta del periodo:

      mayor = Debe - Haber        (Debe es entrada)
      banco = Credito - Debito    (Credito es entrada)

    Las cuatro partidas son los movimientos sin par de cada lado, que es
    exactamente lo que el acta tiene que explicar. La "diferencia sin
    justificar" es lo que queda afuera de esas cuatro categorias (por ejemplo
    un debito bancario que no es gasto del banco): si el cruce esta completo,
    da 0.00.
    """
    saldo_libro_mayor = _dec(total_debe_mayor) - _dec(total_haber_mayor)
    saldo_banco = _dec(total_credito_banco) - _dec(total_debito_banco)

    # Ingresos del banco que la empresa no registro: creditos sin par.
    ingresos_no_registrados = sum(
        (_dec(p.get("credito")) for p in pendientes_banco), Decimal("0.00")
    )
    # Gastos, comisiones e impuestos del banco: el total del cuadro de gastos.
    egresos_no_registrados = sum(
        (abs(_dec(f.get("suma_debito"))) for f in tabla_gastos), Decimal("0.00")
    )
    # Pagos/cheques emitidos que el banco todavia no debito: egresos del mayor.
    cheques_no_cobrados = sum(
        (_dec(p.get("haber")) for p in pendientes_mayor), Decimal("0.00")
    )
    # Cobros que la empresa registro y el banco todavia no acredito.
    transferencias_transito = sum(
        (_dec(p.get("debe")) for p in pendientes_mayor), Decimal("0.00")
    )

    # Partidas del acta con el signo con que se muestran en el informe.
    ingresos = ingresos_no_registrados
    egresos = -egresos_no_registrados
    cheques = cheques_no_cobrados
    transito = -transferencias_transito

    diferencia = (
        saldo_libro_mayor + ingresos + egresos + cheques + transito - saldo_banco
    )

    valores = {
        "saldo_libro_mayor": float(saldo_libro_mayor),
        "ingresos_no_registrados": float(ingresos),
        "egresos_no_registrados": float(egresos),
        "cheques_no_cobrados": float(cheques),
        "transferencias_transito": float(transito),
        "saldo_banco": float(saldo_banco),
        "diferencia": float(diferencia),
    }

    texto = "\n".join([
        f"Saldo Final según Libro Mayor: $ {formatear_moneda(saldo_libro_mayor)}",
        f"(+) Ingresos bancarios no registrados en Mayor (Cobranzas): $ {formatear_moneda(ingresos)}",
        f"(-) Egresos bancarios no registrados en Mayor (Total Cuadro Gastos): $ {formatear_moneda(egresos)}",
        f"(+) Cheques / Pagos emitidos no cobrados por el banco: $ {formatear_moneda(cheques)}",
        f"(-) Transferencias en tránsito (Ingresos Mayor no en Banco): $ {formatear_moneda(transito)}",
        f"= Saldo Final según Banco: $ {formatear_moneda(saldo_banco)}",
        f"Diferencia sin justificar: $ {formatear_moneda(diferencia)}",
    ])

    return valores, texto


def generar_reporte(
    *,
    total_debe_mayor: Any,
    total_haber_mayor: Any,
    total_credito_banco: Any,
    total_debito_banco: Any,
    pendientes_banco: list[dict],
    pendientes_mayor: list[dict],
    tabla_gastos: list[dict],
) -> dict:
    """Los dos bloques del reporte listos para la respuesta de la API."""
    valores, texto_acta = acta_conciliacion(
        total_debe_mayor=total_debe_mayor,
        total_haber_mayor=total_haber_mayor,
        total_credito_banco=total_credito_banco,
        total_debito_banco=total_debito_banco,
        pendientes_banco=pendientes_banco,
        pendientes_mayor=pendientes_mayor,
        tabla_gastos=tabla_gastos,
    )
    return {
        "cuadro_gastos": cuadro_gastos_markdown(tabla_gastos),
        "acta_conciliacion": texto_acta,
        "acta": valores,
    }
