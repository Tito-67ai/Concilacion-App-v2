"""Arma el papel de trabajo FO 02-03 a partir del estado de la conciliacion.

Estructura (hoja "Libro Mayor"):

    Filas 1-6   membrete institucional (viene de la plantilla).
    Fila 8      encabezado de la Tabla 1 (todos los movimientos del mayor).
    Fila 9      fila de Saldo Inicial (siempre, con el saldo en la col. F).
    ...         Tabla 1: Fecha | Documento | Cuenta | Debe | Haber | Saldo |
                Descripcion | Organizacion | Centro de Costos.
    ...         Tabla 2 "Partidas contables no registradas en banco." (mayor que
                no sono en el extracto).
    ...         Tabla 3 "Partidas en banco pendientes de registracion contable."
                (extracto que no esta en el mayor).
    ...         Pie: saldo final segun mayor, saldo final segun banco y el
                control de diferencia `=F(banco)-F(mayor)`.

Hoja "Movimientos Bancarios": el extracto completo en una sola tabla de 17
columnas (A-Q) que arranca en la fila 8, con el saldo acumulado por formula
`=F(anterior)+E-D` y una fila de control contra el mayor al final.

La plantilla (assets/plantillas/FO 02-03 Conciliación Bancaria.xlsx) aporta solo
el membrete: el formulario, su codigo, el titulo y las etiquetas azules son de
la auditoria y no se rehacen en codigo. El cuerpo de las tablas lo escribe este
modulo. La plantilla se regenera con scripts/generar_plantilla_fo_02_03.py.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.worksheet import Worksheet

from app.models.schemas import (
    EncabezadoConciliacion,
    PendienteExport,
    SolicitudExportacion,
)

DIRECTORIO_PLANTILLAS = Path(__file__).resolve().parent.parent / "assets" / "plantillas"
NOMBRE_PLANTILLA = "FO 02-03 Conciliación Bancaria.xlsx"

HOJA_MAYOR = "Libro Mayor"
HOJA_MOVIMIENTOS = "Movimientos Bancarios"

# El formato del spec: miles con coma, dos decimales. El de la plantilla era el
# contable con guion para el cero; el spec pide este.
FORMATO_IMPORTE = "#,##0.00"
FORMATO_FECHA = "yyyy-mm-dd"

# ----------------------------------------------------------------------
# Layout
# ----------------------------------------------------------------------

FILA_ENCABEZADO_TABLA1 = 8
FILA_ENCABEZADO_MOVIMIENTOS = 8

COLUMNAS_TABLA1 = [
    "Fecha",
    "Documento",
    "Cuenta",
    "Debe",
    "Haber",
    "Saldo",
    "Descripción",
    "Organización",
    "Centro de Costos",
]
COLUMNAS_TABLA2 = [
    "Fecha",
    "Documento",
    "Cuenta",
    "Debe",
    "Haber",
    "Saldo",
    "Descripción",
    "Organización",
]
COLUMNAS_TABLA3 = [
    "Fecha",
    "Documento",
    "Cuenta",
    "Debe",
    "Haber",
    "Saldo",
    "Descripción",
]
COLUMNAS_MOVIMIENTOS = [
    "Fecha contable",
    "Cod de Concepto",
    "Concepto",
    "Debito en $",
    "Credito en $",
    "Saldo en $",
    "Informacion Complementaria",
    "Nro de cheque",
    "Sucursal Origen",
    "Canal",
    "Banco",
    "CBU/Alias",
    "Tipo trf",
    "Referencia",
    "Nombre",
    "Tipo doc",
    "Nro doc",
]

TITULO_PARTIDAS_CONTABLES = "Partidas contables no registradas en banco."
TITULO_PARTIDAS_BANCO = "Partidas en banco pendientes de registración contable."

# Anchos (caracteres) por columna. Los de importe (D/E/F) son anchos a
# proposito: con el separador de miles y dos decimales, un importe como
# 99.999.999.999,99 ocupa ~17 caracteres; con 14 Excel lo tapa con "#######".
ANCHOS_MAYOR = {
    "A": 12.0,
    "B": 18.0,
    "C": 14.0,
    "D": 18.0,
    "E": 18.0,
    "F": 20.0,
    "G": 40.0,
    "H": 22.0,
    "I": 18.0,
}
ANCHOS_MOVIMIENTOS = {
    "A": 14.0,
    "B": 14.0,
    "C": 34.0,
    "D": 18.0,
    "E": 18.0,
    "F": 20.0,
    "G": 24.0,
    "H": 12.0,
    "I": 16.0,
    "J": 12.0,
    "K": 12.0,
    "L": 22.0,
    "M": 12.0,
    "N": 20.0,
    "O": 24.0,
    "P": 10.0,
    "Q": 16.0,
}

# ----------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------

# El alpha va FF (opaco): el mismo azul de las etiquetas "Empresa:" de la
# plantilla. Con alpha 00 Excel pinta el relleno como transparente.
RELLENO_ENCABEZADO = PatternFill("solid", fgColor="FF00B0F0")
FUENTE_ENCABEZADO = Font(name="Calibri", size=11, bold=True)
FUENTE_TITULO_SECCION = Font(name="Calibri", size=11, bold=True)
# shrink_to_fit: red de seguridad. Si un importe supera el ancho de la
# columna, Excel lo achica en vez de taparlo con "#######".
ALINEACION_DERECHA = Alignment(horizontal="right", shrink_to_fit=True)
ALINEACION_CENTRO = Alignment(horizontal="center")
ALINEACION_IZQUIERDA = Alignment(horizontal="left")
BORDE_ENCABEZADO = Border(bottom=Side(style="thin"))


def ruta_plantilla() -> Path:
    return DIRECTORIO_PLANTILLAS / NOMBRE_PLANTILLA


# ----------------------------------------------------------------------
# Normalizacion de valores
# ----------------------------------------------------------------------


def _importe(valor: object) -> float:
    """Un importe a float, con 0 para lo que venga sucio o ausente."""
    try:
        numero = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if numero != numero or numero in (float("inf"), float("-inf")):
        return 0.0
    return round(numero, 2)


def _fecha(valor: object) -> date | None:
    """Acepta date, datetime y los dos formatos de texto que manda el cruce."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and valor.strip():
        for formato in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(valor.strip(), formato).date()
            except ValueError:
                continue
    return None


