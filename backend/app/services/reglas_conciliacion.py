"""Reglas de negocio para las partidas que NO encontraron coincidencia (FO 02-03).

Por que existe
--------------
El conciliador deja dos bandejas de "sin coincidencia": lo que esta en el
extracto del banco pero no en la contabilidad, y lo que esta en la contabilidad
pero no en el extracto. Antes, esa clasificacion vivia mezclada entre
`conciliador_avanzado.py` (que separaba gastos del banco del resto) y
`asientos_ajuste.py` (que armaba el asiento). Este modulo concentra las reglas
de negocio en un solo lugar, para que el cruce, el generador de asientos y la
pantalla de revision usen exactamente el mismo criterio.

Que decide
----------
Para cada partida sin par devuelve un `tipo` (que es), una `accion` (que hacer) y,
cuando corresponde, la contracuenta del asiento. Las reglas son las del pedido:

A. Esta en el extracto pero falta en contabilidad -> asiento de ajuste:

   - GASTO BANCARIO (comision, mantenimiento, chequera, IVA, intereses):
     Debe <gasto> / Haber Banco. Automatico.
   - RETENCION / IMPUESTO (SIRCREB, retencion IIBB, impuesto ley 25.413
     "Deb/Cred", sellado): Debe <impuesto/retencion> / Haber Banco. Automatico.
     Ojo: "IMP S/CRED" es un credito del extracto pero sigue siendo un impuesto,
     por eso se prueba ANTES que el signo del movimiento.
   - INGRESO / TRANSFERENCIA NO REGISTRADA (acreditacion sin comprobante interno):
     NO se genera asiento automatico. Se marca para revision visual, porque la
     contracuenta es la cuenta del cliente y la elige una persona.
   - DEBITO AUTOMATICO (pago directo no contabilizado que no es gasto ni
     impuesto): asiento con la cuenta de conciliacion de banco, marcado para
     revisar la contracuenta.

B. Esta en contabilidad pero falta en el extracto -> NO se genera asiento. Se
   marca como "Pendiente de Conciliacion (Diferencia Temporal)" y se conserva
   para el periodo siguiente (cheques diferidos en transito, depositos
   pendientes de acreditacion).

El modulo no descarta nada ni cambia importes: solo etiqueta y decide si
corresponde asiento. La decision final la confirma una persona en la pantalla de
revision antes de inyectar nada en Xubio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.services.clasificacion import _normalizar, _subcategoria_gasto

# ----------------------------------------------------------------------
# Tipos (que es la partida)
# ----------------------------------------------------------------------

TIPO_GASTO_BANCARIO = "gasto_bancario"
TIPO_RETENCION_IMPUESTO = "retencion_impuesto"
TIPO_INGRESO_NO_REGISTRADO = "ingreso_no_registrado"
TIPO_DEBITO_AUTOMATICO = "debito_automatico"
TIPO_PENDIENTE_TEMPORAL = "pendiente_temporal"

ETIQUETAS_TIPO = {
    TIPO_GASTO_BANCARIO: "Gasto bancario",
    TIPO_RETENCION_IMPUESTO: "Retencion / impuesto",
    TIPO_INGRESO_NO_REGISTRADO: "Ingreso / transferencia no registrada",
    TIPO_DEBITO_AUTOMATICO: "Debito automatico",
    TIPO_PENDIENTE_TEMPORAL: "Pendiente de conciliacion (diferencia temporal)",
}

# ----------------------------------------------------------------------
# Acciones (que hacer)
# ----------------------------------------------------------------------

ACCION_ASIENTO = "asiento"      # generar asiento de ajuste
ACCION_REVISAR = "revisar"      # marcar para revision, sin asiento automatico
ACCION_PENDIENTE = "pendiente"  # partida temporal, sin asiento

# Claves logicas de contracuenta: `asientos_ajuste.py` las resuelve contra el
# plan de cuentas de la config (settings.CUENTA_*).
CONTRACUENTA_GASTOS = "gastos_bancarios"
CONTRACUENTA_RETENCIONES = "retenciones_impuestos"
CONTRACUENTA_CONCILIACION_BANCO = "conciliacion_banco"

# ----------------------------------------------------------------------
# Patrones
# ----------------------------------------------------------------------
#
# El orden de prueba importa: retenciones e impuestos primero, porque
# "IMP S/CRED" o "IMPUESTO LEY 25413" tambien caerian por el generico
# "IMPUESTO" de los gastos. La etiqueta mas especifica gana.
RE_RETENCION_IMPUESTO = re.compile(
    r"SIRCREB"
    r"|RETENCION"
    r"|PERCEP"
    r"|RECAUDACION"
    r"|LEY\s*25\.?413"                     # impuesto a los debitos y creditos
    r"|IMP\s*S\s*/\s*(?:DEB|CRED)"         # IMP S/DEB CT, IMP S/CRED CT
    r"|IMPUESTO\s+SOBRE\s+DEBITOS"
    r"|SELLAD"                             # SELLADO, SELLADOS
)

RE_GASTO_BANCARIO = re.compile(
    r"\bCOM\b"          # COM GEST CLICK, COM MANT CT, COM MPAY
    r"|COMISION"
    r"|MANTENIMIENTO"
    r"|CHEQUERA"
    r"|DEB\s*LIQ\s*INTER"
    r"|INTERES"
    r"|\bIVA\b"         # IVA REDUCIDA
    r"|I\s*V\s*A\b"     # la variante espaciada "I V A"
    r"|IMPUESTO"        # IMPUESTO AL VALOR AGREGADO
)


@dataclass(frozen=True)
class ClasificacionSinCoincidencia:
    """Resultado de aplicar las reglas a una partida sin par."""

    tipo: str
    accion: str
    # Etiqueta humana: la subcategoria del gasto (Comisiones, IVA, ...) cuando
    # existe, o una descripcion del tipo. Es tambien el nombre de la
    # contracuenta cuando `accion == asiento`.
    regla: str
    revisar_manual: bool = False
    # Clave logica de la contracuenta (ver CONTRACUENTA_*); None si no hay
    # asiento automatico.
    contracuenta: Optional[str] = None

    @property
    def requiere_asiento(self) -> bool:
        return self.accion == ACCION_ASIENTO

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS_TIPO.get(self.tipo, self.tipo)


def clasificar_sin_coincidencia(
    origen: str,
    concepto: str,
    entra: bool,
) -> ClasificacionSinCoincidencia:
    """Aplica las reglas de negocio a una partida sin coincidencia.

    Args:
        origen: "banco" (esta en el extracto) o "mayor" (esta en contabilidad).
        concepto: el concepto tal como viene del extracto o del mayor.
        entra: True si el movimiento es una entrada de plata al banco.
    """
    if origen == "mayor":
        # B: en contabilidad pero no en el banco -> diferencia temporal, sin
        # asiento. Se conserva para el periodo siguiente.
        return ClasificacionSinCoincidencia(
            tipo=TIPO_PENDIENTE_TEMPORAL,
            accion=ACCION_PENDIENTE,
            regla="Diferencia temporal",
            revisar_manual=False,
            contracuenta=None,
        )

    texto = _normalizar(concepto)
    subcategoria = _subcategoria_gasto(concepto)

    if RE_RETENCION_IMPUESTO.search(texto):
        return ClasificacionSinCoincidencia(
            tipo=TIPO_RETENCION_IMPUESTO,
            accion=ACCION_ASIENTO,
            regla=subcategoria or settings.CUENTA_RETENCIONES,
            revisar_manual=False,
            contracuenta=CONTRACUENTA_RETENCIONES,
        )

    if RE_GASTO_BANCARIO.search(texto):
        return ClasificacionSinCoincidencia(
            tipo=TIPO_GASTO_BANCARIO,
            accion=ACCION_ASIENTO,
            regla=subcategoria or settings.CUENTA_GASTOS_BANCARIOS,
            revisar_manual=False,
            contracuenta=CONTRACUENTA_GASTOS,
        )

    if entra:
        # Acreditacion comercial sin comprobante: la contracuenta es la cuenta
        # del cliente y la asigna una persona. No se genera asiento automatico.
        return ClasificacionSinCoincidencia(
            tipo=TIPO_INGRESO_NO_REGISTRADO,
            accion=ACCION_REVISAR,
            regla="Ingreso / transferencia no registrada",
            revisar_manual=True,
            contracuenta=None,
        )

    # Debito que no es gasto ni impuesto del banco: pago directo no
    # contabilizado. Se propone asiento contra la cuenta de conciliacion de
    # banco, marcado para revisar la contracuenta real.
    return ClasificacionSinCoincidencia(
        tipo=TIPO_DEBITO_AUTOMATICO,
        accion=ACCION_ASIENTO,
        regla="Debito automatico",
        revisar_manual=True,
        contracuenta=CONTRACUENTA_CONCILIACION_BANCO,
    )
