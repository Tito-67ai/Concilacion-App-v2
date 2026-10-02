import pdfplumber
import pandas as pd
import re
import sys
import os

# Configuración de rutas para importar Tools
carpeta_padre = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(carpeta_padre)

from Tools import limpiar_numero, guardar_excel

def extraer_brubank(pdf_path, excel_path, log_callback):
    """
    Motor BruBank V5 (Anclaje Fuerte de Columnas):
    - Soluciona el problema de los CUITs en la descripción.
    - Captura la fila completa usando un anclaje desde el final de la línea.
    - Ignora matemáticamente la columna saldo para Excel, pero la lee para asegurar la estructura.
    - Mantiene la inversión contable (Débito Bco -> Haber, Crédito Bco -> Debe).
    """
    try:
        todas_las_filas = []
        
        # Variables base
        tipo_cta = "Cuenta"
        moneda_cta = ""
        cuenta_actual_str = "Cuenta Desconocida"
        
        # Banderas
        saldo_inicial_capturado = False
        fin_del_extracto = False
        leyendo_movimientos = False
        
        log_callback("🟣 Extrayendo pdf de BRUBANK (Anclaje Fuerte V5)...")
        
        # --- EL REGEX MAESTRO ---
        # 1. Definimos cómo se ve UNA columna financiera (Monto negativo, positivo, o un guion)
        col = r'(?:-\s*\$?\s*\d{1,3}(?:\.\d{3})*,\d{2}|\$?\s*\d{1,3}(?:\.\d{3})*,\d{2}|-)'
        
        # 2. Armamos la línea entera: Fecha + Ref + Descripción + Col1(Debe) + Col2(Haber) + Col3(Saldo)
        # Al anclarlo con '$' al final, la descripción (.*?) absorbe cualquier CUIT o texto raro sin romper las columnas.
        patron_linea = r'^(\d{2}[-/]\d{2}[-/]\d{2,4})\s+([\d\w\-]+)\s+(.*?)\s+(' + col + r')\s+(' + col + r')\s+(' + col + r')$'

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
                    
                    # --- 1. FIN DEL EXTRACTO ---
                    if "LOS DEPÓSITOS EN" in linea_upper or "LOS DEPOSITOS EN" in linea_upper:
                        log_callback("⏹️ Fin del extracto detectado (Legales).")
                        fin_del_extracto = True
                        break 
                        
                    # --- 2. ACTIVADOR DE MOVIMIENTOS ---
                    if "FECHA" in linea_upper and "#REF" in linea_upper:
                        leyendo_movimientos = True
                        continue

                    # --- 3. DETECCIÓN DE CUENTA ---
                    if "TIPO" in linea_upper:
                        idx_tipo = linea_upper.find("TIPO")
                        texto_post = linea_limpia[idx_tipo+4:].strip()
                        
                        palabras_prohibidas = ["SALDO", "RESUMEN", "CRÉDITO", "DÉBITO"]
                        for palabra in palabras_prohibidas:
                            idx_corte = texto_post.upper().find(palabra)
                            if idx_corte != -1:
                                texto_post = texto_post[:idx_corte].strip()
                                
                        tipo_cta = texto_post
                        moneda_cta = "" 
                        cuenta_actual_str = tipo_cta 
                        saldo_inicial_capturado = False
                        leyendo_movimientos = False 
                        log_callback(f"   🏦 Nueva cuenta detectada: {cuenta_actual_str}")
                        
                    if "MONEDA" in linea_upper:
                        idx_moneda = linea_upper.find("MONEDA")
                        texto_post = linea_limpia[idx_moneda+6:].strip()
                        
                        for palabra in ["SALDO", "RESUMEN", "CRÉDITO", "DÉBITO"]:
                            idx_corte = texto_post.upper().find(palabra)
                            if idx_corte != -1:
                                texto_post = texto_post[:idx_corte].strip()
                        moneda_cta = texto_post
                        cuenta_actual_str = f"{tipo_cta} - {moneda_cta}"
                        
                    if "NÚMERO" in linea_upper or "NUMERO" in linea_upper:
                        match_num = re.search(r'(?:NÚMERO|NUMERO)\s+(\d[\d\-]*)', linea_limpia, re.IGNORECASE)
                        if match_num:
                            num_cta = match_num.group(1).strip()
                            if moneda_cta:
                                cuenta_actual_str = f"{tipo_cta} - {moneda_cta} - {num_cta}"
                            else:
                                cuenta_actual_str = f"{tipo_cta} - {num_cta}"
                            log_callback(f"      ↳ Número anexado: {num_cta}")

                    # --- 4. SALDO INICIAL ---
                    if "SALDO INICIAL" in linea_upper and not saldo_inicial_capturado:
                        idx_saldo = linea_upper.find("SALDO INICIAL")
                        subcadena = linea_limpia[idx_saldo:]
                        
                        patron_dinero = r'(-?\s*\$?\s*\d{1,3}(?:\.\d{3})*,\d{2})'
                        matches = re.findall(patron_dinero, subcadena)
                        
                        if matches:
                            valor_ini = limpiar_numero(matches[-1].replace('$', ''))
                            fila = {
                                "CUENTA": cuenta_actual_str, "FECHA": "INICIO", "REFERENCIA": "",
                                "DETALLE": "SALDO INICIAL",
                                "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": valor_ini
                            }
                            todas_las_filas.append(fila)
                            saldo_inicial_capturado = True
                            
                    # --- 5. MOVIMIENTOS ---
                    if leyendo_movimientos:
                        # Aplicamos el Regex Maestro que lee de extremo a extremo
                        match_mov = re.match(patron_linea, linea_limpia)
                        
                        if match_mov:
                            fecha = match_mov.group(1)
                            ref = match_mov.group(2)
                            desc_limpia = match_mov.group(3).strip() # Aquí quedó el CUIT atrapado sanamente
                            str_debe = match_mov.group(4)   # Débito Banco
                            str_haber = match_mov.group(5)  # Crédito Banco
                            
                            # Limpieza y conversión
                            valor_debito_bco = 0.0 if str_debe.strip() == '-' else abs(limpiar_numero(str_debe.replace('$', '')))
                            valor_credito_bco = 0.0 if str_haber.strip() == '-' else abs(limpiar_numero(str_haber.replace('$', '')))
                            
                            # --- INVERSIÓN CONTABLE ---
                            debe = valor_credito_bco
                            haber = valor_debito_bco
                            
                            fila = {
                                "CUENTA": cuenta_actual_str,
                                "FECHA": fecha,
                                "REFERENCIA": ref,
                                "DETALLE": desc_limpia,
                                "DEBE": debe,
                                "HABER": haber,
                                "SALDO_CALC": 0.0 # Ponemos 0 provisional, la fórmula de Excel hará el trabajo
                            }
                            todas_las_filas.append(fila)
                            
        return generar_excel_brubank(todas_las_filas, excel_path, log_callback)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Brubank: {str(e)}"


def generar_excel_brubank(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos en Brubank."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    df = df[["CUENTA", "FECHA", "REFERENCIA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]]
    df.rename(columns={"SALDO_CALC": "SALDO"}, inplace=True)

    for i in range(len(df)):
        fila_excel_actual = i + 2 
        if df.at[i, "FECHA"] == "INICIO":
            df.at[i, "FECHA"] = ""
            continue 
        else:
            fila_excel_anterior = fila_excel_actual - 1
            # FÓRMULA GANADORA: G=SALDO, E=DEBE (Entradas), F=HABER (Salidas)
            # Saldo = Saldo Anterior + Debe - Haber
            formula = f"=G{fila_excel_anterior}+E{fila_excel_actual}-F{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)