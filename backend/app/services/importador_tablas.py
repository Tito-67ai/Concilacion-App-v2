"""
Importacion de extractos que llegan como tabla (xlsx/csv) en vez de PDF.

Los extractores de PDF escriben un Excel con las columnas FECHA, DETALLE, DEBE,
HABER, SALDO. Cuando el usuario trae el Excel del banco门户, los encabezados
son otros: "Fecha operacion", "Descripcion", "Debito", "Credito", "Nro. comprobante".
Por eso este modulo traduzca los encabezados a los nombres canonicos y despues
reusa _df_to_movimientos, que ya sabe calcular el saldo, descartar la fila de
saldo inicial y avisar cuando un importe quedo en cero.
"""

import csv
import io
import logging
import os
import unicodedata

import pandas as pd

from app.models.schemas import MovimientoBancario
from app.services.procesador_central import ErrorDeExtraccion, _df_to_movimientos, _borrar

logger = logging.getLogger(__name__)

EXTENSIONES = {".xlsx", ".xls", ".csv"}

# De cada columna canonica, los encabezados que usan los bancos. Se comparan ya
# normalizados (mayusculas, sin acentos ni signos), asi que aca van sin tildes.
ALIAS_COLUMNAS = {
    "FECHA": {
        "FECHA",
        "FECHADEFONDOOPERACION",
        "FECHADEOPERACION",
        "FECHAOPERACION",
        "FECHAMOVIMIENTO",
        "FECHACONTABLE",
        "FECHAVALOR",
        "FECHAEFECTIVA",
        "DATE",
        "FECHACONTRATO",
    },
    "DETALLE": {
        "DETALLE",
        "DETALLEDELAOPERACION",
        "DETALLEOPERACION",
        "CONCEPTO",
        "DESCRIPCION",
        "GLOSA",
        "OBSERVACION",
        "MEMO",
        "DESCRIPCIONDELMOVIMIENTO",
        "CONCEPTOMOVIMIENTO",
    },
    "DEBE": {
        "DEBE",
        "DEBITO",
        "DEBITOS",
        "EGRESO",
        "EGRESOS",
        "SALDODEUDOR",
        "IMPORTEDEBITO",
        "DEBITOMONEDA",
        "WITHDRAWALS",
        "DEBITS",
    },
    "HABER": {
        "HABER",
        "CREDITO",
        "CREDITOS",
        "INGRESO",
        "INGRESOS",
        "SALDOACREEDOR",
        "IMPORTECREDITO",
        "CREDITOMONEDA",
        "DEPOSITS",
        "CREDITS",
    },
    # Algunos bancos (MP) traen una sola columna con el signo ya puesto.
    "IMPORTE": {
        "IMPORTE",
        "MONTO",
        "VALOR",
        "VALORMONEDA",
        "IMPORTEOPERACION",
        "AMOUNT",
    },
    "SALDO": {
        "SALDO",
        "SALDOACTUAL",
        "SALDOCONTABLE",
        "SALDOFINAL",
        "SALDOACUMULADO",
        "BALANCE",
    },
    "REFERENCIA": {
        "REFERENCIA",
        "REF",
        "IDOPERACION",
        "NROOPERACION",
        "NUMEROOPERACION",
        "NROCOMPROBANTE",
        "NUMEROCOMPROBANTE",
        "COMPROBANTE",
        "REFERENCIABANCARIA",
    },
    "CUENTA": {
        "CUENTA",
        "CTA",
        "NUMERODECUENTA",
        "NROCUENTA",
    },
}

# Cuantas filas se miran para encontrar el encabezado cuando el Excel viene con
# un titulo arriba ("Extracto BBVA - Cuenta 123") antes de los nombres de columna.
FILAS_PARA_BUSCAR_ENCABEZADO = 15


def _normalizar(texto) -> str:
    """'Fecha de Operación' -> 'FECHADEOPERACION'."""
    sin_acentos = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in sin_acentos.upper() if c.isalnum())


