"""Arma el papel de trabajo FO 02-03 a partir del estado de la conciliacion.

Estructura (hoja "Libro Mayor") - segun modelo de auditoria:

    Filas 1-6   membrete institucional (viene de la plantilla).
    Fila 8      encabezado vacio / separador.
    Fila 9      encabezado: Fecha | Documento | Cuenta | Debe | Haber | Saldo |
                Descripcion | Organizacion | Centro de Costos.
    Fila 10     "Saldo Inicial" con el saldo en la columna F.
    Fila 11+    TODOS los movimientos del mayor ordenados por fecha, saldo por formula.

Hoja "Movimientos Bancarios" - extracto resumido del banco:

    Filas 1-6   membrete (formulas contra Libro Mayor).
    Fila 8      encabezado: Fecha contable | Concepto | Debito en $ | Credito en $ | Saldo en $.
    Fila 9      "Saldo Inicial" con el saldo en la columna E.
    Fila 10+    TODOS los movimientos del extracto (sin repetidos), debito=negativo, credito=positivo, saldo acumulado.

    Encabezado sin relleno y con filtro de Excel (A8:E{ultima fila}). En los datos
    se marca: amarillo = tiene coincidencia (conciliado); verde = no tiene
    coincidencia (partida pendiente). El Libro Mayor usa el mismo criterio.

Cuadro de sumas por subcategoria (cols I-K de Movimientos Bancarios):
    Concepto | Suma Crédito | Suma Débito
    Ingresos Brutos | X | Y
    IVA | X | Y
    Comisiones | X | Y
    Impuestos | X | Y
    Sellado | X | Y
    TOTAL | X | Y

La plantilla (assets/plantillas/FO 02-03 Conciliación Bancaria.xlsx) aporta solo
el membrete: el formulario, su codigo, el titulo y las etiquetas azules son de
la auditoria y no se rehacen en codigo. El cuerpo de las tablas lo escribe este
modulo.
"""

from __future__ import annotations

import io
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from app.models.schemas import (
    EncabezadoConciliacion,
    MovimientoBancoExport,
    MovimientoMayorExport,
    PendienteExport,
    SolicitudExportacion,
)
from app.services.clasificacion import es_gasto_bancario, _subcategoria_gasto

DIRECTORIO_PLANTILLAS = Path(__file__).resolve().parent.parent / "assets" / "plantillas"
NOMBRE_PLANTILLA = "FO 02-03 Conciliación Bancaria.xlsx"

HOJA_MAYOR = "Libro Mayor"
HOJA_MOVIMIENTOS = "Movimientos Bancarios"
HOJA_EXTRACTO_BRUTO = "Extracto Bruto"

# Formatos del formulario. El numero usa el contable heredado de la plantilla
# (el cero se ve "-") y las fechas van dd/mm/yyyy. La celda del periodo es la
# excepcion: el spec la pide en AAAA-MM-DD.
FORMATO_IMPORTE = '_ * #,##0.00_ ;_ * \\-#,##0.00_ ;_ * "-"??_ ;_ @_ '
FORMATO_FECHA = "dd/mm/yyyy"
FORMATO_PERIODO = "yyyy-mm-dd"

# ----------------------------------------------------------------------
# Layout fijo (según plantilla de auditoria)
# ----------------------------------------------------------------------

# Libro Mayor: encabezados en fila 9, Saldo Inicial en 10, datos desde 11
FILA_ENCABEZADO_MAYOR = 9
FILA_SALDO_INICIAL_MAYOR = 10
FILA_PRIMER_DATO_MAYOR = 11

COLUMNAS_MAYOR = [
    "Fecha",      # A
    "Documento",  # B
    "Cuenta",     # C
    "Debe",       # D
    "Haber",      # E
    "Saldo",      # F
    "Descripción",# G
    "Organización", # H
    "Centro de Costos", # I
]

# Movimientos Bancarios: encabezados en fila 8, Saldo Inicial en 9, datos desde 10
FILA_ENCABEZADO_MOV = 8
FILA_SALDO_INICIAL_MOV = 9
FILA_PRIMER_DATO_MOV = 10

