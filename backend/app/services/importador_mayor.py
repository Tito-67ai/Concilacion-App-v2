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


def leer_mayor(ruta: str) -> LecturaMayor:
    """
    Convierte el archivo contable en las filas que consume el cruce.

    Cada fila queda como {fecha, concepto, debe, haber}, que es lo que
    conciliador.conciliar_movimientos espera del lado de Xubio. Sin fecha no hay
    cruce (la tolerancia se mide en dias), asi que un archivo cuyas fechas no se
    entienden se rechaza en vez de devolver una bandeja de pendientes eterna.
    """
    try:
        df = leer_tabla(ruta, es_encabezado=_es_encabezado_de_mayor)
        # Antes de renombrar: el error tiene que decirle al usuario que
        # encabezados tenia SU archivo, no como los llamo el traductor, y hay
        # que saber con que nombre original quedo cada canonica para decidir la
        # convencion de los importes.
        columnas = [str(c) for c in df.columns]
        mapa = mapa_de_columnas(df)
        df = normalizar_columnas(df)
    except ErrorDeExtraccion:
        raise
    except Exception as e:
        # openpyxl tira sus propias excepciones cuando el archivo no es un libro.
        logger.exception("No se pudo leer el Libro Mayor")
        raise ErrorDeExtraccion(f"No se pudo leer el Libro Mayor: {e}") from e

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
                "debe": debe,
                "haber": haber,
            }
        )

    if not movimientos:
        raise ErrorDeExtraccion(
            "El archivo no tiene movimientos del Libro Mayor: no se encontro "
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