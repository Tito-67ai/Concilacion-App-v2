import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, guardar_excel


def _debe_haber(valor_movimiento, es_office_banking, linea_raw=""):
    """
    Decide DEBE/HABER de un movimiento de Galicia.

    El contrato del proyecto es DEBE = plata que SALE y HABER = plata que ENTRA
    (ver test_la_convencion_de_debe_y_haber_no_se_puede_invertir). En el reporte
    tradicional el importe ya trae el signo: positivo es un credito (entra),
    negativo un debito (sale). En Office Banking el banco imprime el signo
    suelto en la linea: "+" entra y "-" sale.

    Devolvia el signo al reves desde que se importo el parser (positivo -> DEBE),
    asi que un extracto real de Galicia descuadraba 885 de 886 filas: el saldo
    arrancaba derivado desde la primera linea.
    """
    if es_office_banking:
        if "+" in linea_raw:
            return 0.0, abs(valor_movimiento)
        if "-" in linea_raw:
            return abs(valor_movimiento), 0.0
        # Sin signo explicito en la linea: decide el propio importe.
        return (0.0, valor_movimiento) if valor_movimiento >= 0 else (abs(valor_movimiento), 0.0)

    if valor_movimiento >= 0:
        return 0.0, valor_movimiento
    return abs(valor_movimiento), 0.0


def extraer_galicia(pdf_path, excel_path, log_callback):
    """
    Motor Galicia V6 (Híbrido - Detecta Office Banking):
    - Detecta si es el reporte "OFFICE BANKING" o el "Tradicional".
    - Office Banking: Se guía por los signos explícitos '+' y '-' en la línea.
    - Tradicional: Se guía por números positivos (Haber) vs negativos (Debe).
    - Mantiene la lógica de corte de página de la V5.
    """
    try:
        filas_data = []
        transaccion_actual = None 
        fin_del_extracto = False 
        
        # Flags de formato
        es_office_banking = False
        formato_detectado = False

        # Frases de corte de hoja
        frases_fin_pagina = ["RESUMEN", "PÁGINA", "PAGINA", "HOJA NRO", "FECHA DE DESCARGA"]

        log_callback("🟠 Extrayendo pdf del BANCO GALICIA")

        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                if fin_del_extracto: break 
                
                log_callback(f"Leyendo página {i+1} de {total_pags}...")
                
                texto_pagina = pagina.extract_text()
                if not texto_pagina: continue

                # --- 1. DETECCIÓN DE FORMATO (Solo en la primera página que leemos) ---
                if not formato_detectado:
                    if "OFFICE BANKING" in texto_pagina.upper():
                        es_office_banking = True
                        log_callback("   🔎 Formato detectado: OFFICE BANKING (Signos +/-)")
                    else:
                        es_office_banking = False
                        log_callback("   🔎 Formato detectado: TRADICIONAL (Positivo/Negativo)")
                    formato_detectado = True
                # ---------------------------------------------------------------------

                leyendo_cuerpo = False 
                lineas = texto_pagina.split('\n')

                for linea in lineas:
                    linea_limpia = linea.strip()
                    linea_upper = linea_limpia.upper()
                    if not linea_limpia: continue
                    
                    partes = linea_limpia.split()

                    # DETECCIÓN DE TOTAL (FIN)
                    if "TOTAL" in linea_upper:
                        numeros = [p for p in partes if es_numero_bancario(p)]
                        if len(numeros) >= 2 and not re.match(r'\d{2}/\d{2}', partes[0]):
                            log_callback("⏹️ Fin del extracto detectado (TOTAL).")
                            if transaccion_actual: filas_data.append(transaccion_actual)
                            fin_del_extracto = True
                            break 

                    # DETECCIÓN DE FECHA (INICIO DE TRANSACCIÓN)
                    es_fecha = re.match(r'\d{2}/\d{2}/\d{2,4}', partes[0])

                    if es_fecha:
                        leyendo_cuerpo = True
                        if transaccion_actual: filas_data.append(transaccion_actual)

                        fecha = partes[0]
                        indices_numeros = [idx for idx, p in enumerate(partes) if es_numero_bancario(p)]
                        
                        if len(indices_numeros) < 2: # Necesitamos al menos Movimiento y Saldo
                            transaccion_actual = None
                            continue
                        
                        idx_saldo = indices_numeros[-1]       
                        idx_movimiento = indices_numeros[-2] 
                        
                        str_saldo = partes[idx_saldo]
                        str_movimiento = partes[idx_movimiento]
                        
                        descripcion = " ".join(partes[1:idx_movimiento])
                        
                        valor_movimiento = limpiar_numero(str_movimiento)
                        valor_saldo = limpiar_numero(str_saldo) 

                        # --- LÓGICA CORE: DECISIÓN DEBE vs HABER ---
                        linea_raw = " ".join(partes)
                        debe, haber = _debe_haber(
                            valor_movimiento, es_office_banking, linea_raw
                        )

                        transaccion_actual = {
                            "FECHA": fecha,
                            "DETALLE": descripcion, 
                            "DEBE": debe, "HABER": haber, "SALDO": valor_saldo 
                        }
                        continue 

                    # VERIFICACIÓN DE FIN DE PÁGINA
                    if leyendo_cuerpo:
                        frase_corte = next((f for f in frases_fin_pagina if f in linea_upper), None)
                        if frase_corte:
                            if transaccion_actual: 
                                filas_data.append(transaccion_actual)
                                transaccion_actual = None
                            break 

                    # CONTINUACIÓN DE TEXTO
                    if leyendo_cuerpo and transaccion_actual is not None:
                        if "HOJA" not in linea_upper and "SALDO" not in linea_upper:
                            transaccion_actual["DETALLE"] += " " + linea_limpia

        if not fin_del_extracto and transaccion_actual:
            filas_data.append(transaccion_actual)

        return generar_excel_galicia(filas_data, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Galicia: {str(e)}"

def generar_excel_galicia(filas_data, excel_path, log_callback):
    if not filas_data:
        return False, "No se encontraron movimientos válidos en Galicia."

    log_callback(f"Procesando {len(filas_data)} movimientos...")

    # OJO: antes se metia una fila de plantilla con SALDO="XXX" para que una
    # persona completara el saldo inicial a mano y despues se pisaba la columna
    # SALDO con formulas de Excel. Eso hacia dos cosas malas: la fila "XXX"
    # salia despues como un movimiento falso en la respuesta, y el valor_saldo
    # que el extractor si leyo de cada linea del PDF se tiraba a la basura.
    # Como el archivo se borra al terminar y nadie lo abre, no hay nada que
    # completar a mano: se respeta el saldo que trajo cada fila.
    df = pd.DataFrame(filas_data)
    df = df[["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"]]

    # pandas 3 no deja escribir un string dentro de una columna float64.
    # Sin este cast, el df.at[] de la formula de abajo revienta con TypeError.
    df["SALDO"] = df["SALDO"].astype(object)

    return guardar_excel(df, excel_path)