def _periodo_a_fecha(periodo: str | None) -> date | None:
    """'2026-09' -> un date, para la celda del periodo."""
    if not periodo:
        return None
    texto = periodo.strip()
    for formato in ("%Y-%m", "%Y/%m", "%m/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _saldo_final_banco(solicitud: SolicitudExportacion) -> float:
    if solicitud.saldo_final_banco is not None:
        return _importe(solicitud.saldo_final_banco)
    if solicitud.movimientos_banco:
        return _importe(solicitud.movimientos_banco[-1].saldo)
    return 0.0


# ----------------------------------------------------------------------
# Escritura de celdas
# ----------------------------------------------------------------------


def _formatear(celda, valor: object) -> None:
    """Fecha -> centrada; numero -> derecha con dos decimales; resto -> izquierda."""
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, date):
        celda.number_format = FORMATO_FECHA
        celda.alignment = ALINEACION_CENTRO
    elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
        celda.number_format = FORMATO_IMPORTE
        celda.alignment = ALINEACION_DERECHA
    else:
        celda.alignment = ALINEACION_IZQUIERDA


def _escribir_fila(hoja: Worksheet, fila: int, valores: list, centradas=()) -> None:
    for indice, valor in enumerate(valores):
        celda = hoja.cell(row=fila, column=indice + 1)
        celda.value = valor
        _formatear(celda, valor)
        if indice in centradas:
            celda.alignment = ALINEACION_CENTRO


