import pdfplumber
import pandas as pd
import re
import sys
import os

# Configuración de ruta
carpeta_padre = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(carpeta_padre)

from Tools import es_numero_bancario, limpiar_numero, guardar_excel

def extraer_icbc(pdf_path, excel_path, log_callback):
    """
    Motor ICBC:
    - Fecha formato DD-MM.
    - Signos negativos al final del número (100.00-).
    - Detecta cortes de página "CONTINUA...".
    - Ignora códigos numéricos internos entre Concepto e Importe.
    """
    try:
        todas_las_filas = []
        
        saldo_inicial_capturado = False
        
        log_callback("🔴 Extrayendo pdf del BANCO ICBC...")

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
                    
                    # --- 1. DETECCIÓN DE CORTES DE PÁGINA ---
                    # Si vemos esto, dejamos de leer la página actual inmediatamente
                    if "CONTINUA AL DORSO" in linea_upper or "CONTINUA EN LA HOJA" in linea_upper:
                        log_callback(f"   ↪ Corte de página detectado en línea: {linea_limpia[:20]}...")
                        break # Salimos del bucle de líneas para pasar a la siguiente página

                    # Fin del extracto
                    if "TOT.IMP.LEY" in linea_upper or "SALDO FINAL AL" in linea_upper:
                        continue

                    partes = linea_limpia.split()
                    if not partes: continue

                    # --- 2. SALDO INICIAL ---
                    # Buscamos solo el primer saldo inicial del extracto
                    if not saldo_inicial_capturado and "SALDO ULTIMO EXTRACTO" in linea_upper:
                        # Buscamos el número al final de la línea
                        numeros = [p for p in partes if es_numero_bancario(p)]
                        if numeros:
                            saldo_val = limpiar_numero(numeros[-1])
                            fila_inicio = {
                                "FECHA": "INICIO",
                                "DETALLE": "SALDO ANTERIOR (Automático)",
                                "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": saldo_val
                            }
                            todas_las_filas.append(fila_inicio)
                            saldo_inicial_capturado = True
                        continue
                    
                    # Ignoramos los "SALDO PAGINA ANTERIOR" que aparecen en hojas siguientes
                    if "SALDO PAGINA ANTERIOR" in linea_upper:
                        continue

                    # --- 3. MOVIMIENTOS ---
                    # Regex para fechas ICBC: DD-MM (ej: 08-10)
                    match_fecha = re.match(r'^(\d{2}-\d{2})', partes[0])
                    
                    if match_fecha:
                        fecha = match_fecha.group(1)
                        
                        # Filtramos solo lo que parece dinero real (con decimales/puntos)
                        # Esto elimina columnas basura como "0543" o "0187"
                        tokens_dinero = [p for p in partes if es_numero_bancario(p)]
                        
                        if not tokens_dinero:
                            continue
                        
                        # Lógica para distinguir Saldo vs Movimiento:
                        # Si hay 2 números (ej: "-500.00" y "22.000,00"), el último es el SALDO acumulado.
                        # Si hay 1 número, es el MOVIMIENTO.
                        
                        if len(tokens_dinero) >= 2:
                            # El último es saldo (lo ignoramos para el cálculo, usamos fórmula)
                            str_movimiento = tokens_dinero[-2]
                            # El resto son columnas basura, el movimiento es el anteúltimo dinero encontrado
                        else:
                            # Solo hay un número, es el movimiento
                            str_movimiento = tokens_dinero[0]
                        
                        # Convertimos
                        valor_movimiento = limpiar_numero(str_movimiento)
                        
                        # ICBC pone el menos al final (ej: "600,00-").
                        # Tools.limpiar_numero ya maneja esto, pero para asignar columnas DEBE/HABER:
                        # Si tiene "-" (string original) O es negativo (valor numérico) -> HABER
                        es_debito = "-" in str_movimiento or valor_movimiento < 0
                        
                        if es_debito:
                            debe = 0.0
                            haber = abs(valor_movimiento)
                        else:
                            debe = abs(valor_movimiento)
                            haber = 0.0
                        
                        # Descripción: Todo lo que está entre la fecha y el primer número bancario
                        # A veces hay códigos en el medio, intentamos limpiarlos visualmente
                        # Unimos todo y luego quitamos los códigos numéricos simples
                        indices_dinero = [i for i, p in enumerate(partes) if es_numero_bancario(p)]
                        idx_fin_desc = indices_dinero[0] if indices_dinero else len(partes)
                        
                        desc_cruda = " ".join(partes[1:idx_fin_desc])
                        
                        # Limpieza extra: quitar códigos numéricos sueltos (ej: 0543 0171)
                        # Regex: Reemplazar palabras que sean solo números de 3 o 4 dígitos
                        descripcion = re.sub(r'\b\d{3,4}\b', '', desc_cruda).strip()
                        # Quitar espacios dobles
                        descripcion = re.sub(r'\s+', ' ', descripcion)

                        fila = {
                            "FECHA": fecha,
                            "DETALLE": descripcion,
                            "DEBE": debe,
                            "HABER": haber,
                            "SALDO_CALC": 0.0 
                        }
                        todas_las_filas.append(fila)

        return generar_excel_icbc(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error ICBC: {str(e)}"

def generar_excel_icbc(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos ICBC."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    df = df[["FECHA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]]
    df.rename(columns={"SALDO_CALC": "SALDO"}, inplace=True)

    for i in range(len(df)):
        fila_excel_actual = i + 2 
        if df.at[i, "FECHA"] == "INICIO":
            df.at[i, "FECHA"] = ""
            continue 
        else:
            fila_excel_anterior = fila_excel_actual - 1
            # ICBC: Saldo Anterior - Debe + Haber (Lógica estándar)
            # Nota: Si el banco resta el débito, la fórmula es +C -D. 
            # Verificamos: Saldo (Positivo) - Debito (Salida) + Credito (Entrada)
            # En Excel: =SaldoAnterior - Debe + Haber (Si Debe es positivo visualmente)
            # Como separamos en columnas Debe/Haber positivos:
            formula = f"=E{fila_excel_anterior}+C{fila_excel_actual}-D{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)