"""
Extractor Santander / BcoRio formato "extractos mensuales de cuenta".

Este PDF no es el Santander clasico (fechas con dd/mm/aaaa y saldo en columna
fija). Viene del portal "reportes":

    FECHA CONCEPTO F.VALOR COMPROBANTE ORIGEN CANAL DEBITOS CREDITOS SALDOS
    SALDO PAGINA ANTERIOR 1.187.851,65
    08-07 IMP S/DEBITOS EN CTA CTE 0543 4,36-
    08-07 CRED RESC FCI 020A256323080 0501 FOND 2.500.000,00
    08-07 CREDITO POR RESCATE FCI 020A256323080 0543 0,24 13.301.504,18

Tres cosas que rompen un parser general:

1. La fecha es dd-mm, sin año. El año sale del encabezado ("PERIODO 01-07-2026
   AL 31-07-2026").
2. Los codigos de comprobante/origen/canal (0543, 0501, 0187, BS, DNET, FOND)
   se parece a un numero y el parser general se los come como importe.
3. El signo va pegado al final del numero ("4,36-") y la columna de creditos no
   trae signo. Hay que deducir la direccion del saldo de la linea.
"""

import os
import re
import sys

import pandas as pd
import pdfplumber

carpeta_padre = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(carpeta_padre)

from Tools import TrackerSaldo, guardar_excel, limpiar_numero

# dd-mm al comienzo de la linea
RE_FECHA = re.compile(r"^(\d{2})-(\d{2})\b")