COLUMNAS_MOV = [
    "Fecha contable", # A
    "Concepto",       # B
    "Debito en $",    # C (negativo = salida)
    "Credito en $",   # D (positivo = entrada)
    "Saldo en $",     # E (acumulado)
]

# Anchos de columna (caracteres)
ANCHOS_MAYOR = {"A": 12.0, "B": 22.0, "C": 28.0, "D": 16.0, "E": 16.0, "F": 18.0, "G": 35.0, "H": 22.0, "I": 18.0}
ANCHOS_MOV = {"A": 14.0, "B": 45.0, "C": 18.0, "D": 18.0, "E": 18.0, "I": 16.0, "J": 18.0, "K": 18.0}

# ----------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------

RELLENO_ENCABEZADO = PatternFill("solid", fgColor="FF00B0F0")
RELLENO_CONCILIADO = PatternFill("solid", fgColor="FFFFFF00")     # amarillo: tiene coincidencia
RELLENO_NO_CONCILIADO = PatternFill("solid", fgColor="FF93C47D")  # verde: sin coincidencia (pendiente)
RELLENO_AJUSTE_CONTABLE = PatternFill("solid", fgColor="FFE69138")  # naranja: gasto del banco sin asiento
FUENTE_ENCABEZADO = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FUENTE_ENCABEZADO_OSCURO = Font(name="Calibri", size=11, bold=True)  # para fondos claros
FUENTE_TITULO = Font(name="Calibri", size=11, bold=True)
FUENTE_SALDO_INICIAL = Font(name="Calibri", size=11, bold=True)
FUENTE_NORMAL = Font(name="Calibri", size=11)
ALINEACION_CENTRO = Alignment(horizontal="center")
ALINEACION_DERECHA = Alignment(horizontal="right", shrink_to_fit=True)
BORDE_FINO = Border(bottom=Side(style="thin"))
BORDE_DOBLE = Border(top=Side(style="thin"), bottom=Side(style="double"))
BORDE_CUADRO = Border(
    top=Side(style="thin"), bottom=Side(style="thin"),
    left=Side(style="thin"), right=Side(style="thin")
)

# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------

def ruta_plantilla() -> Path:
    return DIRECTORIO_PLANTILLAS / NOMBRE_PLANTILLA


def _escribir_membrete(hoja: Worksheet, encabezado: EncabezadoConciliacion) -> None:
    """Los cuatro campos del membrete de FO 02-03."""
    hoja["B5"] = encabezado.empresa or ""
    hoja["B6"] = encabezado.banco or ""
    hoja["I6"] = encabezado.numero_cuenta or ""
    periodo = _periodo_a_fecha(encabezado.periodo)
    if periodo is not None:
        hoja["I5"] = periodo
        hoja["I5"].number_format = FORMATO_PERIODO
        hoja["I5"].alignment = ALINEACION_CENTRO
    elif encabezado.periodo:
        hoja["I5"] = encabezado.periodo


def _restaurar_formulas_membrete(hoja: Worksheet) -> None:
    """La hoja de movimientos toma el membrete por formula contra Libro Mayor."""
    hoja["B5"] = "=+'Libro Mayor'!B5"
    hoja["B6"] = "=+'Libro Mayor'!B6"
    hoja["I5"] = "=+'Libro Mayor'!I5"
    hoja["I6"] = "=+'Libro Mayor'!I6"
    hoja["I5"].number_format = FORMATO_PERIODO
    hoja["I5"].alignment = ALINEACION_CENTRO


