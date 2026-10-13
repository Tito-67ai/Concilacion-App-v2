"""
Lectura de la contraparte contable exportada desde Xubio a archivo.

El cruce automatico necesita los dos lados: el extracto del banco y el asiento
del sistema contable. La API de Xubio esta reservada a planes superiores al
contratado, asi que la via disponible es exportar la contraparte desde el
navegador y traerla como archivo. /xubio/cruzar-datos sigue existiendo para
cuando esa API se contrate; esta via es la que no depende de nadie.

La lectura es la misma que la de los extractos (titulos arriba del encabezado,
codificaciones raras, separador ';') con dos diferencias:

* el encabezado se acepta con FECHA y DETALLE, o con FECHA y DEBE/HABER: la
  contraparte no siempre trae la columna de detalle del asiento;
* los importes se entienden como los espera conciliador._importe_xubio, es
  decir DEBE = entrada y HABER = salida. Eso vale para un Libro Mayor contable,
  pero Xubio tambien exporta "Movimientos de CC" (debito = salida), y ahi los
  importes van dados vuelta. Confundirlos deja TODO el cruce con el signo
  equivocado y no empareja nada, sin error que lo delate. La convencion se
  deduce de los encabezados y se devuelve para que la pantalla la muestre.
"""

import logging
from typing import NamedTuple

import pandas as pd

from app.services.Tools import limpiar_numero
from app.services.importador_tablas import (
    _normalizar,
    leer_tabla,
    mapa_de_columnas,
    normalizar_columnas,
)
from app.services.procesador_central import (
    ErrorDeExtraccion,
    _columna,
    _es_saldo_inicial,
    _parse_fecha,
)

logger = logging.getLogger(__name__)

# Palabras de un extracto de cuenta corriente: ahi el DEBITO es plata que
# SALE (el banco te la debita). En un libro mayor contable la columna se
# llama "Debe" y es la ENTRADA.
_SALIDA_DE_CUENTA = ("DEBITO", "CARGO", "EGRESO", "RETIRO", "DEBIT")
_ENTRADA_DE_CUENTA = ("CREDITO", "ABONO", "INGRESO", "DEPOSITO", "CREDIT")


class LecturaMayor(NamedTuple):
    """Lo que salio de un archivo contable: las filas y como se interpretaron."""

    datos: list[dict]
    # 'contable' (Debe = entrada) o 'cuenta' (debito = salida).
    convencion: str


def _es_encabezado_de_mayor(canonicas: set) -> bool:
    """
    FECHA mas cualquier columna que traiga importe o detalle.

    Exigir DETALLE, como hace el extracto bancario, dejaria el archivo sin
    encabezado encontrado: pandas tomaria el titulo de arriba como nombres de
    columna y las fechas quedarian como datos sueltos en una columna 0.
    """
    if "FECHA" not in canonicas:
        return False
    return bool(canonicas & {"DETALLE", "DEBE", "HABER", "IMPORTE"})


def _convencion(mapa: dict[str, str]) -> str:
    """
    'contable' si el archivo es un Libro Mayor, 'cuenta' si es un extracto de
    cuenta corriente.

    En doble partida la cuenta bancaria es un activo: el DEBE la aumenta (entra
    plata) y el HABER la disminuye (sale). Un extracto de cuenta dice lo mismo
    al reves: ahi "debito" es el banco descontandote plata. La decision sale de
    los encabezados, no de las filas: los importes son iguales en los dos
    casos, lo que cambia es de que lado caen.

    Solo se invierte cuando las dos columnas hablan claro ("Debito ..." y
    "Credito ..."): si alguna es neutra ("Debe"/"Haber") se asume libro.
    """
    # mapa_de_columnas devuelve {original: canonica}; aca se pregunta al reves.
    original = {canonica: origen for origen, canonica in mapa.items()}
    original_debe = original.get("DEBE")
    original_haber = original.get("HABER")
    if not original_debe or not original_haber:
        return "contable"
    debe = _normalizar(original_debe)
    haber = _normalizar(original_haber)
    salida = any(token in debe for token in _SALIDA_DE_CUENTA)
    entrada = any(token in haber for token in _ENTRADA_DE_CUENTA)
    return "cuenta" if salida and entrada else "contable"


def _importes_mayor(fila) -> tuple[float, float]:
    """
    (debe, haber) en valores positivos, con la convencion del libro contable.

    Si el archivo trae una sola columna IMPORTE con el signo ya puesto, el
    positivo se traduce a DEBE (entrada) y el negativo a HABER (salida).
    """
    debe = abs(limpiar_numero(_columna(fila, "DEBE", "Debe")))
    haber = abs(limpiar_numero(_columna(fila, "HABER", "Haber")))

    if debe == 0 and haber == 0 and "IMPORTE" in fila.index:
        valor = limpiar_numero(_columna(fila, "IMPORTE"))
        if valor > 0:
            debe = valor
        elif valor < 0:
            haber = -valor

    return debe, haber


