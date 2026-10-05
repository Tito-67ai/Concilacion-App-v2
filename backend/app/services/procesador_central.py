import logging
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from app.models.schemas import MovimientoBancario
from app.services.Tools import limpiar_numero
from app.services.clasificacion import clasificar
from app.services.bancos import (
    BcoBBK,
    BcoBBVA,
    BcoCMF,
    BcoGAL,
    BcoHIPO,
    BcoICBC,
    BcoMP,
    BcoPBA,
    BcoRIO,
    BcoSUPV,
)
from app.services.bancos.BcoSANT import extraer_santander_rio

logger = logging.getLogger(__name__)


class ErrorDeExtraccion(RuntimeError):
    """
    El PDF se pudo abrir pero el parser de este banco no logro sacar los movimientos.

    Antes esto se traducía en una lista vacía con HTTP 200: el banco roto
    parecia un extracto sin movimientos. Ahora sube como error y se ve el motivo.
    """


BANCOS = {
    "BBVA": BcoBBVA.extraer_bbva,
    "GAL": BcoGAL.extraer_galicia,
    "ICBC": BcoICBC.extraer_icbc,
    "RIO": BcoRIO.extraer_santander,
    "PBA": BcoPBA.extraer_provincia,
    "SUPV": BcoSUPV.extraer_supervielle,
    "CMF": BcoCMF.extraer_cmf,
    "HIPO": BcoHIPO.extraer_hipotecario,
    "BBK": BcoBBK.extraer_brubank,
    "MP": BcoMP.extraer_mp,
    "SANT": extraer_santander_rio,
}

FORMATOS_FECHA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d", "%d.%m.%Y")

# Palabras que los bancos usan para la fila de arranque de la cuenta
MARCAS_SALDO_INICIAL = ("SALDO INICIAL", "SALDO ANTERIOR", "SALDO ULTIMO", "SALDO INICIAL (MODIFICAR)")


def _log(mensaje):
    # Adaptador para los extractores, que reciben un log_callback(mensaje)
    logger.info("%s", mensaje)


def _borrar(ruta):
    try:
        if os.path.exists(ruta):
            os.remove(ruta)
    except OSError as e:
        logger.warning("No se pudo borrar el temporal %s: %s", ruta, e)


def _columna(fila, *nombres):
    """Primer valor presente de una lista de nombres de columna alternativos."""
    for nombre in nombres:
        if nombre in fila.index:
            return fila[nombre]
    return None