def _periodo_a_fecha(periodo: str | None) -> date | None:
    if not periodo:
        return None
    texto = periodo.strip()
    for fmt in ("%Y-%m", "%Y/%m", "%m/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _fecha(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and valor.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(valor.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _importe(valor: object) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return 0.0
    if n != n or n in (float("inf"), float("-inf")):
        return 0.0
    return round(n, 2)


def _escribir_fila(
    hoja: Worksheet,
    fila: int,
    valores: list,
    columna_base: int = 1,
    formato_importe_idx: set[int] | None = None,
    fuente: Font | None = None,
) -> None:
    if formato_importe_idx is None:
        formato_importe_idx = set()
    for i, v in enumerate(valores):
        celda = hoja.cell(row=fila, column=columna_base + i, value=v)
        if i in formato_importe_idx and isinstance(v, (int, float)):
            celda.number_format = FORMATO_IMPORTE
            celda.alignment = ALINEACION_DERECHA
        elif isinstance(v, date):
            celda.number_format = FORMATO_FECHA
            celda.alignment = ALINEACION_CENTRO
        if fuente:
            celda.font = fuente


def _escribir_encabezados(hoja: Worksheet, fila: int, columnas: list[str], columna_base: int = 1, con_relleno: bool = True) -> None:
    for i, nombre in enumerate(columnas):
        celda = hoja.cell(row=fila, column=columna_base + i, value=nombre)
        # Con relleno azul el texto va blanco; sin relleno el fondo es blanco y
        # el texto blanco quedaria invisible (era lo que pasaba en el Libro
        # Mayor: los titulos, incluido "Fecha", desaparecian).
        celda.font = FUENTE_ENCABEZADO if con_relleno else FUENTE_ENCABEZADO_OSCURO
        if con_relleno:
            celda.fill = RELLENO_ENCABEZADO
        celda.alignment = ALINEACION_CENTRO


def _clave_mayor(fecha, concepto, comprobante, debe, haber) -> tuple:
    return (
        _fecha(fecha).isoformat() if _fecha(fecha) else "",
        (concepto or "").strip(),
        (comprobante or "").strip(),
        round(_importe(debe), 2),
        round(_importe(haber), 2),
    )


def _clave_banco(fecha, concepto, debe, haber) -> tuple:
    return (
        _fecha(fecha).isoformat() if _fecha(fecha) else "",
        (concepto or "").strip(),
        round(_importe(debe), 2),
        round(_importe(haber), 2),
    )


def _sin_repetidos(movimientos: list[MovimientoBancoExport]) -> list[MovimientoBancoExport]:
    """Descarta lineas repetidas del extracto (mismo concepto, debe, haber, referencia)."""
    vistos = set()
    unicos: list[MovimientoBancoExport] = []
    for m in movimientos:
        clave = (
            _fecha(m.fecha).isoformat() if _fecha(m.fecha) else "",
            (m.concepto or "").strip(),
            round(_importe(m.debe), 2),
            round(_importe(m.haber), 2),
            (m.referencia or "").strip(),
        )
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(m)
    return unicos


# ----------------------------------------------------------------------
# Hoja LIBRO MAYOR
# ----------------------------------------------------------------------

def _fecha_saldo_inicial(solicitud: SolicitudExportacion) -> date | None:
    """
    Fecha de apertura para la fila "Saldo Inicial".

    El modelo de auditoria la escribe un dia antes del primer movimiento (30/06
    en un periodo que arranca el 01/07). Si no hay movimientos con fecha, se usa
    el inicio del periodo menos un dia.
    """
    fechas = [f for f in (_fecha(m.fecha) for m in solicitud.movimientos_mayor) if f]
    if fechas:
        return min(fechas) - timedelta(days=1)
    periodo = _periodo_a_fecha(solicitud.encabezado.periodo)
    if periodo is not None:
        return periodo - timedelta(days=1)
    return None


def _armar_libro_mayor(hoja: Worksheet, solicitud: SolicitudExportacion, pendientes_xubio: Counter) -> None:
    """Una sola tabla: Saldo Inicial + todos los movimientos del mayor ordenados por fecha."""
    # Anchos
    for col, ancho in ANCHOS_MAYOR.items():
        hoja.column_dimensions[col].width = ancho

    # Encabezados en fila 9
    _escribir_encabezados(hoja, FILA_ENCABEZADO_MAYOR, COLUMNAS_MAYOR, con_relleno=False)

    # Fila Saldo Inicial (10). El modelo de auditoria la escribe con la fecha de
    # apertura (el dia anterior al primer movimiento): sin eso la fila aparecia
    # sin fecha y se perdia el arranque del periodo. La cuenta se deja vacia: el
    # mayor de la pantalla trae todas las cuentas, asi que poner "la primera"
    # seria una cuenta cualquiera y no la del banco que se concilia.
    fila = FILA_SALDO_INICIAL_MAYOR
    _escribir_fila(
        hoja, fila,
        [
            _fecha_saldo_inicial(solicitud),
            "Saldo Inicial",
            None, None, None, solicitud.saldo_inicial_mayor, None, None, None,
        ],
        formato_importe_idx={5},  # col F (idx 5 base 0)
        fuente=FUENTE_SALDO_INICIAL,
    )
    # Formula en F para que arrastre: la primera fila de datos la usara
    hoja.cell(row=fila, column=6).number_format = FORMATO_IMPORTE
    hoja.cell(row=fila, column=6).alignment = ALINEACION_DERECHA

    # Combinar todos los movimientos del mayor (conciliados + pendientes Xubio)
    # En el papel de trabajo el Libro Mayor muestra TODO, no solo pendientes.
    # Orden: por fecha, luego por concepto.
    todos_mayor = list(solicitud.movimientos_mayor)
    todos_mayor.sort(key=lambda m: (_fecha(m.fecha) or date.min, m.concepto or ""))

    fila = FILA_PRIMER_DATO_MAYOR
    for mov in todos_mayor:
        debe = _importe(mov.debe)
        haber = _importe(mov.haber)
        # Formula de saldo: =F(anterior)+D(este)-E(este)
        if fila == FILA_PRIMER_DATO_MAYOR:
            formula_saldo = f"=F{fila-1}+D{fila}-E{fila}"
        else:
            formula_saldo = f"=F{fila-1}+D{fila}-E{fila}"

        _escribir_fila(
            hoja, fila,
            [
                _fecha(mov.fecha),
                mov.documento or mov.comprobante or "",  # B: Documento
                mov.cuenta or "",                        # C: Cuenta
                debe if debe else None,                  # D: Debe
                haber if haber else None,                # E: Haber
                None,                                    # F: Saldo -> formula
                mov.descripcion or mov.concepto or "",   # G: Descripción
                mov.organizacion or "",                  # H: Organización
                "",                                      # I: Centro de Costos
            ],
            formato_importe_idx={3, 4},  # D, E
        )
        celda_saldo = hoja.cell(row=fila, column=6, value=formula_saldo)
        celda_saldo.number_format = FORMATO_IMPORTE
        celda_saldo.alignment = ALINEACION_DERECHA

        # Resaltar: amarillo si tiene coincidencia (conciliado), verde si no la
        # tiene (partida pendiente del mayor). Solo se pintan las celdas con importe.
        clave = _clave_mayor(mov.fecha, mov.concepto, mov.comprobante, mov.debe, mov.haber)
        es_pendiente = pendientes_xubio.get(clave, 0) > 0
        relleno = RELLENO_CONCILIADO
        if es_pendiente:
            pendientes_xubio[clave] -= 1
            relleno = RELLENO_NO_CONCILIADO
        if debe or haber:
            for col_idx in (4, 5):  # D, E
                c = hoja.cell(row=fila, column=col_idx)
                if c.value not in (None, 0):
                    c.fill = relleno

        fila += 1


# ----------------------------------------------------------------------
# Hoja MOVIMIENTOS BANCARIOS
# ----------------------------------------------------------------------


def _armar_movimientos_bancarios(
    hoja: Worksheet,
    solicitud: SolicitudExportacion,
    pendientes_banco_counter: Counter,
) -> None:
    """Tabla de 5 columnas: Fecha | Concepto | Debito | Credito | Saldo (acumulado).

    Encabezado sin relleno y con filtro de Excel (A8:E{ultima fila}). En los datos
    se marca el criterio de la conciliacion:
      - amarillo: el movimiento del banco tiene coincidencia (conciliado).
      - naranja:  sin coincidencia y es gasto del banco (comision, IVA,
                  impuesto, retencion): ajuste contable que falta asentar.
      - verde:    sin coincidencia y no es gasto (ej. transferencia sin
                  identificar): partida pendiente a investigar.
    """
    # Anchos
    for col, ancho in ANCHOS_MOV.items():
        hoja.column_dimensions[col].width = ancho

    # Encabezados en fila 8, sin relleno (texto oscuro para que se lea)
    _escribir_encabezados(hoja, FILA_ENCABEZADO_MOV, COLUMNAS_MOV, con_relleno=False)

    # Fila Saldo Inicial (9) - solo el saldo en col E
    _escribir_fila(
        hoja, FILA_SALDO_INICIAL_MOV,
        [None, "Saldo Inicial", None, None, solicitud.saldo_final_banco],
        formato_importe_idx={4},  # col E
        fuente=FUENTE_SALDO_INICIAL,
    )
    hoja.cell(row=FILA_SALDO_INICIAL_MOV, column=5).number_format = FORMATO_IMPORTE
    hoja.cell(row=FILA_SALDO_INICIAL_MOV, column=5).alignment = ALINEACION_DERECHA

    # Todos los movimientos del banco (conciliados + pendientes banco), sin repetidos
    todos_banco = _sin_repetidos(list(solicitud.movimientos_banco))
    todos_banco.sort(key=lambda m: (_fecha(m.fecha) or date.min, m.concepto or ""))

    fila = FILA_PRIMER_DATO_MOV
    for mov in todos_banco:
        debe = _importe(mov.debe)
        haber = _importe(mov.haber)
        # En el extracto: debito = salida (negativo en C), credito = entrada (positivo en D)
        # Saldo acumulado en E: =E(anterior)+D(este)+C(este)  [C es negativo, D positivo]
        formula_saldo = f"=E{fila-1}+D{fila}+C{fila}"

        _escribir_fila(
            hoja, fila,
            [
                _fecha(mov.fecha),
                mov.concepto or "",
                -debe if debe else None,    # Debito en $ (negativo = salida)
                haber if haber else None,   # Credito en $ (positivo = entrada)
                None,  # Saldo -> formula
            ],
            formato_importe_idx={2, 3},  # C, D
        )
        celda_saldo = hoja.cell(row=fila, column=5, value=formula_saldo)
        celda_saldo.number_format = FORMATO_IMPORTE
        celda_saldo.alignment = ALINEACION_DERECHA

        # Resaltar según el criterio de la conciliación:
        #   amarillo (RELLENO_CONCILIADO): tiene coincidencia (conciliado)
        #   naranja (RELLENO_AJUSTE_CONTABLE): sin coincidencia y es gasto bancario
        #                                     (comisión, IVA, impuesto, retención) → ajuste contable
        #   verde (RELLENO_NO_CONCILIADO): sin coincidencia y no es gasto
        #                                     (ej. transferencia no identificada) → a investigar
        clave = _clave_banco(mov.fecha, mov.concepto, mov.debe, mov.haber)
        es_pendiente = pendientes_banco_counter.get(clave, 0) > 0
        if es_pendiente:
            pendientes_banco_counter[clave] -= 1
            relleno = RELLENO_AJUSTE_CONTABLE if es_gasto_bancario(mov.concepto) else RELLENO_NO_CONCILIADO
        else:
            relleno = RELLENO_CONCILIADO
        if debe or haber:
            for col_idx in (3, 4):  # C, D
                c = hoja.cell(row=fila, column=col_idx)
                if c.value is not None:
                    c.fill = relleno

        fila += 1

    # Filtro de Excel sobre la tabla (A8:E{ultima fila}). Arranca en el
    # encabezado para que los desplegables queden ahi, como el modelo.
    ultima = max(fila - 1, FILA_SALDO_INICIAL_MOV)
    hoja.auto_filter.ref = f"A{FILA_ENCABEZADO_MOV}:E{ultima}"


def _armar_cuadro_subcategorias(
    hoja: Worksheet,
    fila_inicio: int,
    pendientes_banco: list[PendienteExport],
) -> None:
    """Cuadro de sumas por concepto bancario real a la derecha de la tabla (cols I-K).

    Columnas: I=Concepto (original del extracto), J=Suma Crédito, K=Suma Débito.
    Solo muestra conceptos con importe > 0.
    """

    # Acumular por concepto original (normalizado)
    sumas: dict[str, dict[str, float]] = {}
    for p in pendientes_banco:
        if not es_gasto_bancario(p.concepto):
            continue
        concepto_original = (p.concepto or "").strip()
        # Normalizar: mayúsculas, sin espacios múltiples
        concepto_norm = " ".join(concepto_original.upper().split())
        if not concepto_norm:
            concepto_norm = "SIN CONCEPTO"
        debe = _importe(p.debe)
        haber = _importe(p.haber)
        if debe == 0 and haber == 0:
            continue
        if concepto_norm not in sumas:
            sumas[concepto_norm] = {"credito": 0.0, "debito": 0.0}
        sumas[concepto_norm]["credito"] += haber
        sumas[concepto_norm]["debito"] += debe

    if not sumas:
        return

    # Escribir encabezados en fila 8 (misma altura que encabezado tabla principal)
    fila_enc = FILA_ENCABEZADO_MOV
    encabezados = ["Concepto", "Suma Crédito", "Suma Débito"]
    for i, titulo in enumerate(encabezados):
        celda = hoja.cell(row=fila_enc, column=9 + i, value=titulo)  # cols I, J, K
        celda.font = FUENTE_ENCABEZADO_OSCURO  # sin relleno: texto oscuro
        celda.alignment = ALINEACION_CENTRO
        celda.border = BORDE_CUADRO

    # Escribir filas de datos
    fila = fila_enc + 1
    for concepto, valores in sumas.items():
        _escribir_fila(
            hoja,
            fila,
            [
                concepto,
                valores["credito"] if valores["credito"] else None,
                valores["debito"] if valores["debito"] else None,
            ],
            columna_base=9,  # columna I
            formato_importe_idx={1, 2},  # J, K
        )
        for col in (10, 11):  # J, K
            c = hoja.cell(row=fila, column=col)
            c.number_format = FORMATO_IMPORTE
            c.alignment = ALINEACION_DERECHA
            c.border = BORDE_CUADRO
        fila += 1

    # Fila TOTAL
    total_credito = sum(v["credito"] for v in sumas.values())
    total_debito = sum(v["debito"] for v in sumas.values())
    _escribir_fila(
        hoja,
        fila,
        [
            "TOTAL",
            total_credito if total_credito else None,
            total_debito if total_debito else None,
        ],
        columna_base=9,
        formato_importe_idx={1, 2},
    )
    for col in (10, 11):  # J, K
        c = hoja.cell(row=fila, column=col)
        c.number_format = FORMATO_IMPORTE
        c.alignment = ALINEACION_DERECHA
        c.font = FUENTE_TITULO
        c.border = BORDE_CUADRO


# ----------------------------------------------------------------------
# Hoja EXTRACTO BRUTO (opcional - solo si hay datos crudos)
# ----------------------------------------------------------------------


def _armar_extracto_bruto(hoja: Worksheet, datos_brutos: list[dict]) -> None:
    """Escribe el extracto completo tal cual (17 columnas)."""
    if not datos_brutos:
        return
    # Encabezados fijos del extracto ICBC
    encabezados = [
        "Fecha contable", "Cod de Concepto", "Concepto", "Debito en $", "Credito en $",
        "Saldo en $", "Informacion Complementaria", "Nro de cheque", "Sucursal Origen",
        "Canal", "Banco", "CBU/Alias", "Tipo trf", "Referencia", "Nombre",
        "Tipo doc", "Nro doc"
    ]
    _escribir_encabezados(hoja, 1, encabezados)
    for i, row in enumerate(datos_brutos, start=2):
        _escribir_fila(hoja, i, [row.get(h, "") for h in encabezados])


# ----------------------------------------------------------------------
# Punto de entrada
# ----------------------------------------------------------------------


def exportar(solicitud: SolicitudExportacion) -> bytes:
    """Devuelve el .xlsx del papel de trabajo, listo para mandarse como archivo."""
    ruta = ruta_plantilla()
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro la plantilla FO 02-03 en {ruta}")

    libro = load_workbook(ruta)
    try:
        mayor = libro[HOJA_MAYOR]
        movimientos = libro[HOJA_MOVIMIENTOS]

        # Anchos
        for col, ancho in ANCHOS_MAYOR.items():
            mayor.column_dimensions[col].width = ancho
        for col, ancho in ANCHOS_MOV.items():
            movimientos.column_dimensions[col].width = ancho

        # Membrete
        _escribir_membrete(mayor, solicitud.encabezado)
        _restaurar_formulas_membrete(movimientos)

        # Multisets para saber que lineas no tienen coincidencia (van en verde)
        pendientes_xubio = Counter(
            _clave_mayor(p.fecha, p.concepto, p.comprobante, p.debe, p.haber)
            for p in solicitud.pendientes_xubio
        )
        pendientes_banco = Counter(
            _clave_banco(p.fecha, p.concepto, p.debe, p.haber)
            for p in solicitud.pendientes_banco
        )

        # Criterio de color: coincidencia = amarillo, sin coincidencia = verde.
        _armar_libro_mayor(mayor, solicitud, pendientes_xubio)
        _armar_movimientos_bancarios(movimientos, solicitud, pendientes_banco)
        _armar_cuadro_subcategorias(movimientos, FILA_ENCABEZADO_MOV, solicitud.pendientes_banco)

        # Hoja extracto bruto si hay datos (opcional)
        if hasattr(solicitud, "extracto_bruto") and solicitud.extracto_bruto:
            if HOJA_EXTRACTO_BRUTO in libro.sheetnames:
                bruto = libro[HOJA_EXTRACTO_BRUTO]
            else:
                bruto = libro.create_sheet(HOJA_EXTRACTO_BRUTO)
            _armar_extracto_bruto(bruto, solicitud.extracto_bruto)

        destino = io.BytesIO()
        libro.save(destino)
        return destino.getvalue()
    finally:
        libro.close()


def nombre_archivo(solicitud: SolicitudExportacion, hoy: date | None = None) -> str:
    """
    Genera el nombre del archivo siguiendo el estándar FO 02-03:
    {empresa} 02-03 {banco} {fecha_dd-mm-yyyy} ({version}).xlsx

    Ejemplo: "PICCININI Y ASOCIADOS S.A. 02-03 ICBC 13-10-2026 (1).xlsx"
    """
    dia = hoy or date.today()
    partes = [p for p in (solicitud.encabezado.empresa, solicitud.encabezado.banco) if p.strip()]
    if not partes:
        empresa = "SIN_EMPRESA"
        banco = "SIN_BANCO"
    else:
        empresa = partes[0].strip()
        banco = partes[1].strip() if len(partes) > 1 else "SIN_BANCO"

    # Limpieza: solo alfanumérico, espacios, guiones, puntos, ampersand
    limpio_empresa = "".join(c if c.isalnum() or c in " -_.&" else "" for c in empresa).strip()
    limpio_banco = "".join(c if c.isalnum() or c in " -_.&" else "" for c in banco).strip()
    limpio_empresa = " ".join(limpio_empresa.split())
    limpio_banco = " ".join(limpio_banco.split())

    # Fecha en formato DD-MM-YYYY
    periodo = solicitud.encabezado.periodo
    if periodo and periodo.strip():
        # Intentar parsear periodo como YYYY-MM o similar
        texto = periodo.strip()
        for fmt in ("%Y-%m", "%Y/%m", "%m/%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                fecha_parseada = datetime.strptime(texto, fmt)
                cierre = fecha_parseada.strftime("%d-%m-%Y")
                break
            except ValueError:
                continue
        else:
            cierre = dia.strftime("%d-%m-%Y")
    else:
        cierre = dia.strftime("%d-%m-%Y")

    # Version: usar un contador simple basado en la fecha/hora para evitar colisiones
    version = dia.strftime("%H%M%S")[-2:]  # últimos 2 dígitos de hora/min/seg

    return f"{limpio_empresa} 02-03 {limpio_banco} {cierre} ({version}).xlsx"