def _desde_dataframe(df, fuente: str = "El archivo") -> LecturaMayor:
    """
    Convierte un DataFrame ya leido en las filas que consume el cruce.

    Lo comparten la via archivo (leer_mayor) y el JSON del webreport de Xubio
    (leer_mayor_desde_json): de donde salen las columnas no cambia como se
    traducen los encabezados ni como se leen los signos.

    Cada fila queda como {fecha, concepto, comprobante, debe, haber}, que es lo
    que conciliador.conciliar_movimientos espera del lado de Xubio. Sin fecha no
    hay cruce (la tolerancia se mide en dias), asi que una fuente cuyas fechas
    no se entienden se rechaza en vez de devolver una bandeja de pendientes
    eterna.

    Antes de renombrar guarda los encabezados originales: el error tiene que
    nombrar lo que traia la fuente, no como lo llamo el traductor.
    """
    columnas = [str(c) for c in df.columns]
    mapa = mapa_de_columnas(df)
    df = normalizar_columnas(df)

    if "FECHA" not in df.columns:
        raise ErrorDeExtraccion(
            "El Libro Mayor no tiene columna de Fecha. Se encontraron estas "
            f"columnas: {columnas}. Exportá el mayor con Fecha, Debe y Haber."
        )
    if not ({"DEBE", "HABER", "IMPORTE"} & set(df.columns)):
        raise ErrorDeExtraccion(
            "El Libro Mayor no tiene columnas de importe (Debe, Haber ni "
            f"Importe). Se encontraron estas columnas: {columnas}."
        )

    convencion = _convencion(mapa)
    invertir = convencion == "cuenta"

    movimientos = []
    sin_fecha = 0
    sin_importe = 0

    for _, fila in df.iterrows():
        concepto = str(_columna(fila, "DETALLE", "Concepto") or "").strip()
        # El numero de comprobante va por su columna cuando el export la trae
        # ("Comprobante", "Nro comprobante"...). El traductor de columnas la
        # deja en REFERENCIA (la misma canonica que usa el extracto bancario
        # para el numero de operacion); leerla de ahi es lo mismo que leerla de
        # un nombre que no existe. Sin la columna no se inventa: quedar como
        # '—' en la bandeja derecha es mejor que confundirla con el detalle.
        comprobante = (
            str(_columna(fila, "REFERENCIA") or "").strip() or None
            if "REFERENCIA" in df.columns
            else None
        )
        # La fila de saldo es un resumen del periodo, no un movimiento: si entra
        # queda para siempre en la bandeja de pendientes sin par posible.
        if _es_saldo_inicial(concepto):
            continue

        debe, haber = _importes_mayor(fila)
        if invertir:
            # Movimientos de CC: el debito es salida. En terminos contables la
            # misma fila va al HABER (la cuenta bancaria baja), y el credito
            # (plata que entra) va al DEBE.
            debe, haber = haber, debe
        if debe == 0 and haber == 0:
            sin_importe += 1
            continue

        fecha = _parse_fecha(_columna(fila, "FECHA", "Fecha"))
        if fecha is None:
            sin_fecha += 1

        movimientos.append(
            {
                "fecha": fecha,
                "concepto": concepto,
                "comprobante": comprobante,
                "debe": debe,
                "haber": haber,
            }
        )

    if not movimientos:
        raise ErrorDeExtraccion(
            f"{fuente} no tiene movimientos del Libro Mayor: no se encontro "
            f"ninguna fila con importe. Se descartaron {sin_importe} filas sin "
            "Debe ni Haber."
        )

    if not any(m["fecha"] for m in movimientos):
        raise ErrorDeExtraccion(
            "Se leyeron movimientos pero ninguno tiene una fecha reconocible "
            "(dd/mm/aaaa o aaaa-mm-dd). Sin fecha el cruce no tiene como "
            "compararlos contra el extracto."
        )

    if sin_fecha:
        # No se rechaza el archivo por unas filas sueltas: quedan en la bandeja
        # de pendientes y una persona puede parearlas a mano.
        logger.warning("Libro Mayor: %d filas sin fecha no van a poder cruzarse", sin_fecha)
    logger.info(
        "Libro Mayor: %d movimientos, convencion %s (%d filas sin importe, %d sin fecha)",
        len(movimientos),
        convencion,
        sin_importe,
        sin_fecha,
    )
    return LecturaMayor(movimientos, convencion)


def leer_mayor(ruta: str) -> LecturaMayor:
    """
    Lee el archivo contable exportado desde el navegador.

    Abre el Excel/CSV y delega el armado de las filas en _desde_dataframe, que
    es el mismo que usa la via web de Xubio: un solo traductor de columnas y
    una sola convencion de signos para las dos fuentes.
    """
    try:
        df = leer_tabla(ruta, es_encabezado=_es_encabezado_de_mayor)
    except ErrorDeExtraccion:
        raise
    except Exception as e:
        # openpyxl tira sus propias excepciones cuando el archivo no es un libro.
        logger.exception("No se pudo leer el Libro Mayor")
        raise ErrorDeExtraccion(f"No se pudo leer el Libro Mayor: {e}") from e

    return _desde_dataframe(df)


