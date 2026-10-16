"""Arma los asientos de ajuste de las partidas que no tuvieron coincidencia.

Que hace y por que existe
-------------------------
El cuadro de "asientos sin coincidencia" del papel de trabajo (exportador.py)
lista las partidas que quedaron sin par, pero no las convierte en un asiento
contable: son filas sueltas con Debe/Haber/Importe. Un contador no puede cargar
eso en el sistema tal cual. Este modulo toma esas mismas partidas y arma, para
cada una, un asiento de PARTIDA DOBLE que balancea: Debe = Haber.

Criterio contable
-----------------
Todo movimiento del extracto o del Libro Mayor mueve la cuenta bancaria. Segun
de que lado este la plata, la contrapartida del asiento cambia:

- Entra plata (aumenta el Banco):   Debe <contracuenta>  /  Haber <Banco>
- Sale plata (disminuye el Banco):  Debe <Banco>         /  Haber <contracuenta>

Ojo con los signos: los dos lados del cruce NO usan la misma convencion.

- Extracto del banco (origen "banco"): `debe` es una SALIDA de plata (el banco
  debita la cuenta del cliente) y `haber` una ENTRADA. Es la convencion del
  "Debito en $" negativo que escribe el papel de trabajo.
- Libro Mayor (origen "mayor"): `debe`/`haber` son la convencion contable
  normal sobre el activo. Un `debe` en el mayor es plata que ENTRA al banco y un
  `haber` es plata que SALE. Por eso el cruce enfrenta Debe Mayor contra Credito
  Banco (conciliador_avanzado.py): son el mismo movimiento con el signo dado
  vuelta.

La contracuenta se elige asi:

- Extracto + gasto/impuesto del banco (comision, IVA, sellado, imp. ley 25.413,
  SIRCREB): la subcategoria real (Comisiones, IVA, Ingresos Brutos, Impuestos,
  Sellado) o "Gastos bancarios" si no encaja en ninguna.
- Extracto + cualquier otro concepto: la cuenta de conciliacion de banco.
- Libro Mayor: la cuenta de conciliacion del mayor, porque son partidas en
  transito (cheques no debitados, depositos no acreditados) que todavia no
  tienen contrapartida en el banco.

Todas las cuentas salen de la config (settings.CUENTA_*) para que cada empresa
las apunte a su plan de cuentas sin tocar el codigo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.config import settings
from app.models.schemas import PendienteExport
from app.services.clasificacion import _subcategoria_gasto, es_gasto_bancario

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


@dataclass
class AsientoAjuste:
    """Un asiento de ajuste de partida doble: sus lineas balancean."""

    numero: int
    fecha: date | None
    origen: str
    concepto: str
    referencia: str = ""
    lineas: list[LineaAsiento] = field(default_factory=list)

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


def cuenta_contrapartida_banco(concepto: str) -> str:
    """La contracuenta del extracto: subcategoria del gasto o cuenta de conciliacion."""
    if es_gasto_bancario(concepto):
        return _subcategoria_gasto(concepto) or settings.CUENTA_GASTOS_BANCARIOS
    return settings.CUENTA_CONCILIACION_BANCO


def _origen_del_pendiente(pendiente: PendienteExport) -> str:
    """Deduce el lado desde el campo `origen` cuando no se pasa explicito."""
    texto = (pendiente.origen or "").lower()
    if "mayor" in texto or "xubio" in texto:
        return ORIGEN_MAYOR
    return ORIGEN_BANCO


def asiento_desde_pendiente(
    numero: int,
    pendiente: PendienteExport,
    origen: str | None = None,
) -> AsientoAjuste | None:
    """Convierte una partida sin coincidencia en un asiento de partida doble.

    `origen` es "banco" o "mayor"; si no se pasa se deduce del campo `origen`
    del pendiente. Devuelve None si la partida no tiene importe (no hay nada que
    asentar).
    """
    origen = origen or _origen_del_pendiente(pendiente)
    banco = settings.CUENTA_BANCO
    detalle = _detalle(pendiente)

    if origen == ORIGEN_MAYOR:
        # El mayor es la cuenta banco de los libros: debe = entra, haber = sale.
        importe = _importe(pendiente.debe) or _importe(pendiente.haber)
        entra = _importe(pendiente.debe) != 0
        contracuenta = settings.CUENTA_CONCILIACION_MAYOR
    else:
        # El extracto: debe = sale, haber = entra.
        importe = _importe(pendiente.debe) or _importe(pendiente.haber)
        entra = _importe(pendiente.haber) != 0
        contracuenta = cuenta_contrapartida_banco(pendiente.concepto)

    if not importe:
        return None

    if entra:
        lineas = [
            LineaAsiento(banco, detalle, debe=importe),
            LineaAsiento(contracuenta, detalle, haber=importe),
        ]
    else:
        lineas = [
            LineaAsiento(contracuenta, detalle, debe=importe),
            LineaAsiento(banco, detalle, haber=importe),
        ]

    return AsientoAjuste(
        numero=numero,
        fecha=pendiente.fecha,
        origen=origen,
        concepto=(pendiente.concepto or "").strip(),
        referencia=(pendiente.comprobante or pendiente.referencia or "").strip(),
        lineas=lineas,
    )


def construir_asientos(
    pendientes_banco: list[PendienteExport] | None = None,
    pendientes_xubio: list[PendienteExport] | None = None,
) -> list[AsientoAjuste]:
    """Los asientos de ajuste de las dos bandejas, numerados y en orden de fecha.

    Se ordenan por fecha (y origen para que el orden sea estable entre corridas)
    porque el asiento se numera como aparece en el papel: dos exportaciones del
    mismo estado dan exactamente los mismos numeros.
    """
    partidas = (
        [(p, ORIGEN_BANCO) for p in (pendientes_banco or [])]
        + [(p, ORIGEN_MAYOR) for p in (pendientes_xubio or [])]
    )
    partidas.sort(key=lambda par: (par[0].fecha or date.min, par[1], (par[0].concepto or "")))

    asientos: list[AsientoAjuste] = []
    for pendiente, origen in partidas:
        asiento = asiento_desde_pendiente(len(asientos) + 1, pendiente, origen)
        if asiento is not None:
            asientos.append(asiento)
    return asientos


def totales(asientos: list[AsientoAjuste]) -> tuple[float, float]:
    """(total Debe, total Haber) de todos los asientos: tienen que coincidir."""
    total_debe = round(sum(a.debe for a in asientos), 2)
    total_haber = round(sum(a.haber for a in asientos), 2)
    return total_debe, total_haber
