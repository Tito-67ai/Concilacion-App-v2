"""Arma el papel de trabajo FO 02-03 a partir del estado de la conciliacion.

La plantilla vive como asset en app/assets/plantillas y se carga con openpyxl en
vez de recrear el formato en codigo: el membrete (formulario, revision,
vigencia), los merges, los anchos de columna y el formato de numero de la
auditoria son cosas que no hay que mantener sincronizadas a mano.

Los dos titulos de seccion que ya trae la plantilla se respetan tal cual:

    A10  Partidas contables no registradas en banco.
    A18  Partidas en banco pendientes de registracion contable.

La hoja "Movimientos Bancarios" tiene tres bloques lado a lado, que es lo que
indican los merges del membrete (C2:H2, AF2:AL2 y BJ2:BP2, con el codigo de
formulario 30 columnas mas alla en cada bloque).
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.models.schemas import (
    EncabezadoConciliacion,
    ParConciliado,
    PendienteExport,
    SolicitudExportacion,
)

DIRECTORIO_PLANTILLAS = Path(__file__).resolve().parent.parent / "assets" / "plantillas"
NOMBRE_PLANTILLA = "FO 02-03 Conciliación Bancaria.xlsx"

HOJA_MAYOR = "Libro Mayor"
HOJA_MOVIMIENTOS = "Movimientos Bancarios"

# Formato de numero heredado de la plantilla: separador de miles, punto para los
# decimales y guion para el cero. Es el que Excel ya trae definido en las celdas
# contables del formulario.
FORMATO_IMPORTE = '_ * #,##0.00_ ;_ * \\-#,##0.00_ ;_ * "-"??_ ;_ @_ '
FORMATO_FECHA = "dd/mm/yyyy"

# ----------------------------------------------------------------------
# Layout de la hoja "Libro Mayor"
# ----------------------------------------------------------------------

# Titulo de la seccion -> (fila del titulo, fila del encabezado, fila del primer
# dato). Los titulos ya estan en la plantilla (A10 y A18); el encabezado se
# escribe una fila abajo de cada uno.
SECCIONES_MAYOR = [
    ("Partidas contables no registradas en banco.", 10, 11, 12),
    ("Partidas en banco pendientes de registración contable.", 18, 19, 20),
]

COLUMNAS_MAYOR = ["Fecha", "Concepto", "Debe", "Haber", "Importe"]

# Anchos (caracteres) para las columnas que usa la hoja Libro Mayor.
ANCHOS_MAYOR = {"A": 15.7, "B": 20.9, "C": 14.0, "D": 14.0, "E": 14.0}

# ----------------------------------------------------------------------
# Layout de la hoja "Movimientos Bancarios"
# ----------------------------------------------------------------------

# Columna en la que arranca cada bloque. Los 30 de separacion salen del
# membrete de la plantilla: el codigo "FO 02-03" esta en I1, AM1 y BQ1.
BLOQUES_MOVIMIENTOS = [
    (1, "Movimientos Bancarios"),
    (31, "Libro Mayor"),
    (61, "Conciliación"),
]

COLUMNAS_MOVIMIENTOS = [
    "Fecha",
    "Concepto",
    "Debe",
    "Haber",
    "Importe",
    "Saldo",
    "Categoría",
    "Origen",
]

# Ancho por posicion dentro de un bloque (0 = Fecha, 1 = Concepto, ...).
ANCHOS_POR_POSICION = [12.0, 34.0, 13.0, 13.0, 13.0, 13.0, 12.0, 12.0]

FILA_TITULO_MOVIMIENTOS = 7
FILA_ENCABEZADO_MOVIMIENTOS = 8
FILA_PRIMER_DATO_MOVIMIENTOS = 9

# ----------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------

# El alpha va FF (opaco) a proposito: el mismo azul de la etiqueta "Empresa:"
# de la plantilla. Con alpha 00 Excel pinta el relleno como transparente.
RELLENO_ENCABEZADO = PatternFill("solid", fgColor="FF00B0F0")
FUENTE_ENCABEZADO = Font(name="Calibri", size=11, bold=True)
FUENTE_TITULO_BLOQUE = Font(name="Calibri", size=11, bold=True)
FUENTE_TOTAL = Font(name="Calibri", size=11, bold=True)
ALINEACION_DERECHA = Alignment(horizontal="right")
ALINEACION_CENTRO = Alignment(horizontal="center")

BORDE_TOTAL = Border(top=Side(style="thin"), bottom=Side(style="double"))


def ruta_plantilla() -> Path:
    return DIRECTORIO_PLANTILLAS / NOMBRE_PLANTILLA


def _columna(base: int, desplazamiento: int) -> str:
    return get_column_letter(base + desplazamiento)


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
    """'2026-09' o 'septiembre 2026' -> un date, para la celda con formato mes."""
    if not periodo:
        return None
    texto = periodo.strip()
    for formato in ("%Y-%m", "%Y/%m", "%m/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    # Sin formato reconocible se escribe el texto tal cual: la celda va a
    # mostrarlo, pero no se pisa el dato que mando el usuario.
    return None


MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

ETIQUETA_ORIGEN = {
    "banco": "Banco",
    "xubio": "Libro Mayor",
}


def _etiqueta_categoria(categoria: str | None) -> str:
    if categoria == "percepcion":
        return "Percepción"
    if categoria == "impuesto":
        return "Impuesto"
    if categoria == "operativo":
        return "Operativo"
    return categoria or ""


def _escribir_encabezado(hoja: Worksheet, encabezado: EncabezadoConciliacion) -> None:
    """Los cuatro campos del membrete.

    Solo en la hoja Libro Mayor: la de Movimientos Bancarios los trae por
    formula (=+'Libro Mayor'!B5 y companhia) y hay que respetar esas formulas en
    vez de pisarlas con un valor.
    """
    hoja["B5"] = encabezado.empresa
    hoja["B6"] = encabezado.banco
    hoja["I6"] = encabezado.numero_cuenta

    periodo = _periodo_a_fecha(encabezado.periodo)
    if periodo is not None:
        hoja["I5"] = periodo
    elif encabezado.periodo:
        hoja["I5"] = encabezado.periodo


def _estilo_encabezado(celda) -> None:
    celda.font = FUENTE_ENCABEZADO
    celda.fill = RELLENO_ENCABEZADO
    celda.alignment = ALINEACION_CENTRO


def _escribir_fila(
    hoja: Worksheet,
    fila: int,
    columna_base: int,
    valores: list,
) -> None:
    for desplazamiento, valor in enumerate(valores):
        # No se puede pasar value= al cell(): openpyxl no sabe convertir una
        # lista. Se escribe la celda vacia y despues el valor.
        celda = hoja.cell(row=fila, column=columna_base + desplazamiento)
        celda.value = valor
        if isinstance(valor, date):
            celda.number_format = FORMATO_FECHA
            celda.alignment = ALINEACION_CENTRO
        elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
            celda.number_format = FORMATO_IMPORTE
            celda.alignment = ALINEACION_DERECHA


def _escribir_fila_de_totales(hoja: Worksheet, fila: int, columna_base: int, celdas: int) -> None:
    for desplazamiento in range(celdas):
        celda = hoja.cell(row=fila, column=columna_base + desplazamiento)
        celda.font = FUENTE_TOTAL
        celda.border = BORDE_TOTAL


def _importe_de_lado(haber: float, debe: float, lado: str) -> float:
    """El importe con signo unificado de cada lado.

    Banco:  un DEBE es una salida, asi que el signo va (haber - debe).
    Mayor:  un DEBE es una entrada, asi que el signo va (debe - haber).
    """
    if lado == "xubio":
        return round(_importe(debe) - _importe(haber), 2)
    return round(_importe(haber) - _importe(debe), 2)


def _importe_de_pendiente(pendiente: PendienteExport, lado: str) -> float:
    if pendiente.importe is not None:
        return _importe(pendiente.importe)
    return _importe_de_lado(_importe(pendiente.haber), _importe(pendiente.debe), lado)


def _importe_de_par(par: ParConciliado) -> float:
    """El importe con signo del par, o el del banco si no vino."""
    if par.importe is None:
        return _importe(par.haber) - _importe(par.debe)
    return _importe(par.importe)


def _armar_mayor(hoja: Worksheet, solicitud: SolicitudExportacion) -> None:
    """Las dos secciones del libro mayor: los pendientes, de cada lado."""
    for columna, ancho in ANCHOS_MAYOR.items():
        hoja.column_dimensions[columna].width = ancho

    # El signo del importe depende del lado, y no es una cuestion de gusto: en el
    # banco un DEBE es una salida (conciliador.py:19-26) y en el mayor de Xubio
    # un DEBE es una entrada (conciliador.py:31). Si las dos secciones usaran la
    # convencion del banco, las partidas del mayor saldrian al reves y el papel
    # de trabajoaria contradecir a la pantalla.
    secciones = [
        (SECCIONES_MAYOR[0], solicitud.pendientes_xubio, "xubio"),
        (SECCIONES_MAYOR[1], solicitud.pendientes_banco, "banco"),
    ]

    for (
        (titulo_esperado, fila_titulo, fila_encabezado, fila_dato),
        pendientes,
        lado,
    ) in secciones:
        # El titulo ya viene de la plantilla y es el texto que la auditoria
        # reconosce. Solo se escribe si el archivo no lo tiene: si alguien
        # edito la plantilla a mano, el papel sale con su texto, no con el
        # nuestro pisando encima.
        celda_titulo = hoja.cell(row=fila_titulo, column=1)
        if not celda_titulo.value:
            celda_titulo.value = titulo_esperado
        celda_titulo.font = FUENTE_TITULO_BLOQUE

        for desplazamiento, titulo in enumerate(COLUMNAS_MAYOR):
            celda = hoja.cell(row=fila_encabezado, column=1 + desplazamiento, value=titulo)
            _estilo_encabezado(celda)

        fila = fila_dato
        for pendiente in pendientes:
            _escribir_fila(
                hoja,
                fila,
                1,
                [
                    _fecha(pendiente.fecha),
                    pendiente.concepto,
                    _importe(pendiente.debe),
                    _importe(pendiente.haber),
                    _importe_de_pendiente(pendiente, lado),
                ],
            )
            fila += 1

        if fila > fila_dato:
            total_debe = sum(_importe(p.debe) for p in pendientes)
            total_haber = sum(_importe(p.haber) for p in pendientes)
            hoja.cell(row=fila, column=2, value="Total").alignment = ALINEACION_DERECHA
            hoja.cell(row=fila, column=3, value=total_debe)
            hoja.cell(row=fila, column=4, value=total_haber)
            hoja.cell(row=fila, column=5, value=_importe_de_lado(total_haber, total_debe, lado))
            _escribir_fila_de_totales(hoja, fila, 1, len(COLUMNAS_MAYOR))
            for desplazamiento in (2, 3, 4):
                hoja.cell(row=fila, column=1 + desplazamiento).number_format = FORMATO_IMPORTE
                hoja.cell(row=fila, column=1 + desplazamiento).alignment = ALINEACION_DERECHA


def _armar_bloque(
    hoja: Worksheet,
    columna_base: int,
    titulo: str,
    filas: list[list],
) -> None:
    for posicion, ancho in enumerate(ANCHOS_POR_POSICION):
        hoja.column_dimensions[_columna(columna_base, posicion)].width = ancho

    celda_titulo = hoja.cell(row=FILA_TITULO_MOVIMIENTOS, column=columna_base, value=titulo)
    celda_titulo.font = FUENTE_TITULO_BLOQUE

    for desplazamiento, nombre in enumerate(COLUMNAS_MOVIMIENTOS):
        celda = hoja.cell(
            row=FILA_ENCABEZADO_MOVIMIENTOS, column=columna_base + desplazamiento, value=nombre
        )
        _estilo_encabezado(celda)

    fila = FILA_PRIMER_DATO_MOVIMIENTOS
    for valores in filas:
        _escribir_fila(hoja, fila, columna_base, valores)
        fila += 1

    if fila > FILA_PRIMER_DATO_MOVIMIENTOS:
        total_debe = sum(_importe(v[2]) for v in filas)
        total_haber = sum(_importe(v[3]) for v in filas)
        hoja.cell(row=fila, column=columna_base + 1, value="Total").alignment = ALINEACION_DERECHA
        # El Importe se totaliza igual que Debe y Haber para que el bloque
        # cuadre contra el Libro Mayor, que si lo suma. El Saldo no se suma:
        # es un saldo acumulado, no una magnitud aditiva.
        for desplazamiento, valor in (
            (2, total_debe),
            (3, total_haber),
            (4, sum(_importe(v[4]) for v in filas)),
        ):
            hoja.cell(row=fila, column=columna_base + desplazamiento, value=valor)
        _escribir_fila_de_totales(
            hoja, fila, columna_base, len(COLUMNAS_MOVIMIENTOS)
        )
        for desplazamiento in (2, 3, 4, 5):
            hoja.cell(row=fila, column=columna_base + desplazamiento).number_format = FORMATO_IMPORTE
            hoja.cell(row=fila, column=columna_base + desplazamiento).alignment = ALINEACION_DERECHA


def _filas_de_banco(pendientes: list[PendienteExport]) -> list[list]:
    filas = []
    for pendiente in pendientes:
        filas.append(
            [
                _fecha(pendiente.fecha),
                pendiente.concepto,
                _importe(pendiente.debe),
                _importe(pendiente.haber),
                _importe_de_pendiente(pendiente, "banco"),
                _importe(pendiente.saldo),
                _etiqueta_categoria(pendiente.categoria),
                "Banco",
            ]
        )
    return filas


def _filas_de_mayor(pendientes: list[PendienteExport]) -> list[list]:
    filas = []
    for pendiente in pendientes:
        filas.append(
            [
                _fecha(pendiente.fecha),
                pendiente.concepto,
                _importe(pendiente.debe),
                _importe(pendiente.haber),
                _importe_de_pendiente(pendiente, "xubio"),
                "",
                "",
                "Libro Mayor",
            ]
        )
    return filas


def _filas_de_conciliados(pares: list[ParConciliado]) -> list[list]:
    filas = []
    for par in pares:
        if par.manual:
            origen = "A mano"
            if par.diferencia is not None and _importe(par.diferencia) != 0:
                origen = f"A mano (dif. {par.diferencia:.2f})"
        else:
            origen = "Automático"
        filas.append(
            [
                _fecha(par.fecha),
                f"{par.concepto_banco} / {par.concepto_xubio}",
                _importe(par.debe),
                _importe(par.haber),
                _importe_de_par(par),
                _importe(par.saldo),
                _etiqueta_categoria(par.categoria),
                origen,
            ]
        )
    return filas


def _armar_movimientos(hoja: Worksheet, solicitud: SolicitudExportacion) -> None:
    # Un constructor de filas por bloque, en el mismo orden que
    # BLOQUES_MOVIMIENTOS: banco, libro mayor y conciliados.
    filas_por_bloque = [
        _filas_de_banco(solicitud.pendientes_banco),
        _filas_de_mayor(solicitud.pendientes_xubio),
        _filas_de_conciliados(solicitud.conciliados),
    ]

    for (columna_base, titulo), filas in zip(BLOQUES_MOVIMIENTOS, filas_por_bloque):
        _armar_bloque(hoja, columna_base, titulo, filas)


def exportar(solicitud: SolicitudExportacion) -> bytes:
    """Devuelve el .xlsx del papel de trabajo, listo para mandarse como archivo."""
    ruta = ruta_plantilla()
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontro la plantilla FO 02-03 en {ruta}")

    libro = load_workbook(ruta)
    try:
        mayor = libro[HOJA_MAYOR]
        movimientos = libro[HOJA_MOVIMIENTOS]

        _escribir_encabezado(mayor, solicitud.encabezado)
        _armar_mayor(mayor, solicitud)
        _armar_movimientos(movimientos, solicitud)

        # La hoja de movimientos toma el membrete por formula contra Libro
        # Mayor. Si en una sesion anterior quedo con un valor pegado, la
        # formula se perdio y esta hoja dejaria de seguir al membrete.
        _restaurar_formulas_del_membrete(movimientos)

        destino = io.BytesIO()
        libro.save(destino)
        return destino.getvalue()
    finally:
        libro.close()


def _restaurar_formulas_del_membrete(hoja: Worksheet) -> None:
    """Deja los links de la hoja de movimientos apuntando al Libro Mayor."""
    hoja["B5"] = "=+'Libro Mayor'!B5"
    hoja["B6"] = "=+'Libro Mayor'!B6"
    hoja["I5"] = "=+'Libro Mayor'!I5"
    hoja["I6"] = "=+'Libro Mayor'!I6"


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