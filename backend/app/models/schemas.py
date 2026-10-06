from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional
from datetime import date, datetime


def _normalizar_fecha(valor: Any) -> Any:
    """Acepta las dos formas de fecha que se manejan en el proyecto.

    El cruce devuelve 'fecha' como date en los pendientes y como string ISO en
    los pares (conciliador.py:171), y el extractor de tablas puede mandar
    dd/mm/yyyy. Si el schema solo aceptara ISO, un papel de trabajo con una
    fecha en formato argentino no se exportaria: el 422 seria del backend y no
    de la conciliacion, que es imposible de adivinar desde la pantalla.
    """
    if not isinstance(valor, str):
        return valor
    texto = valor.strip()
    if not texto:
        return None
    if texto[0].isdigit() and "/" in texto:
        try:
            return datetime.strptime(texto, "%d/%m/%Y").date()
        except ValueError:
            return valor
    return texto

class MovimientoBancario(BaseModel):
    fecha: date
    concepto: str
    referencia: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    saldo: float
    # 'operativo', 'percepcion' o 'impuesto'. Solo etiqueta: no cambia el importe
    # ni si la fila participa del cruce. Sirve para que la pantalla pueda
    # esconder las percepciones e impuestos, que no son operaciones de la
    # empresa y casi nunca encuentran su par en Xubio.
    #
    # None y no 'operativo' a proposito: la etiqueta se deriva del concepto, no
    # se afirma a mano. Con el default puesto, un MovimientoBancario armado a
    # mano quedaria marcado como operativo sin clasificar nunca, y el filtro lo
    # esconderia de la bandeja sin que nadie lo haya decidido.
    categoria: Optional[str] = None
    
class RespuestaExtraccion(BaseModel):
    exito: bool
    banco: str
    # De donde se leyeron los movimientos: 'pdf' o 'tabla'. Opcional para que el
    # frontend no rompa si habla con un backend que no lo manda.
    origen: Optional[str] = None
    # Que extractor leyo el archivo. Sirve para ver cuando el motor generico
    # entra de rescate porque el parser del banco no pudo con ese PDF.
    motor: Optional[str] = None
    cantidad_movimientos: int
    datos: list[MovimientoBancario]


# ----------------------------------------------------------------------
# Exportacion del papel de trabajo (FO 02-03)
# ----------------------------------------------------------------------
#
# Lo que se exporta es el ESTADO de la conciliacion tal como quedo en la
# pantalla, no un cruce nuevo. Por eso el frontend manda las tres bandejas que
# ya tiene en memoria: si el exportador volviera a cruzar contra Xubio, el
# papel de trabajo podria no coincidir con lo que el usuario acabo de revisar
# (por ejemplo si hay pares armados a mano, que el backend nunca vio).


class EncabezadoConciliacion(BaseModel):
    """Los cuatro campos del membrete de FO 02-03."""

    empresa: str = ""
    banco: str = ""
    numero_cuenta: str = ""
    # El periodo va como 'YYYY-MM' porque la celda I5 de la plantilla tiene
    # formato 'mmmm yyyy': hay que escribir una fecha de Excel, no un texto.
    # Vacio significa "no se informo".
    periodo: Optional[str] = None


class ParConciliado(BaseModel):
    """Una fila de la pestana "Movimientos conciliados".

    Los dos campos 'fecha' y 'importe' los manda el cruce con convenciones
    distintas (conciliador.py): el banco unifica como haber - debe, Xubio como
    debe - haber. Si el frontend no manda 'importe', el exportador lo recalcula
    desde debe/haber del banco para no dejar la celda en cero.
    """

    fecha: Optional[date] = None
    concepto_banco: str = ""
    concepto_xubio: str = ""
    debe: float = 0.0
    haber: float = 0.0
    saldo: float = 0.0
    importe: Optional[float] = None
    categoria: Optional[str] = None
    # Que lo emparejo una persona y no el cruce automatico. Los pares
    # automaticos no mandan estos dos campos.
    manual: bool = False
    diferencia: Optional[float] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class PendienteExport(BaseModel):
    """Una fila sin cruzar, de cualquiera de los dos lados.

    'origen' distingue la bandeja: los pendientes del banco traen saldo y
    categoria, los de Xubio no.
    """

    origen: str = "banco"
    fecha: Optional[date] = None
    concepto: str = ""
    referencia: Optional[str] = None
    debe: float = 0.0
    haber: float = 0.0
    saldo: float = 0.0
    importe: Optional[float] = None
    categoria: Optional[str] = None

    _fecha = field_validator("fecha", mode="before")(_normalizar_fecha)


class SolicitudExportacion(BaseModel):
    conciliados: list[ParConciliado] = Field(default_factory=list)
    pendientes_banco: list[PendienteExport] = Field(default_factory=list)
    pendientes_xubio: list[PendienteExport] = Field(default_factory=list)
    encabezado: EncabezadoConciliacion = Field(default_factory=EncabezadoConciliacion)