def _celda_importe(hoja: Worksheet, fila: int, columna: int, valor: float) -> None:
    celda = hoja.cell(row=fila, column=columna, value=_importe(valor))
    celda.number_format = FORMATO_IMPORTE
    celda.alignment = ALINEACION_DERECHA


def _celda_formula(hoja: Worksheet, fila: int, columna: int, formula: str) -> None:
    celda = hoja.cell(row=fila, column=columna, value=formula)
    celda.number_format = FORMATO_IMPORTE
    celda.alignment = ALINEACION_DERECHA


def _escribir_encabezados(hoja: Worksheet, fila: int, columnas: list[str]) -> None:
    for indice, nombre in enumerate(columnas):
        celda = hoja.cell(row=fila, column=indice + 1, value=nombre)
        celda.font = FUENTE_ENCABEZADO
        celda.fill = RELLENO_ENCABEZADO
        celda.alignment = ALINEACION_CENTRO
        celda.border = BORDE_ENCABEZADO


def _titulo_seccion(hoja: Worksheet, fila: int, texto: str) -> None:
    hoja.cell(row=fila, column=1, value=texto).font = FUENTE_TITULO_SECCION


def _anchos(hoja: Worksheet, anchos: dict[str, float]) -> None:
    for columna, ancho in anchos.items():
        hoja.column_dimensions[columna].width = ancho


# ----------------------------------------------------------------------
# Membrete
# ----------------------------------------------------------------------


def _escribir_membrete(hoja: Worksheet, encabezado: EncabezadoConciliacion) -> None:
    """Los cuatro campos del membrete de la hoja Libro Mayor.

    La hoja de movimientos los toma por formula contra esta: hay que escribir
    valores aca y formulas alla.
    """
    hoja["B5"] = encabezado.empresa
    hoja["B6"] = encabezado.banco
    hoja["I6"] = encabezado.numero_cuenta

    periodo = _periodo_a_fecha(encabezado.periodo)
    if periodo is not None:
        hoja["I5"] = periodo
        hoja["I5"].number_format = FORMATO_FECHA
        hoja["I5"].alignment = ALINEACION_CENTRO
    elif encabezado.periodo:
        hoja["I5"] = encabezado.periodo


def _restaurar_formulas_del_membrete(hoja: Worksheet) -> None:
    """Deja los links de la hoja de movimientos apuntando al Libro Mayor."""
    hoja["B5"] = "=+'Libro Mayor'!B5"
    hoja["B6"] = "=+'Libro Mayor'!B6"
    hoja["I5"] = "=+'Libro Mayor'!I5"
    hoja["I6"] = "=+'Libro Mayor'!I6"
    # La plantilla traia 'mmm-yy' en esta celda; el membrete de las dos hojas
    # tiene que verse igual.
    hoja["I5"].number_format = FORMATO_FECHA
    hoja["I5"].alignment = ALINEACION_CENTRO


# ----------------------------------------------------------------------
# Tablas de la hoja Libro Mayor
# ----------------------------------------------------------------------


def _armar_tabla_mayor(
    hoja: Worksheet, solicitud: SolicitudExportacion
) -> tuple[int, str]:
    """Tabla 1 completa. Devuelve (fila libre, celda del ultimo saldo)."""
    _escribir_encabezados(hoja, FILA_ENCABEZADO_TABLA1, COLUMNAS_TABLA1)

    fila = FILA_ENCABEZADO_TABLA1 + 1
    # La fila de Saldo Inicial siempre va, aunque no haya movimientos: es el
    # punto de partida de la columna F.
    hoja.cell(row=fila, column=7, value="Saldo Inicial").font = FUENTE_TITULO_SECCION
    _celda_importe(hoja, fila, 6, solicitud.saldo_inicial_mayor)
    celda_ultimo_saldo = f"F{fila}"
    fila += 1

    for movimiento in solicitud.movimientos_mayor:
        _escribir_fila(
            hoja,
            fila,
            [
                _fecha(movimiento.fecha),
                movimiento.comprobante or "",
                "",
                _importe(movimiento.debe),
                _importe(movimiento.haber),
                None,
                movimiento.concepto or "",
                "",
                "",
            ],
            centradas={1, 2},
        )
        _celda_formula(hoja, fila, 6, f"=F{fila - 1}+D{fila}-E{fila}")
        celda_ultimo_saldo = f"F{fila}"
        fila += 1

    return fila, celda_ultimo_saldo


