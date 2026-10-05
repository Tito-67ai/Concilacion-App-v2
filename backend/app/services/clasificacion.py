"""
Clasifica los movimientos del extracto en operativo, percepcion o impuesto.

Por que existe: buena parte de un extracto bancario no son operaciones de la
empresa. Son dos cosas bien distintas:

- PERCEPCION: plata que la empresa retiene de un cliente y le gira a ARCA
  ("PERCEPCION IVA RG", "ING BRUTOS PERCEP. C.A.B.A", "R/RECAUDACION IB
  SIRCREB C"). La plata nunca fue de la empresa, asi que no es ingreso ni gasto y
  en contabilidad va a un pasivo, no a la cuenta bancaria. Si el cruce con Xubio
  busca el importe exacto en la cuenta bancaria, estas filas no encuentran nunca
  su par y quedan siempre en la bandeja de pendientes.

- IMPUESTO: lo que la empresa si paga, pero por cuenta de impuestos y no por
  una operacion. El banco cobra el IVA sobre sus propias comisiones
  ("IMPUESTO AL VALOR AGREGADO") y el impuesto a los debitos en cuenta corriente
  ("IMP S/DEBITOS EN CTA CTE"). Es un costo real, muchas veces con credito
  fiscal, pero no es la operacion que uno esta buscando al conciliar.

En el extracto real de ICBC de 90 movimientos, 39 caian en estas dos categorias:
el 43%. Sin separarlas, la bandeja de pendientes se llena de ruido y se esconde
la diferencia de contabilidad que si hay que mirar.

Lo que NO hace este modulo: no descarta nada, no cambia ningun importe y no
toca el cruce del conciliador. Solo etiqueta. La decision de si conviene
conciliarlas o dejarlas aside la toma una persona, con el filtro de la pantalla.

Ojo con los patrones: son heuristicos y hay que revisarlos contra los conceptos
que mandan los bancos. Cuando aparece uno nuevo que no entra en ninguna
categoria, la fila queda como OPERATIVO, que es el default que no esconde nada.
Por eso el orden importa: se prueba PERCEPCION antes que IMPUESTO, asi un
concepto que menciona los dos se cuelga de la categoria mas especifica.
"""

import re
import unicodedata

OPERATIVO = "operativo"
PERCEPCION = "percepcion"
IMPUESTO = "impuesto"

# Para mostrar en la pantalla.
ETIQUETAS = {
    OPERATIVO: "Operativo",
    PERCEPCION: "Percepción",
    IMPUESTO: "Impuesto",
}

# Las que no son operacion y conviene poder esconder de la bandeja.
NO_OPERATIVAS = (PERCEPCION, IMPUESTO)


def _normalizar(texto: str) -> str:
    """Mayusculas, sin acentos y sin espacios doubles.

    Los conceptos salen del PDF ya sin acentos, pero el mismo texto puede venir
    de la importacion de tablas o de un banco que si los trae.
    """
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.upper()).strip()


# Retenciones y percepciones que la empresa gira a ARCA.
#
# Ojo: "ING BRUTOS" suelta NO va aca. Los conceptos de los dos bancos reales son
# "ING BRUTOS PERCEP. C.A.B.A" y "ING BRUTOS PERCEP. BUENOS", que ya caen por
# PERCEP. Con el patron suelto, "TRASPASO A ING BRUTOS SRL" (un traspaso a una
# empresa, o sea una operacion) quedaba como percepcion y se escondia del filtro
# de la pantalla sin que nadie lo pidiera.
RE_PERCEPCION = re.compile(
    r"PERCEP"  # PERCEPCION IVA, PERCEP. R.G., ING BRUTOS PERCEP.
    r"|RETENCION"
    r"|SIRCREB"
    r"|RECAUDACION"
)

# Impuestos que la empresa paga sobre su operatoria bancaria.
RE_IMPUESTO = re.compile(
    r"IMPUESTO AL VALOR AGREGADO"
    r"|IMP\s*S\s*/\s*DEBITOS"
    r"|IMP\s*S\s*/\s*CRED"
    r"|SELLAD[OS]"
    r"|IMPUESTO\s+SOBRE\s+DEBITOS"
)


def clasificar(concepto: str) -> str:
    """
    Devuelve la categoria del movimiento segun su concepto.

    Default OPERATIVO: antes dudar de una operacion y dejarla a mano, lo que sea
    raro que caiga en el filtrado.
    """
    texto = _normalizar(concepto)

    if RE_PERCEPCION.search(texto):
        return PERCEPCION
    if RE_IMPUESTO.search(texto):
        return IMPUESTO
    return OPERATIVO


def es_no_operativa(categoria: str) -> bool:
    return categoria in NO_OPERATIVAS


def resumir_categorias(rows) -> dict:
    """Cuenta movimientos por categoria. Para el resumen de la respuesta."""
    conteo = {OPERATIVO: 0, PERCEPCION: 0, IMPUESTO: 0}
    for row in rows:
        conteo[row.get("categoria") or OPERATIVO] += 1
    return conteo