def _parse_fecha(valor):
    """Devuelve date, o None si la celda no tiene una fecha utilizable."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    if texto.upper() in ("", "INICIO", "S/D", "NAN", "NONE", "NAT", "NULL", "XXX"):
        return None
    for fmt in FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    return None


def _dec(valor) -> Decimal:
    """float a Decimal con dos decimales. Se usa para que el saldo no derive."""
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _importes(fila):
    """
    Devuelve (debe, haber) en valores positivos.

    La mayoria de los bancos separa en dos columnas; MP trae una sola columna
    IMPORTE con el signo ya puesto, y ahi el signo es la unica informacion.
    """
    debe = limpiar_numero(_columna(fila, "DEBE", "Debe"))
    haber = limpiar_numero(_columna(fila, "HABER", "Haber"))

    if debe == 0 and haber == 0 and "IMPORTE" in fila.index:
        valor = limpiar_numero(_columna(fila, "IMPORTE"))
        if valor > 0:
            haber = valor
        elif valor < 0:
            debe = -valor

    return abs(debe), abs(haber)


def _es_saldo_inicial(concepto) -> bool:
    arriba = str(concepto).upper()
    return any(marca in arriba for marca in MARCAS_SALDO_INICIAL)


def _es_semilla(fila) -> bool:
    """
    True si la fila solo arranca la cadena de saldos y no es un movimiento.

    Los extractores marcan el saldo de apertura con un texto ("SALDO INICIAL",
    "SALDO ULTIMO EXTRACTO AL 30/06/2026") y le dejan DEBE y HABER en cero. Esa
    fila existe para decirle de donde arrancar, no para cruzarse con Xubio: si se
    emite queda una fila 0/00 que aparece para siempre en la bandeja de
    pendientes.

    Exigir ademas DEBE y HABER en cero evita tragarse un movimiento real si un
    banco marca tambien una fila con importe: en ese caso gana el importe.
    """
    return fila["es_saldo_inicial"] and not fila["debe"] and not fila["haber"]


def _referencia(fila):
    valor = _columna(fila, "REFERENCIA", "ID_OPERACION", "Referencia")
    if valor is None:
        return None
    texto = str(valor).strip()
    if texto.upper() in ("", "NAN", "NONE", "-"):
        return None
    return texto


def _df_to_movimientos(df, nombre_banco: str = "?") -> list[MovimientoBancario]:
    """
    Convierte el Excel que escribio el extractor en movimientos.

    Los extractores ponen la columna SALDO como formula de Excel
    (=F{anterior}-E+ D). El archivo se borra al terminar y nunca lo abre nadie,
    asi que esa formula no se evalua nunca: al releerlo pandas la devuelve como
    vacio. Por eso el saldo se recalcula aca con DEBE y HABER, que si son datos
    reales de las filas.
    """
    columnas = set(df.columns)
    if not {"FECHA", "DETALLE"} <= columnas:
        raise ErrorDeExtraccion(
            f"{nombre_banco}: el Excel generado no tiene las columnas esperadas "
            f"(FECHA, DETALLE). Columns: {list(df.columns)}"
        )

    filas = []
    for _, fila in df.iterrows():
        concepto = str(_columna(fila, "DETALLE", "Concepto") or "").strip()
        debe, haber = _importes(fila)
        filas.append(
            {
                "concepto": concepto,
                "fecha": _parse_fecha(_columna(fila, "FECHA", "Fecha")),
                "debe": debe,
                "haber": haber,
                # Solo sirve en la fila de saldo inicial: en el resto la
                # sobreescribio la formula y vuelve vacio.
                "saldo_de_origen": limpiar_numero(_columna(fila, "SALDO", "Saldo", "SALDO_CALC")),
                "referencia": _referencia(fila),
                "es_saldo_inicial": _es_saldo_inicial(concepto),
            }
        )

    if not filas:
        logger.warning("%s: el extractor genero un Excel sin filas", nombre_banco)
        return []

    hay_movimientos = any(not _es_semilla(f) for f in filas)
    # El saldo inicial no tiene fecha propia: se le da la del primer movimiento
    # real del periodo, que es a quien corresponde ese saldo.
    primera_fecha = next(
        (f["fecha"] for f in filas if not _es_semilla(f) and f["fecha"]),
        None,
    )

    if hay_movimientos and primera_fecha is None:
        raise ErrorDeExtraccion(
            f"{nombre_banco}: se leyeron {len(filas)} filas pero ninguna tiene una "
            f"fecha reconocible. El parser de este banco no esta entendiendo el PDF."
        )

    movimientos = []
    saldo = Decimal("0.00")
    saldo_conocido = False
    fecha_actual = None
    sin_importe = 0
    ultimo_error_fecha = ""
    # Cuando el extractor capturo el saldo de la linea, lo usamos para
    # contrastar contra el que calculamos nosotros. Si no coinciden, el parser
    # se comio un movimiento o leyo mal un importe.
    saldos_impresos = 0
    saldos_descuadrados = 0

    for f in filas:
        if f["fecha"]:
            fecha_actual = f["fecha"]

        if _es_semilla(f):
            saldo = _dec(f["saldo_de_origen"])
            saldo_conocido = True
            if f["saldo_de_origen"]:
                logger.info("%s: saldo inicial %.2f", nombre_banco, f["saldo_de_origen"])
            # La fila de saldo inicial siembra la cadena y nada mas: no tiene
            # DEBE ni HABER, asi que nunca va a cruzar con Xubio. Emitarla deja
            # una fila 0/00 perpetua en la bandeja de pendientes. El saldo de
            # apertura no se pierde, se deriva del primer movimiento:
            #   saldo_inicial = movimientos[0].saldo + movimientos[0].debe
            #                                     - movimientos[0].haber
            continue

        # Todo lo que sigue es un movimiento. Si la marca de saldo inicial vino
        # con un importe, el importe manda y la fila se trata como una mas.
        if not saldo_conocido and f["saldo_de_origen"]:
            # El banco no trae fila de saldo inicial (Galicia, entre otros),
            # pero si imprime el saldo de cada linea. El de la primera fila es
            # el saldo ya aplicado, asi que para obtener el de apertura hay que
            # sacar el movimiento de esa misma fila. Si no, se descuenta dos
            # veces y todos los saldos quedan corridos.
            saldo = _dec(f["saldo_de_origen"]) - _dec(f["haber"]) + _dec(f["debe"])
            saldo_conocido = True
            logger.info(
                "%s: sin fila de saldo inicial, se deduce de la primera linea: %.2f",
                nombre_banco,
                saldo,
            )

        saldo = saldo - _dec(f["debe"]) + _dec(f["haber"])
        fecha_fila = f["fecha"] or fecha_actual

        if not fecha_fila:
            ultimo_error_fecha = f["concepto"][:60]
            continue

        if f["debe"] == 0 and f["haber"] == 0:
            # No lo borramos: puede ser un movimiento legitimo en cero o un
            # importe que el parser no logro capturar. Se cuenta y se avisa.
            sin_importe += 1

        # Contraste contra el saldo que el banco imprimio en la linea. Solo
        # tiene sentido si ese valor existe: en los bancos que dejan 0.0 y
        # calculan con formula de Excel, el 0.0 no es informacion real.
        if f["saldo_de_origen"] != 0.0:
            saldos_impresos += 1
            if abs(_dec(f["saldo_de_origen"]) - saldo) > Decimal("0.05"):
                saldos_descuadrados += 1
                if saldos_descuadrados <= 10:
                    logger.warning(
                        "%s: el saldo impreso no cuadra con el calculado en %r "
                        "(el banco dice %.2f, nosotros %.2f)",
                        nombre_banco,
                        f["concepto"][:50],
                        f["saldo_de_origen"],
                        float(saldo),
                    )

        movimientos.append(
            MovimientoBancario(
                fecha=fecha_fila,
                concepto=f["concepto"],
                referencia=f["referencia"],
                debe=f["debe"],
                haber=f["haber"],
                saldo=float(saldo),
                categoria=clasificar(f["concepto"]),
            )
        )

    if ultimo_error_fecha:
        logger.error(
            "%s: se descartaron filas sin fecha ni anterior. Ultima: %r",
            nombre_banco,
            ultimo_error_fecha,
        )
    if sin_importe:
        logger.warning(
            "%s: %d filas con DEBE y HABER en cero (importe no capturado o filtro del banco)",
            nombre_banco,
            sin_importe,
        )
    if saldos_descuadrados:
        logger.error(
            "%s: %d de %d filas con saldo impreso no cuadran con el calculado. "
            "El extractor se esta comiendo movimientos o leyendo mal un importe.",
            nombre_banco,
            saldos_descuadrados,
            saldos_impresos,
        )
    if not saldo_conocido and hay_movimientos:
        logger.warning(
            "%s: no se encontro el SALDO INICIAL ni un saldo por linea, "
            "los saldos arrancan en 0",
            nombre_banco,
        )

    return movimientos


def procesar_archivo(banco_id: str, ruta_pdf: str) -> list[MovimientoBancario]:
    """
    Corre el extractor del banco sobre el PDF y devuelve los movimientos.

    Sube ErrorDeExtraccion con el motivo si el banco no se pudo leer. No devuelve
    una lista vacia en silencio: una lista vacia es indistinguible de un extracto
    sin movimientos, y esa confusion fue la que escondia los parsers rotos.
    """
    banco = (banco_id or "").upper().strip()
    extractor = BANCOS.get(banco)
    if extractor is None:
        raise ValueError(
            f"El formato del banco '{banco_id}' no esta soportado. "
            f"Soportados: {', '.join(sorted(BANCOS))}"
        )

    if not os.path.isfile(ruta_pdf):
        raise ErrorDeExtraccion(f"No se encuentra el archivo a procesar: {ruta_pdf}")

    descriptor, excel_tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(descriptor)

    try:
        _log(f"Extrayendo PDF de {banco}")
        ok, resultado = extractor(ruta_pdf, excel_tmp, _log)
        if not ok:
            raise ErrorDeExtraccion(
                f"{banco}: no se pudieron extraer los movimientos. {resultado}"
            )

        df = pd.read_excel(excel_tmp)
        movimientos = _df_to_movimientos(df, banco)

        _log(
            f"{banco}: {len(movimientos)} movimientos, "
            f"saldo final {movimientos[-1].saldo if movimientos else 0}"
        )
        return movimientos
    except ErrorDeExtraccion:
        raise
    except Exception as e:
        logger.exception("Fallo inesperado leyendo el PDF de %s", banco)
        raise ErrorDeExtraccion(f"{banco}: error leyendo el PDF: {e}") from e
    finally:
        # Solo el Excel intermedio es de nuestra propiedad. El PDF es el
        # archivo que nos paso el llamador: borrarlo aqui destruia el original
        # cuando alguien reutilizaba la misma ruta (tests, scripts, la descarga
        # del usuario) y hacia que el motor generico ya no tuviera con que
        # trabajar en el fallback.
        _borrar(excel_tmp)