import logging
from decimal import Decimal

from app.models.schemas import MovimientoBancario
from app.services.clasificacion import clasificar, resumir_categorias

logger = logging.getLogger(__name__)

TOLERANCIA_DIAS = 3


def _dec(valor) -> Decimal:
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _importe_banco(mov: MovimientoBancario) -> Decimal:
    """
    Importe con signo del extracto bancario: lo que entra suma, lo que sale resta.

    El DEBE es salida de plata y el HABER es entrada, igual que en el resto del
    proyecto, asi que el signo unificado es haber - debe.
    """
    return _dec(mov.haber) - _dec(mov.debe)


def _importe_xubio(mov: dict) -> Decimal:
    """Importe con signo del mayor de Xubio: ahi un ingreso va al DEBE."""
    return _dec(mov.get("debe")) - _dec(mov.get("haber"))


def _a_fecha(valor):
    from datetime import date, datetime

    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(valor.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def conciliar_movimientos(
    movimientos_banco: list[MovimientoBancario],
    movimientos_xubio: list[dict],
    tolerancia_dias: int = TOLERANCIA_DIAS,
) -> dict:
    """
    Cruza el extracto del banco contra el mayor de Xubio, de a uno.

    El cruce anterior usaba un merge de pandas solo por monto, sin mirar la
    fecha. Eso multiplicaba las filas: 3 movimientos de $50.000 en el banco y 2
    en Xubio daban 6 filas de resultado en vez de 2, y el saldo de la pantalla
    no cerraba con nada.

    Ademas el cruce es uno a uno: un movimiento del banco no puede quedar
    emparejado con dos de Xubio ni al reves.

    El importe tiene que coincidir AL CENTIMO. Una diferencia de un centavo sale
    en las dos bandejas de pendientes en vez de conciliar sola, y eso es lo que
    se quiere: si el banco y el sistema contable no dicen lo mismo, que un
    humano lo mire. Automatizar ese cruce esconderia una diferencia real de
    contabilidad. (El redondeo del banco si se tolera, pero en otra parte: es lo
    que hace TrackerSaldo al deducir el signo de cada linea del extracto, que
    solo necesita orientarse y no decide si dos transacciones son la misma.)

    Devuelve las tres bandejas: conciliados, pendientes_banco y pendientes_xubio.
    """
    banco = []
    # Importes del banco agrupados, para no recorrer toda la lista por cada fila
    # de Xubio. Se arma junto con la lista para no perder precision al pasar el
    # importe por float.
    indice_banco: dict[Decimal, list[int]] = {}

    for i, m in enumerate(movimientos_banco):
        importe = _importe_banco(m)
        banco.append(
            {
                "origen": "banco",
                "fecha": m.fecha,
                "concepto": m.concepto,
                "referencia": m.referencia,
                "debe": float(m.debe),
                "haber": float(m.haber),
                "saldo": float(m.saldo),
                "importe": float(importe),
                # getAttribute no, es un modelo: la categoria la cargo el
                # procesador al armar el movimiento. El fallback es para cuando
                # alguien arma un MovimientoBancario a mano y se olvida.
                "categoria": getattr(m, "categoria", None) or clasificar(m.concepto),
            }
        )
        indice_banco.setdefault(importe, []).append(i)

    xubio = [
        {
            "origen": "xubio",
            "fecha": _a_fecha(m.get("fecha")),
            "concepto": str(m.get("concepto") or "").strip(),
            # El numero de comprobante del mayor no participa del cruce (se
            # compara importe y fecha), pero no se puede tirar: la bandeja
            # derecha lo muestra al lado de la fecha y el detalle.
            "comprobante": str(m.get("comprobante") or "").strip() or None,
            "debe": float(_dec(m.get("debe"))),
            "haber": float(_dec(m.get("haber"))),
            "importe": float(_importe_xubio(m)),
        }
        for m in movimientos_xubio
    ]

    if not banco or not xubio:
        return {
            "conciliados": [],
            "pendientes_banco": banco,
            "pendientes_xubio": xubio,
            "categorias": resumir_categorias(banco),
        }

    usados = set()
    usados_xubio = set()
    pareados = []

    for indice_x, mov_x in enumerate(xubio):
        candidatos = [
            i
            for i in indice_banco.get(_dec(mov_x["importe"]), [])
            if i not in usados
        ]
        if not candidatos:
            continue

        # Primero el mismo dia; si no hay, uno dentro de la tolerancia.
        def distancia(i):
            fecha_banco = banco[i]["fecha"]
            if mov_x["fecha"] is None or fecha_banco is None:
                return None
            return abs((fecha_banco - mov_x["fecha"]).days)

        con_fecha = [(distancia(i), i) for i in candidatos]
        con_fecha = [(d, i) for d, i in con_fecha if d is not None]
        elegido = None

        if con_fecha:
            con_fecha.sort()
            if con_fecha[0][0] == 0:
                elegido = con_fecha[0][1]
            elif con_fecha[0][0] <= tolerancia_dias:
                elegido = con_fecha[0][1]

        if elegido is None:
            logger.info(
                "Xubio %s (%s) tiene el importe pero no hay movimiento del banco "
                "en la fecha ni dentro de %s dias",
                mov_x["fecha"],
                mov_x["importe"],
                tolerancia_dias,
            )
            continue

        usados.add(elegido)
        usados_xubio.add(indice_x)
        pareados.append((banco[elegido], mov_x))

    conciliados = []
    for mov_b, mov_x in pareados:
        conciliados.append(
            {
                "fecha": mov_b["fecha"].isoformat() if mov_b["fecha"] else None,
                "concepto_banco": mov_b["concepto"],
                "concepto_xubio": mov_x["concepto"],
                # El comprobante y el importe unificado del lado de Xubio: el par
                # guarda los del banco, y la bandeja derecha muestra los del
                # mayor (importe = debe - haber, al reves que el banco).
                "comprobante_xubio": mov_x.get("comprobante"),
                "importe_xubio": mov_x["importe"],
                "debe": mov_b["debe"],
                "haber": mov_b["haber"],
                "saldo": mov_b["saldo"],
                "importe": mov_b["importe"],
                "categoria": mov_b["categoria"],
                "cuadra": True,
            }
        )

    pendientes_banco = [mov for i, mov in enumerate(banco) if i not in usados]
    pendientes_xubio = [mov for i, mov in enumerate(xubio) if i not in usados_xubio]

    conteo = resumir_categorias(banco)

    logger.info(
        "Cruce: %d conciliados, %d del banco sin cruce, %d de Xubio sin cruce",
        len(conciliados),
        len(pendientes_banco),
        len(pendientes_xubio),
    )
    logger.info(
        "Del banco: %d operativos, %d percepciones, %d impuestos",
        conteo["operativo"],
        conteo["percepcion"],
        conteo["impuesto"],
    )

    return {
        "conciliados": conciliados,
        "pendientes_banco": pendientes_banco,
        "pendientes_xubio": pendientes_xubio,
        "categorias": conteo,
    }