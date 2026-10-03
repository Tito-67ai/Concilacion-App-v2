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