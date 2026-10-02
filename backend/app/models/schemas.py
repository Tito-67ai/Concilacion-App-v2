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
    cantidad_movimientos: int
    datos: list[MovimientoBancario]