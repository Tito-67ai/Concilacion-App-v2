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


# Gastos y cargos propios del banco (lo que el extracto debita sin que la
# empresa haya emitido una operacion): comisiones, mantenimiento, intereses,
# IVA, impuestos y sellados. Es lo que el spec del FO 02-03 llama "partidas de
# debito automatico" y lo que va a la Seccion 3 del Libro Mayor.
#
# La funcion que sigue reusa la clasificacion de percepciones e impuestos. Este
# patron cubre lo que ese clasificador no ve:
#   - comisiones e intereses, que quedan como operativos porque no son ni una
#     retencion ni un impuesto;
#   - el IVA suelto ("I V A", "IVA REDUCIDA"), que RE_IMPUESTO no mira;
#   - "IMP S/DEB CT" y "IMP S/CRED CT", la forma abreviada que manda el
#     extracto real (RE_IMPUESTO pide "DEBITOS"/"CRED" completos);
#   - "IMPUESTO LEY 25413", el impuesto a los debitos bancarios.
#
# "ING BRUTOS" suelta no se agrega a proposito: los conceptos reales traen
# "PERCEP" y el patron suelto marcaria un traspaso a una empresa como gasto.
RE_GASTO_BANCARIO = re.compile(
    r"\bCOM\b"  # COM GEST CLICK, COM MANT CT, COM MPAY, COM B@C
    r"|COMISION"
    r"|MANTENIMIENTO"
    r"|DEB\s*LIQ\s*INTER"  # intereses por liquidacion
    r"|INTERES"
    r"|\bIVA\b"  # IVA REDUCIDA
    r"|I\s*V\s*A\b"  # la variante espaciada "I V A"
    r"|IMPUESTO"  # IMPUESTO AL VALOR AGREGADO, IMPUESTO LEY 25413
    r"|IMP\s*S\s*/\s*(?:DEB|CRED)"  # IMP S/DEB CT, IMP S/CRED CT
    r"|SELLAD"  # SELLADO, SELLADOS
)


def es_gasto_bancario(concepto: str) -> bool:
    """True si el concepto es un gasto/cargo del banco (debito automatico).

    Reusa la clasificacion de percepciones e impuestos y le suma las comisiones,
    los intereses y el IVA suelto, que el clasificador de tres categorias deja
    como operativos porque no son ni una retencion ni un impuesto tipico.
    """
    if clasificar(concepto) in NO_OPERATIVAS:
        return True
    return bool(RE_GASTO_BANCARIO.search(_normalizar(concepto)))


def resumir_categorias(rows) -> dict:
    """Cuenta movimientos por categoria. Para el resumen de la respuesta."""
    conteo = {OPERATIVO: 0, PERCEPCION: 0, IMPUESTO: 0}
    for row in rows:
        conteo[row.get("categoria") or OPERATIVO] += 1
    return conteo