def _armar_tabla_pendientes_contables(
    hoja: Worksheet, fila_inicio: int, pendientes: list[PendienteExport]
) -> int:
    """Tabla 2: partidas del mayor que no sono en el extracto."""
    fila = fila_inicio + 1
    _titulo_seccion(hoja, fila, TITULO_PARTIDAS_CONTABLES)
    fila += 1
    _escribir_encabezados(hoja, fila, COLUMNAS_TABLA2)
    fila += 1

    primer_dato = fila
    for pendiente in pendientes:
        _escribir_fila(
            hoja,
            fila,
            [
                _fecha(pendiente.fecha),
                pendiente.comprobante or pendiente.referencia or "",
                "",
                _importe(pendiente.debe),
                _importe(pendiente.haber),
                None,
                pendiente.concepto or "",
                "",
            ],
            centradas={1, 2},
        )
        formula = f"=D{fila}-E{fila}" if fila == primer_dato else f"=F{fila - 1}+D{fila}-E{fila}"
        _celda_formula(hoja, fila, 6, formula)
        fila += 1

    return fila


def _armar_tabla_pendientes_banco(
    hoja: Worksheet, fila_inicio: int, pendientes: list[PendienteExport]
) -> int:
    """Tabla 3: movimientos del extracto que no estan contabilizados."""
    fila = fila_inicio + 1
    _titulo_seccion(hoja, fila, TITULO_PARTIDAS_BANCO)
    fila += 1
    _escribir_encabezados(hoja, fila, COLUMNAS_TABLA3)
    fila += 1

    primer_dato = fila
    for pendiente in pendientes:
        _escribir_fila(
            hoja,
            fila,
            [
                _fecha(pendiente.fecha),
                pendiente.referencia or "",
                "",
                _importe(pendiente.debe),
                _importe(pendiente.haber),
                None,
                pendiente.concepto or "",
            ],
            centradas={1, 2},
        )
        formula = f"=D{fila}-E{fila}" if fila == primer_dato else f"=F{fila - 1}+D{fila}-E{fila}"
        _celda_formula(hoja, fila, 6, formula)
        fila += 1

    return fila


def _armar_pie_de_control(
    hoja: Worksheet,
    fila_inicio: int,
    solicitud: SolicitudExportacion,
    celda_saldo_mayor: str,
) -> None:
    """Saldo final del mayor, saldo final del banco y el control de cierre.

    La formula del control es `=F(penultima)-F(anteultima)`, tal como la pide
    el formulario: diferencia entre el saldo que informa el banco y el saldo
    contable. Cero es el cierre.
    """
    fila = fila_inicio + 1
    _titulo_seccion(hoja, fila, "Saldo final según Mayor")
    _celda_formula(hoja, fila, 6, f"={celda_saldo_mayor}")
    fila_saldo_mayor = fila
    fila += 1

    _titulo_seccion(hoja, fila, "Saldo final según Banco")
    _celda_importe(hoja, fila, 6, _saldo_final_banco(solicitud))
    fila_saldo_banco = fila
    fila += 1

    _titulo_seccion(hoja, fila, "Control de diferencia")
    _celda_formula(hoja, fila, 6, f"=F{fila_saldo_banco}-F{fila_saldo_mayor}")


# ----------------------------------------------------------------------
# Hoja Movimientos Bancarios
# ----------------------------------------------------------------------