def _columna_canonica(nombre) -> str | None:
    """
    Traduce un encabezado a FECHA/DETALLE/..., o None si no se reconoce.

    Primero busca coincidencia exacta; si no hay, containment con el alias mas
    largo. Asi "FECHA DE OPERACION BCO" y "SALDO INICIAL" caen igual, sin que
    "DEBE" se coma un "DETALLE DE DEBITO".
    """
    n = _normalizar(nombre)
    if not n:
        return None

    for canonica, alias in ALIAS_COLUMNAS.items():
        if n in alias:
            return canonica

    mejor = None
    for canonica, alias in ALIAS_COLUMNAS.items():
        for nombre_alias in alias:
            if len(nombre_alias) >= 6 and nombre_alias in n:
                if mejor is None or len(nombre_alias) > mejor[1]:
                    mejor = (canonica, len(nombre_alias))
    return mejor[0] if mejor else None


def normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renombra los encabezados reconocidos a los nombres canonicos.

    Las columnas que no se reconocen se conservan: si el Excel trae CUENTA o una
    columna de comentarios, no se tira nada. Solo se pisan los nombres que si
    tenemos claros.

    Si dos columnas caerian en la misma canonica ("Fecha operacion" y "Fecha"), se
    renombra solo la primera. Renombrar las dos deja dos columnas FECHA y
    _df_to_movimientos lee siempre la primera, en silencio.
    """
    renombres = {}
    ya_tomadas = set()
    for nombre in df.columns:
        canonica = _columna_canonica(nombre)
        if canonica is None or canonica in ya_tomadas:
            continue
        ya_tomadas.add(canonica)
        if canonica not in df.columns:
            renombres[nombre] = canonica

    if renombres:
        logger.info("Columnas normalizadas: %s", renombres)
        df = df.rename(columns=renombres)
    return df


def _fila_del_encabezado(df_crudo: pd.DataFrame):
    """
    Numero de fila donde estan los nombres de columna, o None si la primera fila
    ya los tiene.

    Los Excel y CSV de los portales bancarios arrancan con titulos, logos y
    filtros antes de la tabla. Sin esto, pandas tomaba esa primera linea como
    encabezado y todas las columnas quedaban con nombre numerico.
    """
    if _columna_canonica(df_crudo.columns[0]) is not None:
        return None

    for indice in range(min(FILAS_PARA_BUSCAR_ENCABEZADO, len(df_crudo))):
        fila = df_crudo.iloc[indice]
        canonicas = {_columna_canonica(v) for v in fila}
        # FECHA y DETALLE son las dos que despues exige _df_to_movimientos.
        if {"FECHA", "DETALLE"} <= canonicas:
            return indice
    return None


def _encabezado_de_filas(filas):
    for indice in range(min(FILAS_PARA_BUSCAR_ENCABEZADO, len(filas))):
        canonicas = {_columna_canonica(v) for v in filas[indice]} - {None}
        if {"FECHA", "DETALLE"} <= canonicas:
            return indice
    return None


def _leer_csv(ruta: str) -> pd.DataFrame:
    """
    Los CSV argentinos vienen en cp1252/latin-1 y separados por ';', pero algunos
    bancos exportan utf-8 con ','.

    En vez de confiar en pandas para detectar el separador (que se vuelve loco
    cuando hay titulos arriba y numeros con coma decimal), leemos el archivo a
    mano con csv.Sniffer probando varias codificaciones.
    """
    ultimo_error = None
    for codificacion in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(ruta, "rb") as fh:
                datos = fh.read(65536)
            with open(ruta, "r", encoding=codificacion, errors="strict") as fh:
                texto = fh.read()
        except Exception as e:  # noqa: BLE001
            ultimo_error = e
            continue

        # Probar con separador fijo primero, porque sniffer puede equivocarse
        for separador in (";", ",", "\t", None):
            if separador is None:
                try:
                    dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=";, \t")
                    separador_elegido = dialecto.delimiter
                except Exception:  # noqa: BLE001
                    continue
            else:
                separador_elegido = separador
            try:
                lector = csv.reader(io.StringIO(texto), delimiter=separador_elegido)
                filas = list(lector)
            except Exception:  # noqa: BLE001
                continue

            if len(filas) < 2:
                continue
            columnas_maximas = max(len(f) for f in filas) if filas else 0
            if columnas_maximas < 2:
                continue

            fila_encabezado = _encabezado_de_filas(filas)
            if fila_encabezado is None:
                # No encuentra encabezado en la prueba: tal vez es el caso normal
                # donde la primera fila es el encabezado
                canonicas = {_columna_canonica(v) for v in filas[0]} - {None}
                if len(canonicas) < 2:
                    continue
                fila_encabezado = 0

            encabezados = filas[fila_encabezado]
            encabezados = ["" if h is None else str(h) for h in encabezados]
            datos_filas = filas[fila_encabezado + 1 :]
            df = pd.DataFrame(datos_filas)
            if df.empty:
                continue
            df.columns = encabezados[: len(df.columns)]
            logger.info(
                "CSV leido como %s separador %r: %d columnas, encabezado en la fila %d",
                codificacion,
                separador_elegido,
                len(df.columns),
                fila_encabezado + 1,
            )
            return df
    raise ErrorDeExtraccion(f"No se pudo leer el CSV. Ultimo error: {ultimo_error}")


def _leer_xlsx(ruta: str) -> pd.DataFrame:
    crudo = pd.read_excel(ruta, header=None, dtype=object)
    fila_encabezado = _fila_del_encabezado(crudo)

    if fila_encabezado is None:
        # header=0 es el caso normal: ademas sirve para que el error posterior
        # muestre los encabezados reales que tiene el archivo.
        return pd.read_excel(ruta, dtype=object)

    logger.info("Encabezado de la tabla en la fila %s", fila_encabezado + 1)
    # header=fila_encabezado ya descarta las filas de arriba del encabezado. No
    # hay que volver a cortarlas: read_excel devuelve los datos arrancando en 0.
    return pd.read_excel(ruta, header=fila_encabezado, dtype=object)


def leer_tabla(ruta: str) -> pd.DataFrame:
    extension = os.path.splitext(ruta)[1].lower()
    if extension not in EXTENSIONES:
        raise ErrorDeExtraccion(
            f"Formato de tabla no soportado: '{extension}'. Se aceptan "
            f"{', '.join(sorted(EXTENSIONES))}"
        )
    if not os.path.isfile(ruta):
        raise ErrorDeExtraccion(f"No se encuentra el archivo a procesar: {ruta}")

    # El .xls viejo tambien entra por la misma lectura: pandas usa xlrd por
    # debajo y la unica diferencia es el contenedor (OLE2 en vez de zip).
    lector = _leer_xlsx if extension in (".xlsx", ".xls") else _leer_csv
    df = lector(ruta)

    if df is None or df.empty:
        raise ErrorDeExtraccion("El archivo no tiene filas.")
    return df


def procesar_tabla(banco_id: str, ruta_tabla: str) -> list[MovimientoBancario]:
    """
    Lee un extracto en Excel/CSV y devuelve los movimientos.

    Reusa _df_to_movimientos, que ya resuelve el calculo de saldo y el descarte
    de la fila de saldo inicial. Si el archivo tiene solo un encabezado sin
    columnas reconocibles, sube ErrorDeExtraccion con los nombres que se leyeron:
    es el unico dato que le sirve al usuario para arreglar el archivo.
    """
    banco = (banco_id or "").upper().strip()
    try:
        try:
            df = leer_tabla(ruta_tabla)
            df = normalizar_columnas(df)

            columnas = [str(c) for c in df.columns]
            logger.info("%s: tabla con columnas %s", banco, columnas)
            return _df_to_movimientos(df, banco)
        except ErrorDeExtraccion:
            raise
        except Exception as e:
            # openpyxl tira sus propias excepciones cuando el archivo esta
            # corrupto o no es un libro de Excel. Sin esto el usuario veria un
            # 500 con un traceback en vez de un motivo que pueda corregir.
            logger.exception("%s: error leyendo la tabla", banco)
            raise ErrorDeExtraccion(
                f"{banco}: no se pudo leer el archivo de tabla. {e}"
            ) from e
    finally:
        # Los PDF los borra procesar_archivo; las tablas también son temporales.
        _borrar(ruta_tabla)