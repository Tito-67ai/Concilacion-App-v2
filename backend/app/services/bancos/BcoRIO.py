import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, TrackerSaldo, guardar_excel

def extraer_santander(pdf_path, excel_path, log_callback):
    """
    Motor Santander V4 (Soporte para Saldos Negativos):
    - Regex mejorado para capturar signos '-' y simbolos '$'.
    - Corrige el error de "todo en una celda" causado por fallos en la validación matemática
      al no detectar el signo negativo del saldo inicial.
    """
    try:
        todas_las_filas = []
        cuenta_actual = "Desconocida"
        ultima_fecha = "S/D"
        buscando_transacciones = False
        tracker = TrackerSaldo()
        
        # Regex base para fecha
        patron_fecha = r'^(\d{2}/\d{2}/\d{2})'
        
        # --- NUEVO REGEX CRÍTICO ---
        # 1. (-?[\s\$]*) -> Busca opcionalmente un menos, espacios o signos $ al inicio
        # 2. \d{1,3}... -> El formato de numero 1.000,00
        # 3. (?!\s*%) -> Ignora si es un porcentaje
        patron_monto = r'(-?[\s\$]*\d{1,3}(?:\.\d{3})*,\d{2})(?!\s*%)'

        # Lista negra (Pie de página)
        frases_ignorar = [
            "BANCO SANTANDER ARGENTINA S.A.", "SALVO ERROR U OMISIÓN",
            "LEY 25.738", "INTEGRACIÓN ACCIONARIA", "CORRELATIVO 800678",
            "AV. JUAN DE GARAY", "CAPITAL EXTRANJERO RESPONDE",
            "ENTIDADES QUE UTILICEN LA MARCA"
        ]

        log_callback("🔴 Extrayendo pdf del BANCO SANTANDER...")

        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                log_callback(f"Leyendo página {i+1} de {total_pags}...")
                
                texto_pagina = pagina.extract_text()
                if not texto_pagina: continue

                lineas = texto_pagina.split('\n')

                for linea in lineas:
                    linea_limpia = linea.strip()
                    linea_upper = linea_limpia.upper()
                    
                    if not linea_limpia: continue

                    # --- 1. FILTROS DE SEGURIDAD ---
                    if any(frase in linea_upper for frase in frases_ignorar): continue
                    if re.match(r'^\s*\d+(\s*-\s*\d+)?\s*$', linea_limpia): continue 

                    if "DETALLE IMPOSITIVO" in linea_upper:
                        return generar_excel_santander(todas_las_filas, excel_path, log_callback)

                    if "MOVIMIENTOS" in linea_upper and ("FECHA" in linea_upper or "COMPROBANTE" in linea_upper):
                         continue

                    if "SALDO TOTAL" in linea_upper:
                         buscando_transacciones = False
                         continue

                    # Detección de Cuenta
                    if "CUENTA" in linea_upper and "Nº" in linea_upper:
                        match_cta = re.search(r'Nº\s*([\d\-/]+)', linea)
                        if match_cta:
                            cuenta_str = match_cta.group(1)
                            tipo = "Pesos" if "PESOS" in linea_upper else ("Dólares" if "DOLARES" in linea_upper else "")
                            cuenta_actual = f"Cuenta {tipo} {cuenta_str}".strip()
                        continue
                    
                    if "MOVIMIENTOS" in linea_upper:
                        buscando_transacciones = True
                        continue

                    # --- 2. PROCESAMIENTO DE FILAS ---
                    if buscando_transacciones:
                        # Buscamos montos (ahora captura "-$ 29.000,00" completo)
                        montos_encontrados = re.findall(patron_monto, linea_limpia)
                        
                        # CASO: SALDO INICIAL
                        if "SALDO INICIAL" in linea_upper or "SALDO ANTERIOR" in linea_upper:
                            if montos_encontrados:
                                # Importante: limpiar_numero debe manejar el string "-$ 29..."
                                saldo_inicial = limpiar_numero(montos_encontrados[-1])
                                tracker.iniciar(saldo_inicial)
                                fila = {
                                    "CUENTA": cuenta_actual, "FECHA": "INICIO",
                                    "DETALLE": "SALDO INICIAL",
                                    "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": saldo_inicial
                                }
                                todas_las_filas.append(fila)
                            continue

                        # CASO: POSIBLE MOVIMIENTO
                        es_transaccion_valida = False

                        if len(montos_encontrados) >= 2:
                            str_saldo = montos_encontrados[-1]
                            str_importe = montos_encontrados[-2] 
                            
                            valor_saldo_linea = limpiar_numero(str_saldo)
                            valor_importe_abs = abs(limpiar_numero(str_importe))

                            # VALIDACIÓN MATEMÁTICA
                            saldo_anterior = tracker.saldo_actual
                            
                            # Tolerancia pequeña por redondeos
                            check_resta = abs((saldo_anterior - valor_importe_abs) - valor_saldo_linea) < 0.05
                            check_suma = abs((saldo_anterior + valor_importe_abs) - valor_saldo_linea) < 0.05

                            if check_resta or check_suma:
                                es_transaccion_valida = True
                                
                                match_fecha = re.match(patron_fecha, linea_limpia)
                                if match_fecha:
                                    ultima_fecha = match_fecha.group(1)
                                    texto_sin_fecha = linea_limpia[len(ultima_fecha):].strip()
                                else:
                                    texto_sin_fecha = linea_limpia

                                # Limpiar importe del texto (usamos el string original encontrado)
                                idx_monto = texto_sin_fecha.rfind(str_importe)
                                if idx_monto != -1:
                                    descripcion = texto_sin_fecha[:idx_monto].strip()
                                else:
                                    descripcion = texto_sin_fecha

                                # Limpieza comprobante
                                partes_desc = descripcion.split(' ', 1)
                                if len(partes_desc) > 1 and partes_desc[0].isdigit() and len(partes_desc[0]) > 4:
                                    descripcion = partes_desc[1]

                                # Actualizar Tracker
                                tipo_mov = tracker.identificar_movimiento(valor_importe_abs, valor_saldo_linea)
                                
                                debe = valor_importe_abs if tipo_mov == 'DEBE' else 0.0
                                haber = valor_importe_abs if tipo_mov == 'HABER' else 0.0

                                fila = {
                                    "CUENTA": cuenta_actual, "FECHA": ultima_fecha,
                                    "DETALLE": descripcion, 
                                    "DEBE": debe, "HABER": haber,
                                    "SALDO_CALC": 0.0 
                                }
                                todas_las_filas.append(fila)
                            else:
                                es_transaccion_valida = False

                        # CASO: CONTINUACIÓN DE DESCRIPCIÓN 
                        if not es_transaccion_valida:
                            if todas_las_filas and len(linea_limpia) > 3:
                                if "SALDO" not in linea_upper and "MOVIMIENTOS" not in linea_upper:
                                    if "CUIT" in linea_upper or "I.G.J." in linea_upper or "RESP:" in linea_upper:
                                         pass 
                                    
                                    todas_las_filas[-1]["DETALLE"] += " " + linea_limpia

        return generar_excel_santander(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Santander: {str(e)}"

def generar_excel_santander(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos Santander."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    col_orden = ["CUENTA", "FECHA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]
    df = df[[c for c in col_orden if c in df.columns]]
    
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
            # D=DEBE (plata que sale), E=HABER (plata que entra), F=SALDO:
            # SaldoAnterior - Debe + Haber. Esta formula restaba el HABER,
            # al reves de lo que hace el procesador.
            formula = f"=F{fila_excel_anterior}-D{fila_excel_actual}+E{fila_excel_actual}" 
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)
