"""
Extractor ICBC.

Los PDF de ICBC de este proyecto salen del portal "reportes", con este formato:

    RESUMEN MENSUAL
    1092-CAPITAL FEDERAL PERIODO 01-07-2026 AL 31-07-2026
    HOJA N° 0001
    INFORMACION SOBRE SU CUENTA CORRIENTE EN PESOS N° 0501/02139705/87
    FECHA CONCEPTO F.VALOR COMPROBANTE ORIGEN CANAL DEBITOS CREDITOS SALDOS
    SALDO ULTIMO EXTRACTO AL 30/06/2026 17.576.493,09
    01-07 MANTENIMIENTO DE CUENTA 0501 40.000,00-
    01-07 CRED RESC FCI 020A256323080 0501 FOND 2.500.000,00

Que es exactamente el mismo formato que parsea BcoSANT, asi que en vez de
mantener una segunda version de este parser acá (que nunca llego a funcionar
contra estos PDF:tomaba el codigo de sucursal 0501 por importe y devolvia
cifras de un billon), ICBC delega en el parser del portal.

Dos PDF reales de ICBC, de empresas distintas y con 2 y 4 paginas, leen bien
con esa delegacion: 90 y 133 movimientos y descuadre 0,00.

Si ICBC alguna vez manda otro layout, este archivo tiene que volver a tener su
propio extractor. El punto de entrada no cambia: BANCOS["ICBC"].
"""

import pandas as pd

from app.services.Tools import guardar_excel
from app.services.bancos.BcoSANT import extraer_santander_rio


def extraer_icbc(pdf_path, excel_path, log_callback):
    """ICBC usa el mismo layout del portal que SANT, asi que reutiliza ese parser."""
    log_callback("Extrayendo PDF del BANCO ICBC (formato portal)...")
    return extraer_santander_rio(pdf_path, excel_path, log_callback)


def generar_excel_icbc(filas, excel_path, log_callback):
    """
    Escritor canonico para el shape DEBE/HABER. El extractor de arriba ya
    escribe con el generico del portal; este queda para cuando se cargue una
    tabla de a mano o en un test.
    """
    if not filas:
        return False, "No se encontraron movimientos ICBC."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    df = df[["FECHA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]]
    df.rename(columns={"SALDO_CALC": "SALDO"}, inplace=True)

    # pandas 3 no deja escribir un string dentro de una columna float64.
    # Sin este cast, el df.at[] de la formula de abajo revienta con TypeError.
    df["SALDO"] = df["SALDO"].astype(object)

    for i in range(len(df)):
        fila_excel_actual = i + 2
        if df.at[i, "FECHA"] == "INICIO":
            df.at[i, "FECHA"] = ""
            continue
        else:
            fila_excel_anterior = fila_excel_actual - 1
            # El DEBE es plata que sale de la cuenta y el HABER plata que entra,
            # con las dos columnas en positivo: =SaldoAnterior - Debe + Haber.
            formula = f"=E{fila_excel_anterior}-C{fila_excel_actual}+D{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)