"""Lineas del extracto de ICBC de muestra, con los identificadores saneados.

Por que existe: el repo es publico y un extracto real lleva CBU, CUIT y los
movimientos de la empresa. Este fixture reproduce la ESTRUCTURA del PDF real de
ICBC (que es el mismo layout del portal "reportes" que usa Santander) pero con
importes inventados, asi que el repo no publica movimientos reales y los tests
igual pueden afirmar sobre el cierre.

Lo que este fixture reproduce, y que es lo que hacia fallar al parser:

1. La fecha es dd-mm SIN ANIO. El ano solo esta en el encabezado
   ("PERIODO 01-07-2026 AL 31-07-2026"). Sin resolverlo, el procesador central
   no parsea ninguna fecha y el extracto entero se pierde.
2. El codigo de comprobante (0501) esta pegado al concepto y parece un numero.
   El parser viejo de ICBC lo tomaba por importe.
3. Los codigos de ORIGEN y CANAL (FOND, DNET, BS, CREDIN) y los numeros de
   comprobante de 4 digitos (0187, 0109) tambien se parecen a importes.
4. El signo va pegado al final del numero ("40.000,00-") y la columna de
   creditos no trae signo.
5. Hay dos paginas: la segunda repite el encabezado de columnas y trae un
   "SALDO PAGINA ANTERIOR" que hay que saltear.
6. En la pagina 1 los movimientos vienen SIN saldo de linea y en la 2 CON
   saldo de linea. El parser tiene que bancar las dos formas.
7. El pie con "TOT.IMP.LEY COMP." y el "SALDO FINAL AL" que cierra la cuenta.

Los importes son inventados pero la cadena de saldos cierra exacto:
10.000.000,00 de apertura, 2.510.788,89 de DEBE, 3.462.302,60 de HABER,
10.951.513,71 de cierre.

Para cambiar el fixture se regenera con tests/generar_muestras.py.
"""

# 17 movimientos. DEBE = plata que sale, HABER = plata que entra.
MOVIMIENTOS = [
    # (fecha, concepto, debe, haber, saldo_de_linea)
    ("01-07", "MANTENIMIENTO DE CUENTA", "40.000,00-", None, None),
    ("01-07", "IMPUESTO AL VALOR AGREGADO", "8.400,00-", None, None),
    # El "2408" en el medio del concepto parece un numero y no lo es.
    ("01-07", "PERCEPCION IVA RG 2408", "1.200,00-", None, None),
    ("01-07", "ING BRUTOS PERCEP. C.A.B.A", None, "1.800,00", None),
    ("01-07", "R/RECAUDACION IB SIRCREB C", "20.879,38-", None, None),
    ("01-07", "IMP S/CRED EN CTA CTE", "15.659,54-", None, None),
    # Con ORIGEN y CANAL pegados al importe.
    ("01-07", "CRED RESC FCI 020A999999999", None, "2.000.000,00 FOND", None),
    # Esta linea trae el saldo de la fila, aunque estamos en la pagina 1.
    ("01-07", "DEBITO TRANSF CONNECTION B 0109239", "1.500.000,00- DNET", "10.415.661,08", None),
    ("02-07", "COM MPAY TRF ABIERTA INTER 01-07 COMMPAY TRF A 0543", "600,00-", None, None),
    ("02-07", "DEB SUSCR FCI 020A999999999", "500.000,00- FOND", "9.915.061,08", None),

    # --- Pagina 2 ---
    ("06-07", "R/RECAUDACION IB SIRCREB C", "31.858,82-", None, "9.883.202,26"),
    ("07-07", "IMP S/DEBITOS EN CTA CTE", "191,15-", None, "9.883.011,11"),
    # BS es un CANAL, no parte del importe.
    ("08-07", "DEBITO INMEDIATO2031224368 DBTO CREDIN", "100.000,00- BS", None, "9.783.011,11"),
    ("10-07", "CRED RESC FCI 020A999999999", None, "1.000.000,00 FOND", "10.783.011,11"),
    # Fecha valor distinta de la fecha de_imputacion, como en el PDF real.
    ("15-07", "IMPUESTO AL VALOR AGREGADO", "42.000,00-", None, "10.741.011,11"),
    ("20-07", "TR.9999999 A 0501/0103874 MTA9999999999", "250.000,00- DNET", None, "10.491.011,11"),
    ("31-07", "DEPOS. ECHEQ. NRO. : 99999 0000000155", None, "460.502,60 BS", "10.951.513,71"),
]