def _armar_movimientos(
    hoja: Worksheet, solicitud: SolicitudExportacion, celda_saldo_mayor: str
) -> None:
    _escribir_encabezados(hoja, FILA_ENCABEZADO_MOVIMIENTOS, COLUMNAS_MOVIMIENTOS)

    fila = FILA_ENCABEZADO_MOVIMIENTOS + 1
    primer_dato = fila
    for movimiento in solicitud.movimientos_banco:
        _escribir_fila(
            hoja,
            fila,
            [
                _fecha(movimiento.fecha),
                "",
                movimiento.concepto or "",
                _importe(movimiento.debe),
                _importe(movimiento.haber),
                None,
                "",
                "",
                "",
                "",
                solicitud.encabezado.banco,
                "",
                "",
                movimiento.referencia or "",
                "",
                "",
                "",
            ],
            # Los codigos van centrados (col. B, H, J, K, M, P, Q) aunque hoy
            # salgan vacios: el spec pide centrar fechas y codigos.
            centradas={1, 7, 9, 10, 12, 15, 16},
        )
        # El banco acumula credito - debito; la primera fila arranca en cero.
        if fila == primer_dato:
            formula = f"=E{fila}-D{fila}"
        else:
            formula = f"=F{fila - 1}+E{fila}-D{fila}"
        _celda_formula(hoja, fila, 6, formula)
        fila += 1

    if fila > primer_dato:
        _titulo_seccion(hoja, fila, "Control de diferencia")
        _celda_formula(hoja, fila, 6, f"=F{fila - 1}-'Libro Mayor'!{celda_saldo_mayor}")


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

        _anchos(mayor, ANCHOS_MAYOR)
        _anchos(movimientos, ANCHOS_MOVIMIENTOS)
        _escribir_membrete(mayor, solicitud.encabezado)

        fila, celda_saldo_mayor = _armar_tabla_mayor(mayor, solicitud)
        fila = _armar_tabla_pendientes_contables(mayor, fila, solicitud.pendientes_xubio)
        fila = _armar_tabla_pendientes_banco(mayor, fila, solicitud.pendientes_banco)
        _armar_pie_de_control(mayor, fila, solicitud, celda_saldo_mayor)

        _armar_movimientos(movimientos, solicitud, celda_saldo_mayor)
        _restaurar_formulas_del_membrete(movimientos)

        destino = io.BytesIO()
        libro.save(destino)
        return destino.getvalue()
    finally:
        libro.close()


def nombre_archivo(solicitud: SolicitudExportacion, hoy: date | None = None) -> str:
    """Un nombre de archivo que se entienda y no tenga caracteres raros.

    El período va antes de la fecha de emisión: entre cinco conciliaciones del
    mismo día, la que dice "2026-07" es la que se reconoce; la que dice la
    fecha en que se bajó el archivo es indistinguible. La fecha de hoy solo
    aparece si no se pasó período.
    """
    dia = hoy or date.today()
    partes = [p for p in (solicitud.encabezado.empresa, solicitud.encabezado.banco) if p.strip()]
    detalle = " ".join(partes).strip() or "Conciliación Bancaria"
    limpio = "".join(
        caracter if caracter.isalnum() or caracter in " -_.&" else "" for caracter in detalle
    ).strip()
    limpio = " ".join(limpio.split())

    periodo = solicitud.encabezado.periodo
    cierre = ""
    if periodo and periodo.strip():
        # El período es texto libre ("2026-07", "julio 26"), asi que pasa por
        # la misma limpieza que el nombre: un "/" o un "\0" en un header
        # romperia la descarga.
        cierre = "".join(
            caracter if caracter.isalnum() or caracter in " -_." else ""
            for caracter in periodo.strip()
        ).strip()
    if not cierre:
        cierre = dia.strftime("%d-%m-%Y")

    return f"FO 02-03 {limpio} {cierre}.xlsx"
