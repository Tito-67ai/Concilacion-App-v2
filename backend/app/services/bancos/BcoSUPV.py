import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, TrackerSaldo, guardar_excel

def extraer_supervielle(pdf_path, excel_path, log_callback):
    """
    Motor Banco Supervielle V2:
    - Corrección del error NameError: 'str_monto' is not defined.
    - Soporta múltiples cuentas en un mismo PDF.
    - Identifica DÉBITO/CRÉDITO mediante cálculo matemático (TrackerSaldo).
    - Lee signos negativos a la derecha (Ej: 1.058,29-).
    """
    try:
        todas_las_filas = []
        cuenta_actual = "Desconocida"
        transaccion_actual = None
        
        # Nuestro rastreador matemático
        tracker = TrackerSaldo()
        
        # Banderas de estado
        buscando_movimientos = False
        fin_del_extracto = False
        
        log_callback("🟢 Extrayendo pdf del BANCO SUPERVIELLE...")

        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                if fin_del_extracto: break
                
                log_callback(f"Leyendo página {i+1} de {total_pags}...")
                texto_pagina = pagina.extract_text()
                if not texto_pagina: continue

                lineas = texto_pagina.split('\n')

                for linea in lineas:
                    linea_limpia = linea.strip()
                    linea_upper = linea_limpia.upper()
                    
                    if not linea_limpia: continue

                    # --- 1. DETECCIÓN DE PIE DE PÁGINA ---
                    if linea_upper.startswith("IMPORTANTE:"):
                        log_callback("   ✂️ Pie de página detectado. Saltando a siguiente hoja.")
                        if transaccion_actual is not None:
                            todas_las_filas.append(transaccion_actual)
                            transaccion_actual = None
                        break 

                    # --- 2. DETECCIÓN DE FIN DE DOCUMENTO ---
                    if "**********" in linea_limpia:
                        log_callback("⏹️ Fin absoluto del extracto detectado (Asteriscos).")
                        fin_del_extracto = True
                        break

                    partes = linea_limpia.split()

                    # --- 3. DETECCIÓN DE CUENTA NUEVA ---
                    if "NUMERO DE CUENTA" in linea_upper:
                        try:
                            cuenta_actual = linea_upper.split("NUMERO DE CUENTA")[1].strip().split()[0]
                            log_callback(f"   🏦 Nueva cuenta detectada: {cuenta_actual}")
                        except:
                            pass
                        continue

                    # --- 4. INICIO Y FIN DE BLOQUE DE MOVIMIENTOS ---
                    if "DETALLE DE MOVIMIENTOS" in linea_upper:
                        buscando_movimientos = True
                        continue
                        
                    if "SALDO PERIODO ACTUAL" in linea_upper:
                        if transaccion_actual is not None:
                            todas_las_filas.append(transaccion_actual)
                            transaccion_actual = None
                        buscando_movimientos = False
                        continue

                    # --- 5. SALDO INICIAL ---
                    if "SALDO DEL PERIODO ANTERIOR" in linea_upper or "SALDO DEL PERÍODO ANTERIOR" in linea_upper:
                        if transaccion_actual is not None:
                            todas_las_filas.append(transaccion_actual)
                            transaccion_actual = None
                            
                        str_saldo_ini = partes[-1]
                        valor_saldo_ini = limpiar_numero(str_saldo_ini)
                        tracker.iniciar(valor_saldo_ini)
                        
                        fila = {
                            "CUENTA": cuenta_actual, "FECHA": "INICIO",
                            "DETALLE": "SALDO ANTERIOR",
                            "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": valor_saldo_ini
                        }
                        todas_las_filas.append(fila)
                        continue

                    # --- 6. PROCESAMIENTO DE MOVIMIENTOS ---
                    if buscando_movimientos:
                        es_fecha = re.match(r'^(\d{2}/\d{2}/\d{2,4})', partes[0])

                        if es_fecha:
                            if transaccion_actual is not None:
                                todas_las_filas.append(transaccion_actual)
                            
                            fecha = partes[0]
                            
                            indices_numeros = [idx for idx, p in enumerate(partes) if es_numero_bancario(p)]
                            
                            if len(indices_numeros) < 2:
                                transaccion_actual = None
                                continue
                            
                            idx_saldo = indices_numeros[-1]
                            idx_movimiento = indices_numeros[-2]
                            
                            str_saldo = partes[idx_saldo]
                            str_movimiento = partes[idx_movimiento] # <- Declaración original
                            
                            descripcion = " ".join(partes[1:idx_movimiento])
                            
                            valor_saldo_linea = limpiar_numero(str_saldo)
                            # CORRECCIÓN: Cambiado str_monto por str_movimiento
                            valor_monto_abs = abs(limpiar_numero(str_movimiento))
                            
                            tipo_mov = tracker.identificar_movimiento(valor_monto_abs, valor_saldo_linea)
                            if tipo_mov is None:
                                # La linea no cuadra contra el saldo anterior: la omitimos.
                                # Antes caia en el 'else' y se contabilizaba como HABER.
                                log_callback(
                                    f"SUPV: linea sin cuadrar (importe {valor_monto_abs:.2f}, "
                                    f"saldo {valor_saldo_linea:.2f}, "
                                    f"saldo previo {tracker.saldo_actual:.2f}); se omite"
                                )
                                transaccion_actual = None
                                continue

                            if tipo_mov == 'DEBE':
                                debe = valor_monto_abs
                                haber = 0.0
                            else:
                                debe = 0.0
                                haber = valor_monto_abs
                                
                            transaccion_actual = {
                                "CUENTA": cuenta_actual, "FECHA": fecha,
                                "DETALLE": descripcion, "DEBE": debe, "HABER": haber,
                                "SALDO_CALC": valor_saldo_linea
                            }

                        # --- 7. CONTINUACIÓN DE DESCRIPCIÓN ---
                        else:
                            if transaccion_actual is not None:
                                transaccion_actual["DETALLE"] += " " + linea_limpia

        if not fin_del_extracto and transaccion_actual is not None:
            todas_las_filas.append(transaccion_actual)

        return generar_excel_supervielle(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Supervielle: {str(e)}"


def generar_excel_supervielle(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos Supervielle."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    df = df[["CUENTA", "FECHA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]]
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
            # SaldoAnterior - Debe + Haber. Esta formula estaba al reves
            # (+DEBE -HABER) y hacia crecer el saldo con cada pago.
            formula = f"=F{fila_excel_anterior}-D{fila_excel_actual}+E{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)