# ----------------------------------------------------------------------
# El mismo mayor, pero por la via web de Xubio (el webreport real)
# ----------------------------------------------------------------------
#
# El webreport de Xubio (framework Faf/NXV) NO devuelve JSON: devuelve XML
# con la estructura:
#   <root><dataset><fields>...</fields><data>CSV_SEPARADO_POR_PUNTO_Y_COMA</data></dataset></root>
#
# El CSV tiene un PK inicial + 43 columnas (FECHA, DEBEMONPRINCIPAL, HABERMONPRINCIPAL,
# DEBE, HABER, SALDO, DESCRIPCION, COMPROBANTE, etc.). Se parsea directo a
# DataFrame y se reusa _desde_dataframe, igual que la via archivo.
#
# Para no romper tests que usan MAYOR_JSON sintetico, si la entrada es dict/list
# se intenta el parser JSON viejo (compatibilidad). Si es str con XML, se usa el
# parser real.
# ----------------------------------------------------------------------


def _filas_del_webreport_json(datos) -> list[dict]:
    """Parser legacy para tests: el JSON que el test inventaba (p_Fecha, etc.)."""
    _CLAVES_DE_FILAS = ("data", "datos", "rows", "filas", "registros", "items", "content")
    if isinstance(datos, list):
        crudo = datos
    elif isinstance(datos, dict):
        crudo = next(
            (datos[c] for c in _CLAVES_DE_FILAS if isinstance(datos.get(c), list)),
            None,
        )
        if crudo is None:
            crudo = next((v for v in datos.values() if isinstance(v, list)), None)
    else:
        crudo = None
    if not isinstance(crudo, list):
        return []
    return [fila for fila in crudo if isinstance(fila, dict)]


def _sin_prefijo_de_parametro(nombre) -> str:
    """'p_Fecha' -> 'Fecha': el webreport nombra sus parametros con p_."""
    texto = str(nombre)
    return texto[2:] if texto[:2].lower() == "p_" else texto


def _parsear_webreport_xml(xml_texto: str) -> "pd.DataFrame":
    """Convierte el XML real del webreport en DataFrame con columnas canonicas.

    El XML tiene <dataset><fields> (metadatos) y <data> (CSV ; y ,).
    Se extraen los nombres de <field name="...">, se splitte el CSV y se arma
    el DataFrame. El PK inicial se descarta.
    """
    import xml.etree.ElementTree as ET

    raiz = ET.fromstring(xml_texto)
    dataset = raiz.find("dataset")
    if dataset is None:
        raise ErrorDeExtraccion("XML del webreport sin <dataset>")

    campos_elem = dataset.find("fields")
    if campos_elem is None:
        raise ErrorDeExtraccion("XML del webreport sin <fields>")
    nombres = [f.get("name") for f in campos_elem.findall("field")]

    data_elem = dataset.find("data")
    if data_elem is None or not data_elem.text:
        raise ErrorDeExtraccion("XML del webreport sin <data> o vacio")

    filas = [r for r in data_elem.text.split(";") if r != ""]
    if not filas:
        raise ErrorDeExtraccion("XML del webreport: <data> sin filas")

    # Cada fila: PK + len(nombres) valores. El PK se descarta.
    esperado = len(nombres) + 1
    datos = []
    for fila in filas:
        partes = fila.split(",")
        if len(partes) != esperado:
            continue
        datos.append(partes[1:])  # descartar PK

    if not datos:
        raise ErrorDeExtraccion("XML del webreport: ninguna fila con el conteo esperado")

    import pandas as pd
    df = pd.DataFrame(datos, columns=nombres)
    return df


def leer_mayor_desde_json(datos) -> LecturaMayor:
    """
    Convierte la respuesta cruda del webreport de Xubio en movimientos.

    Acepta dos formatos:
    1. XML real (str): <root><dataset><fields>..</fields><data>CSV</data></dataset></root>
    2. JSON sintético (dict/list): compatibilidad con tests viejos (p_Fecha, etc.)

    En ambos casos delega en _desde_dataframe para reusar el traductor de columnas
    y la convencion de signos (contable vs cuenta).
    """
    # XML real del webreport Faf/NXV
    if isinstance(datos, str) and datos.lstrip().startswith("<?xml"):
        df = _parsear_webreport_xml(datos)
        return _desde_dataframe(df, fuente="El Libro Mayor de Xubio (webreport)")

    # JSON legacy (tests)
    filas = _filas_del_webreport_json(datos)
    if not filas:
        raise ErrorDeExtraccion(
            "El Libro Mayor de Xubio no trajo movimientos. La grilla llego como "
            f"{type(datos).__name__} y no tiene una lista de filas por objeto."
        )

    df = pd.DataFrame(filas)
    df.columns = [_sin_prefijo_de_parametro(c) for c in df.columns]
    return _desde_dataframe(df, fuente="El Libro Mayor de Xubio")


# Alias para compatibilidad: los tests llaman a esta funcion.
filas_del_webreport = _filas_del_webreport_json