# 01-07-2026 AL 31-07-2026  -> 2026
RE_PERIODO = re.compile(r"PERIODO\s+(\d{2})-(\d{2})-(\d{4})", re.IGNORECASE)
RE_PERIODO_BARRA = re.compile(r"PER[IÍ]ODO\s+(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE)

# Numero con miles y/o decimales: 1.234.567,89 | 4,36 | 1.500.000,00
RE_IMPORTE = re.compile(r"\d{1,3}(?:[.\s]\d{3})*,\d{2}|\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2}")

# Tokens que el banco pone en columnas de texto y que se parecen a un numero
CODIGOS_TEXTO = {
    "DNET", "FOND", "DBTO", "CREDIN", "BS", "CS", "CA", "ABIERTA",
    "INTER", "COMMPAY", "MPF", "TRF", "TR", "OELE", "LINK",
}

RE_BASURA = re.compile(
    r"^(FECHA\s+CONCEPTO|CUIT|IVA\s*:|SUCURSAL|CAPITAL\s+FEDERAL|INFORMACION|"
    r"PAGINA|HOJA\s+N|CBU|CONCEPTO\s+F\.VALOR|Este\s+resumen|Emitido|Generado|"
    r"Banco\s+Santander|SANTANDER|RESUMEN\s+TOTAL|TOTAL)",
    re.IGNORECASE,
)

RE_SALDO_ARRANQUE = re.compile(
    r"^SALDO\s+(PAGINA\s+ANTERIOR|INICIAL|ANTERIOR|ULTIMO|ULT\s+EXTRACTO|A\s+LA\s+FECHA)",
    re.IGNORECASE,
)


def _anio_del_documento(texto):
    m = RE_PERIODO.search(texto) or RE_PERIODO_BARRA.search(texto)
    if m:
        return int(m.group(3))
    m = re.search(r"\b(20\d{2})\b", texto)
    return int(m.group(1)) if m else None


def _importes_de_linea(partes):
    """
    Devuelve [(indice, valor, negativo)] de los tokens que son importes.

    Filtra los codigos de 4 digitos sin separador (0543, 0501) y las palabras
    sueltas que el banco usa como canal/origen.
    """
    encontrados = []
    for i, token in enumerate(partes):
        limpio = token.strip().strip(",")

        # El signo va pegado al final en este PDF: "4,36-"
        negativo = limpio.endswith("-")
        if negativo:
            limpio = limpio[:-1]

        # Codigos de columna: 3 o 4 digitos sin separador decimal
        if RE_IMPORTE.fullmatch(limpio):
            pass
        elif re.fullmatch(r"\d{3,4}", limpio):
            # 0543, 0501, 0187 son comprobante/origen/canal, no importes
            continue
        else:
            continue

        valor = limpiar_numero(limpio)
        if valor:
            encontrados.append((i, valor, negativo))

    return encontrados


def extraer_santander_rio(pdf_path, excel_path, log_callback):
    try:
        log_callback("Extrayendo PDF del BANCO SANTANDER (formato portal)")

        filas = []
        saldo_inicial = None

        with pdfplumber.open(pdf_path) as pdf:
            texto_completo = "\n".join(
                (p.extract_text() or "") for p in pdf.pages
            )
            anio = _anio_del_documento(texto_completo)
            if not anio:
                return (
                    False,
                    "No se encontro el periodo del extracto, asi que no se puede "
                    "saber el ano de las fechas (van como dd-mm).",
                )
            log_callback(f"Periodo del extracto: ano {anio}")

            for i, pagina in enumerate(pdf.pages):
                texto = pagina.extract_text() or ""
                for linea in texto.splitlines():
                    limpia = linea.strip()
                    if not limpia or RE_BASURA.match(limpia):
                        continue

                    m_saldo = RE_SALDO_ARRANQUE.match(limpia)
                    if m_saldo:
                        importes = _importes_de_linea(limpia.split())
                        if importes:
                            # El saldo de cada pagina es el mismo cuenta. Solo
                            # nos interesa el de la primera pagina (saldo inicial).
                            if i == 0:
                                saldo_inicial = importes[-1][1]
                                log_callback(
                                    f"  Saldo de partida: {saldo_inicial:,.2f}"
                                )
                        continue

                    m_fecha = RE_FECHA.match(limpia)
                    if not m_fecha:
                        continue

                    dia, mes = int(m_fecha.group(1)), int(m_fecha.group(2))
                    fecha = f"{dia:02d}-{mes:02d}-{anio}"

                    partes = limpia.split()
                    importes = _importes_de_linea(partes)
                    if not importes:
                        continue

                    # El concepto es todo lo que hay antes del primer importe,
                    # menos la fecha y menos los codigos sueltos de 4 digitos.
                    primero = importes[0][0]
                    concepto = " ".join(partes[1:primero])
                    concepto = re.sub(
                        r"\b\d{3,4}\b(?=\s+(DNET|FOND|DBTO|CREDIN|BS|CS|OELE)\b)?",
                        lambda mm: "",
                        concepto,
                    )
                    concepto = re.sub(r"\s{2,}", " ", concepto).strip(" -")
                    if not concepto:
                        concepto = "Sin concepto"

                    filas.append(
                        {
                            "FECHA": fecha,
                            "DETALLE": concepto,
                            "IMPORTE": importes,
                        }
                    )

        if not filas:
            return (
                False,
                "No se encontraron movimientos con formato de fecha dd-mm. "
                "Este PDF puede ser de otro banco.",
            )

        log_callback(f"{len(filas)} filas con fecha e importes")

        # La ultima columna es el saldo de la linea: sirve para decidir la
        # direccion del movimiento y para llevar el saldo ourselves.
        df = _armar_filas(filas, saldo_inicial)

        columnas = ["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"]
        df = df[columnas]
        df["SALDO"] = df["SALDO"].astype(object)

        return guardar_excel(df, excel_path)

    except Exception as e:
        import traceback

        traceback.print_exc()
        return False, f"Error Santander portal: {e}"


def _armar_filas(filas, saldo_inicial):
    """
    Convierte la lista de filas crudas en el Excel canonico.

    Determina DEBE/HABER con la cadena de saldos: en este PDF el signo del
    debito va pegado al numero, pero el credito no trae nada, asi que sin
    contrastar contra el saldo no se puede saber si el numero es entrada o
    salida.
    """
    registros = []
    tracker = TrackerSaldo()
    saldo_actual = saldo_inicial or 0.0

    for fila in filas:
        importes = fila["IMPORTE"]
        concepto = fila["DETALLE"]

        # Con dos numeros: el primero es el movimiento y el segundo el saldo.
        # Con uno: solo el movimiento, el saldo no viene.
        if len(importes) >= 2:
            (_, importe, negativo), (_, saldo_linea, _) = importes[0], importes[-1]
        else:
            importe = importes[0][1]
            negativo = importes[0][2]
            saldo_linea = None

        if tracker.iniciado and saldo_linea is not None:
            direccion = tracker.identificar_movimiento(importe, saldo_linea)
        else:
            # Primera fila, o fila sin saldo impreso: usamos el signo si vino.
            direccion = "DEBE" if negativo else "HABER"

        if direccion is None:
            direccion = "DEBE" if negativo else "HABER"

        if direccion == "DEBE":
            debe, haber = importe, 0.0
            saldo_actual = saldo_actual - importe
        else:
            debe, haber = 0.0, importe
            saldo_actual = saldo_actual + importe

        # Si el banco imprimio el saldo de la linea, ese manda: es la verdad.
        if saldo_linea is not None:
            saldo_actual = saldo_linea

        tracker.iniciar(saldo_actual)

        registros.append(
            {
                "FECHA": fila["FECHA"],
                "DETALLE": concepto,
                "DEBE": debe,
                "HABER": haber,
                "SALDO": saldo_actual,
            }
        )

    return pd.DataFrame(registros)