SALDO_INICIAL = "10.000.000,00"
SALDO_FINAL = "10.951.513,71"

PIE_PAGINA_1 = [
    " parasudeterminacionyperiodicidaddelcambioseencuentrandetalladosenlasolicituddeaperturasuscriptaoportuname",
    " efectivaanualeslaquefiguraenlanormativadelBCRAvigente(soloparaCuentaCorriente).",
    "(*)Importedecreditodeimpuestosusceptibledesercomputadocontraotrostributos,conarregloalonormadoenelart.13d",
    "IndustrialandCommercialBankofChina(Argentina)S.A.U.Florida99(C1005AAA)CiudadAutonomadeBuenosAires.",
    "C.U.I.T.N 30-00000000-0 I.V.A.ResponsableInscripto - I.B.C.M.N 000-0000000-0 F.EXTSTD V.001",
]

PIE_PAGINA_2 = [
    "_________________________________________________________________________________________________________",
    "TOT.IMP.LEY COMP.: 100.230,76 TOT.LEY COMP.$ 24.326,15(*) SALDO FINAL AL 31/07/2026 " + SALDO_FINAL,
    "F.EXTDOR V.001",
]

ENCABEZADO = [
    "EMPRESA DE PRUEBA SRL",
    "A V D A M A N U E L  D E  P R U E B A  0 0 0 0 0 0 0 R E S U M E N M E N S U A L",
    "1 0 9 2 - C A P I T A L  F E D E R A L PERIODO 01-07-2026 AL 31-07-2026",
    "C A P I T A L  F E D E R A L HOJA N 0001",
    "CUIT N 30-00000000-0",
    "IVA : INSCRIPTO",
    "SUCURSAL CENTRO",
    "INFORMACION SOBRE SU CUENTA CORRIENTE EN PESOS N 0501/00000000/00 C.B.U.: 01505016 00000000000000",
    "FECHA CONCEPTO F.VALOR COMPROBANTE ORIGEN CANAL DEBITOS CREDITOS SALDOS",
]

SALDO_ANTERIOR_PAGINA_2 = "9.915.061,08"


def _armar_linea(fecha, concepto, debe, haber, saldo_de_linea):
    """
    Reconstruye una linea del PDF. El formato es:

        DD-MM CONCEPTO [codigos] [importe con signo] [saldo]

    El importe va con el signo pegado si es DEBE, sin signo si es HABER. Los
    codigos de comprobante van siempre antes del importe.
    """
    partes = ["0501"]  # comprobante, siempre presente y siempre "numerico"
    if debe is not None:
        partes.append(debe)
    else:
        # Los HABER no traen signo; el separador " " lo agrega el layout real.
        partes.append(haber.replace(" ", " "))
    if saldo_de_linea is not None:
        partes.append(saldo_de_linea)
    return " ".join([f"{fecha} {concepto}"] + partes)


def _pagina_1():
    lineas = list(ENCABEZADO)
    lineas.append(f"SALDO ULTIMO EXTRACTO AL 30/06/2026 {SALDO_INICIAL}")
    for fecha, concepto, debe, haber, saldo in MOVIMIENTOS[:10]:
        lineas.append(_armar_linea(fecha, concepto, debe, haber, saldo))
    lineas.extend(PIE_PAGINA_1)
    return lineas


def _pagina_2():
    lineas = [ENCABEZADO[-1]]  # solo el encabezado de columnas se repite
    lineas.append(f"SALDO PAGINA ANTERIOR {SALDO_ANTERIOR_PAGINA_2}")
    for fecha, concepto, debe, haber, saldo in MOVIMIENTOS[10:]:
        lineas.append(_armar_linea(fecha, concepto, debe, haber, saldo))
    lineas.extend(PIE_PAGINA_2)
    return lineas


PAGINAS = [_pagina_1(), _pagina_2()]