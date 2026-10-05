from pydantic import BaseModel
from typing import Optional
from datetime import date

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