"""Arma los asientos de ajuste de las partidas que no tuvieron coincidencia.

Que hace y por que existe
-------------------------
El cuadro de "asientos sin coincidencia" del papel de trabajo (exportador.py)
lista las partidas que quedaron sin par, pero no las convierte en un asiento
contable: son filas sueltas con Debe/Haber/Importe. Un contador no puede cargar
eso en el sistema tal cual. Este modulo toma esas mismas partidas y arma, para
las que corresponden, un asiento de PARTIDA DOBLE que balancea: Debe = Haber.

Que partidas generan asiento lo decide `reglas_conciliacion.py` (las reglas de
negocio del pedido), no este modulo:

- Gasto bancario / retencion / impuesto del extracto -> asiento automatico.
- Debito automatico (pago directo no contabilizado)  -> asiento, a revisar.
- Ingreso o transferencia no registrada              -> NO asiento (se marca
  para que una persona asigne la cuenta del cliente).
- Partida que esta en el mayor pero no en el banco   -> NO asiento: es una
  diferencia temporal que se arrastra al periodo siguiente.

Criterio contable
-----------------
Todo movimiento del extracto mueve la cuenta bancaria. Segun de que lado este la
plata, la contrapartida del asiento cambia:

- Entra plata (aumenta el Banco):   Debe <Banco>         /  Haber <contracuenta>
- Sale plata (disminuye el Banco):  Debe <contracuenta>  /  Haber <Banco>

Ojo con los signos: en el extracto `debe` es una SALIDA (el banco debita la
cuenta del cliente) y `haber` una ENTRADA.

Las cuentas salen de la config (settings.CUENTA_*) para que cada empresa las
apunte a su plan de cuentas sin tocar el codigo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.config import settings
from app.models.schemas import PendienteExport
from app.services.reglas_conciliacion import (
    ACCION_ASIENTO,
    CONTRACUENTA_CONCILIACION_BANCO,
    CONTRACUENTA_GASTOS,
    CONTRACUENTA_RETENCIONES,
    ETIQUETAS_TIPO,
    ClasificacionSinCoincidencia,
    clasificar_sin_coincidencia,
)

ORIGEN_BANCO = "banco"
ORIGEN_MAYOR = "mayor"

ETIQUETA_ORIGEN = {
    ORIGEN_BANCO: "Banco",
    ORIGEN_MAYOR: "Libro Mayor",
}


@dataclass
class LineaAsiento:
    """Un renglon de un asiento: una cuenta con su Debe o su Haber."""

    cuenta: str
    detalle: str
    debe: float = 0.0
    haber: float = 0.0
    # Codigo del plan de cuentas (settings.CUENTA_*_CODIGO). Puede ir vacio.
    cuenta_codigo: str = ""
    # "contracuenta" o "banco": distingue los dos renglones para la pantalla.
    rol: str = ""


@dataclass
class AsientoAjuste:
    """Un asiento de ajuste de partida doble: sus lineas balancean."""

    numero: int
    fecha: date | None
    origen: str
    concepto: str
    referencia: str = ""
    lineas: list[LineaAsiento] = field(default_factory=list)
    # Tipo de regla que lo genero (reglas_conciliacion.TIPO_*).
    tipo: str = ""
    # Etiqueta humana de la regla / nombre de la contracuenta (Comisiones, IVA...).
    regla: str = ""
    # "propuesto" | "editado" | "aprobado" | "inyectado" | "error".
    estado: str = "propuesto"
    # True cuando la contracuenta es provisoria y una persona deberia revisarla.
    revisar_manual: bool = False
    # CUIT del tercero, si el extracto crudo lo aporto.
    cuit: str | None = None

    @property
    def debe(self) -> float:
        return sum(linea.debe for linea in self.lineas)

    @property
    def haber(self) -> float:
        return sum(linea.haber for linea in self.lineas)

    @property
    def importe(self) -> float:
        """El importe del hecho economico: el Debe (que iguala al Haber)."""
        return self.debe

    @property
    def balancea(self) -> bool:
        """True si la partida doble cierra (tolerancia de un centavo)."""
        return abs(self.debe - self.haber) < 0.005


@dataclass
class PartidaTemporal:
    """Una partida sin coincidencia que NO lleva asiento automatico.

    Es lo que la pantalla muestra aparte: los ingresos sin comprobante (a
    asignar cuenta) y las diferencias temporales del mayor.
    """

    origen: str
    tipo: str
    regla: str
    fecha: date | None
    concepto: str
    referencia: str = ""
    importe: float = 0.0
    revisar_manual: bool = False

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS_TIPO.get(self.tipo, self.tipo)


def _importe(valor: object) -> float:
    try:
        return round(float(valor or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _detalle(pendiente: PendienteExport) -> str:
    texto = (pendiente.concepto or "").strip()
    referencia = (pendiente.comprobante or "").strip() or (pendiente.referencia or "").strip()
    if referencia and referencia not in texto:
        return f"{texto} · {referencia}" if texto else referencia
    return texto


def _origen_del_pendiente(pendiente: PendienteExport) -> str:
    """Deduce el lado desde el campo `origen` cuando no se pasa explicito."""
    texto = (pendiente.origen or "").lower()
    if "mayor" in texto or "xubio" in texto:
        return ORIGEN_MAYOR
    return ORIGEN_BANCO


def _entra_plata(pendiente: PendienteExport, origen: str) -> bool:
    """True si el movimiento es una entrada al banco.

    En el extracto entra = haber != 0; en el mayor (convencion contable sobre el
    activo) entra = debe != 0.
    """
    if origen == ORIGEN_MAYOR:
        return _importe(pendiente.debe) != 0
    return _importe(pendiente.haber) != 0


def _cuenta_contracuenta(clasificacion: ClasificacionSinCoincidencia) -> tuple[str, str]:
    """Resuelve (nombre, codigo) de la contracuenta segun la clave logica.

    El nombre suele ser la subcategoria (Comisiones, IVA, SIRCREB...), que es
    como aparece en el extracto. Para el debito automatico la contracuenta es la
    cuenta de conciliacion de banco de la config (la regla solo describe el
    caso, no es un nombre de cuenta).
    """
    if clasificacion.contracuenta == CONTRACUENTA_RETENCIONES:
        nombre = clasificacion.regla or settings.CUENTA_RETENCIONES
        codigo = settings.CUENTA_RETENCIONES_CODIGO
    elif clasificacion.contracuenta == CONTRACUENTA_GASTOS:
        nombre = clasificacion.regla or settings.CUENTA_GASTOS_BANCARIOS
        codigo = settings.CUENTA_GASTOS_BANCARIOS_CODIGO
    else:
        nombre = settings.CUENTA_CONCILIACION_BANCO
        codigo = settings.CUENTA_CONCILIACION_BANCO_CODIGO
    return nombre, codigo


def clasificar_pendiente(
    pendiente: PendienteExport,
    origen: str | None = None,
) -> ClasificacionSinCoincidencia:
    """Aplica las reglas de negocio a una partida sin coincidencia."""
    origen = origen or _origen_del_pendiente(pendiente)
    return clasificar_sin_coincidencia(
        origen,
        pendiente.concepto,
        _entra_plata(pendiente, origen),
    )


def asiento_desde_pendiente(
    numero: int,
    pendiente: PendienteExport,
    origen: str | None = None,
) -> AsientoAjuste | None:
    """Convierte una partida sin coincidencia en un asiento de partida doble.

    `origen` es "banco" o "mayor"; si no se pasa se deduce del campo `origen`
    del pendiente.

    Devuelve None cuando la partida NO lleva asiento automatico (ingreso no
    registrado o diferencia temporal del mayor) o cuando no tiene importe.
    """
    origen = origen or _origen_del_pendiente(pendiente)
    clasificacion = clasificar_pendiente(pendiente, origen)

    if not clasificacion.requiere_asiento:
        return None

    importe = _importe(pendiente.debe) or _importe(pendiente.haber)
    if not importe:
        return None

    banco = settings.CUENTA_BANCO
    entra = _entra_plata(pendiente, origen)
    contracuenta, codigo_contra = _cuenta_contracuenta(clasificacion)
    detalle = _detalle(pendiente)

    if entra:
        # Entra plata al banco: el activo aumenta (Debe Banco) y la
        # contracuenta se acredita.
        lineas = [
            LineaAsiento(banco, detalle, debe=importe, cuenta_codigo=settings.CUENTA_BANCO_CODIGO, rol="banco"),
            LineaAsiento(contracuenta, detalle, haber=importe, cuenta_codigo=codigo_contra, rol="contracuenta"),
        ]
    else:
        # Sale plata del banco: el activo disminuye (Haber Banco) y la
        # contracuenta se debita (gasto / impuesto).
        lineas = [
            LineaAsiento(contracuenta, detalle, debe=importe, cuenta_codigo=codigo_contra, rol="contracuenta"),
            LineaAsiento(banco, detalle, haber=importe, cuenta_codigo=settings.CUENTA_BANCO_CODIGO, rol="banco"),
        ]

    return AsientoAjuste(
        numero=numero,
        fecha=pendiente.fecha,
        origen=origen,
        concepto=(pendiente.concepto or "").strip(),
        referencia=(pendiente.comprobante or pendiente.referencia or "").strip(),
        lineas=lineas,
        tipo=clasificacion.tipo,
        regla=clasificacion.regla,
        estado="propuesto",
        revisar_manual=clasificacion.revisar_manual,
    )


def partida_temporal(
    pendiente: PendienteExport,
    origen: str | None = None,
) -> PartidaTemporal:
    """Arma el detalle de una partida sin coincidencia que no lleva asiento."""
    origen = origen or _origen_del_pendiente(pendiente)
    clasificacion = clasificar_pendiente(pendiente, origen)
    return PartidaTemporal(
        origen=origen,
        tipo=clasificacion.tipo,
        regla=clasificacion.regla,
        fecha=pendiente.fecha,
        concepto=(pendiente.concepto or "").strip(),
        referencia=(pendiente.comprobante or pendiente.referencia or "").strip(),
        importe=_importe(pendiente.debe) or _importe(pendiente.haber),
        revisar_manual=clasificacion.revisar_manual,
    )


def _partidas_ordenadas(
    pendientes_banco: list[PendienteExport] | None,
    pendientes_xubio: list[PendienteExport] | None,
) -> list[tuple[PendienteExport, str]]:
    partidas = (
        [(p, ORIGEN_BANCO) for p in (pendientes_banco or [])]
        + [(p, ORIGEN_MAYOR) for p in (pendientes_xubio or [])]
    )
    partidas.sort(key=lambda par: (par[0].fecha or date.min, par[1], (par[0].concepto or "")))
    return partidas


def construir_asientos(
    pendientes_banco: list[PendienteExport] | None = None,
    pendientes_xubio: list[PendienteExport] | None = None,
) -> list[AsientoAjuste]:
    """Los asientos de ajuste de las dos bandejas, numerados y en orden de fecha.

    Solo las partidas que, segun las reglas de negocio, llevan asiento. Los
    ingresos no registrados y las partidas del mayor se devuelven aparte con
    `partidas_sin_asiento`.

    Se ordenan por fecha (y origen para que el orden sea estable entre corridas)
    porque el asiento se numera como aparece en el papel: dos exportaciones del
    mismo estado dan exactamente los mismos numeros.
    """
    asientos: list[AsientoAjuste] = []
    for pendiente, origen in _partidas_ordenadas(pendientes_banco, pendientes_xubio):
        asiento = asiento_desde_pendiente(len(asientos) + 1, pendiente, origen)
        if asiento is not None:
            asientos.append(asiento)
    return asientos


def partidas_sin_asiento(
    pendientes_banco: list[PendienteExport] | None = None,
    pendientes_xubio: list[PendienteExport] | None = None,
) -> list[PartidaTemporal]:
    """Las partidas que NO llevan asiento automatico, en orden de fecha.

    Son los ingresos/transferencias no registradas (revision manual) y las
    diferencias temporales del mayor (se arrastran al periodo siguiente).
    """
    partidas: list[PartidaTemporal] = []
    for pendiente, origen in _partidas_ordenadas(pendientes_banco, pendientes_xubio):
        if clasificar_pendiente(pendiente, origen).accion == ACCION_ASIENTO:
            continue
        partidas.append(partida_temporal(pendiente, origen))
    return partidas


def proponer_asientos(
    pendientes_banco: list[PendienteExport] | None = None,
    pendientes_xubio: list[PendienteExport] | None = None,
) -> tuple[list[AsientoAjuste], list[PartidaTemporal]]:
    """(asientos propuestos, partidas sin asiento) de las dos bandejas."""
    return (
        construir_asientos(pendientes_banco, pendientes_xubio),
        partidas_sin_asiento(pendientes_banco, pendientes_xubio),
    )


def totales(asientos: list[AsientoAjuste]) -> tuple[float, float]:
    """(total Debe, total Haber) de todos los asientos: tienen que coincidir."""
    total_debe = round(sum(a.debe for a in asientos), 2)
    total_haber = round(sum(a.haber for a in asientos), 2)
    return total_debe, total_haber
