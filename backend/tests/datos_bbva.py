"""Lineas del extracto de BBVA de muestra, con los identificadores saneados.

Por que existe: el repo es publico y un extracto real lleva CBU, CUIT y los
movimientos de la empresa. Este fixture reproduce la ESTRUCTURA del PDF real de
BBVA pero con importes inventados, asi que el repo no publica movimientos reales
y los tests igual pueden afirmar sobre el cierre.

Lo que este fixture reproduce, y que es lo que hacia fallar al parser:

1. La fecha del movimiento va dd/mm SIN ANIO ("01/07"). El ano solo esta en la
   linea de PERIODO del regimen SIRCREB ("PERIODO 01/07/2026 AL 31/07/2026").
   Sin resolverlo, el procesador central no parsea ninguna fecha y descarta el
   extracto entero.
2. El signo: BBVA imprime el DEBITO en NEGATIVO y el CREDITO en POSITIVO. El
   parser viejo lo leia al reves, asi que toda la cuenta quedaba invertida.
3. La columna ORIGEN puede traer "D"/"C", un codigo ("574") o la fecha de
   origen completa ("30/06/26"): ninguno de esos numeros es un importe.
4. Las cuentas sin actividad traen una fila "00/00 SIN MOVIMIENTOS" que no es un
   movimiento.
5. Despues del ultimo "TOTAL MOVIMIENTOS" el banco imprime un anexo de
   transferencias ("TR. E/CTAS.") que NO son movimientos de la cuenta.

Los importes son inventados pero la cadena de saldos cierra exacto:
100.000,00 de apertura, 17.000,00 de DEBE, 70.000,00 de HABER, 153.000,00 de
cierre.

Para cambiar el fixture se regenera con tests/generar_muestras.py.
"""

# 6 movimientos. DEBE = plata que sale (negativo), HABER = plata que entra.
MOVIMIENTOS_PAGINA_1 = [
    # El "01/07/26" y el "00002" son ORIGEN y comprobante, no importes.
    "01/07 IMP.LEY 25413 01/07/26 00002 -5.000,00 95.000,00",
    "02/07 D COM MANT MENS PROYE 06/26 -3.000,00 92.000,00",
    # Con "D" y un codigo de comprobante pegado al concepto.
    "03/07 D 574 COBRO DE PROVEEDORES CR MIN000033995 20.000,00 112.000,00",
]

MOVIMIENTOS_PAGINA_2 = [
    # La columna ORIGEN puede quedar vacia: el concepto arranca con cifras.
    "05/07 D 500 TRANSFERENCIA CCP001 022602 7 -8.000,00 104.000,00",
    "10/07 LEY NRO 25.413 SOBRE CREDIT -1.000,00 103.000,00",
    "15/07 D 500 TRANSFERENCIA CCP001 010101 9 50.000,00 153.000,00",
]

ENCABEZADO = [
    "1/1 0072441 1",
    "EMPRESA DE PRUEBA SRL",
    "PERIODO 01/07/2026 AL 31/07/2026 TOTAL DEL IMPORTE DEBITADO. 17.000,00",
    "Cuenta Pyme Persona Juridica CONSOLIDADO",
    "CC $ 025-014236/1 (Cta.Cte.Bancaria)",
    "FECHA ORIGEN CONCEPTO DEBITO CREDITO SALDO",
    "SALDO ANTERIOR 100.000,00",
]

COLA_PAGINA_2 = [
    "FECHA ORIGEN CONCEPTO DEBITO CREDITO SALDO",
    "SALDO AL 31 DE JULIO 153.000,00",
    "TOTAL MOVIMIENTOS -17.000,00 70.000,00",
    # Segunda cuenta, sin actividad: la fila "00/00 SIN MOVIMIENTOS" no es un
    # movimiento y antes se colaba como una fila en cero.
    "CC $ 025-014237/8 (Cta.Cte.Bancaria)",
    "SALDO ANTERIOR 0,00",
    "00/00 SIN MOVIMIENTOS 0,00",
    "SALDO AL 31 DE JULIO 0,00",
    "TOTAL MOVIMIENTOS 0,00 0,00",
    # Anexo posterior: no son movimientos de la cuenta.
    "Transferencias",
    "RECIBIDAS",
    "03/08 015 99999999999M EMPRESA DE PRUEBA TR. E/CTAS.OTROS B VARIOS 0106918 0106918 $ 3.700.000,00 CC $ 025-014236/1",
]

PAGINAS = [
    ENCABEZADO + MOVIMIENTOS_PAGINA_1,
    MOVIMIENTOS_PAGINA_2 + COLA_PAGINA_2,
]

SALDO_INICIAL = "100.000,00"
SALDO_FINAL = "153.000,00"
DEBE_TOTAL = 17000.00
HABER_TOTAL = 70000.00
