import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, guardar_excel

def extraer_hipotecario(pdf_path, excel_path, log_callback):
    """
    Motor Banco Hipotecario:
    - Formato numérico Inglés (1,000.00).
    - Ignora la fila resumen "SALDO FINAL DEL DIA".
    - Detecta Débito/Crédito por palabras clave (N/C, N/D) o posición.
    """
    try:
        todas_las_filas = []
        saldo_inicial_capturado = False
        
        # Regex para fecha (dd/mm/aaaa)
        patron_fecha = r'^(\d{2}/\d{2}/\d{4})'

        log_callback("🔴 Extrayendo pdf del BANCO HIPOTECARIO (Formato Inglés)...")

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

                    # --- 1. FILTROS DE LIMPIEZA ---
                    
                    # CORTE DE PÁGINA (Pie de página)
                    if "BANCO HIPOTECARIO S.A" in linea_upper or "RECONQUISTA 101 PB" in linea_upper:
                         # Si es pie de página, dejamos de leer esta hoja
                         break 
                    
                    # FILAS BASURA O ENCABEZADOS
                    if "FECHA" in linea_upper and "DESCRIPCION" in linea_upper: continue
                    if "DEVOLUCION IVA DTO" in linea_upper: continue
                    
                    # --- [CORRECCIÓN CLAVE] IGNORAR SALDO FINAL DEL DIA ---
                    # Esta fila tiene saldo pero no tiene movimiento (Debe/Haber vacíos),
                    # por lo que rompería la lógica si intentamos leerla como transacción.
                    if "SALDO FINAL DEL DIA" in linea_upper or "SALDO FINAL AL DIA" in linea_upper:
                        continue

                    partes = linea_limpia.split()

                    # --- 2. SALDO INICIAL (Cabecera) ---
                    # Buscamos la caja de cabecera que dice "SALDO INICIAL   $ X.XXX,XX"
                    if not saldo_inicial_capturado and "SALDO INICIAL" in linea_upper and "$" in linea_upper:
                        # Buscamos números en la línea
                        tokens_dinero = [p for p in partes if es_numero_bancario(p)]
                        if tokens_dinero:
                            # [CORRECCIÓN] Usamos es_formato_ingles=True
                            saldo_val = limpiar_numero(tokens_dinero[-1], es_formato_ingles=True)
                            
                            fila_inicio = {
                                "FECHA": "INICIO", "DETALLE": "SALDO INICIAL",
                                "DEBE": 0.0, "HABER": 0.0, "SALDO": saldo_val
                            }
                            todas_las_filas.append(fila_inicio)
                            saldo_inicial_capturado = True
                        continue

                    # --- 3. MOVIMIENTOS ---
                    match_fecha = re.match(patron_fecha, partes[0])
                    
                    if match_fecha:
                        fecha = match_fecha.group(1)
                        
                        # Detectamos tokens que parecen dinero
                        tokens_dinero = [p for p in partes if es_numero_bancario(p)]
                        
                        if not tokens_dinero: continue

                        # Lógica de Extracción de Monto:
                        # En Hipotecario, a veces aparece el saldo al final y a veces no.
                        # Pero siempre aparece el monto de la transacción.
                        # Si hay 2 números -> [Movimiento, Saldo]
                        # Si hay 1 número -> [Movimiento] (El saldo está vacío en el PDF visualmente)
                        
                        if len(tokens_dinero) >= 2:
                            str_movimiento = tokens_dinero[-2] # El anteúltimo
                        else:
                            str_movimiento = tokens_dinero[0]  # El único que hay

                        # [CORRECCIÓN] Conversión con formato Inglés
                        valor_movimiento = limpiar_numero(str_movimiento, es_formato_ingles=True)
                        valor_abs = abs(valor_movimiento)

                        # --- LÓGICA DEBE vs HABER (Heurística de Keywords) ---
                        # Como pdfplumber a veces pega las columnas, usamos palabras clave para decidir.
                        
                        desc_temp = linea_upper

                        # Este PDF no trae el signo del importe pegado, asi que
                        # hay que adivinar la direccion por palabras. Lo que NO
                        # se puede cambiar es la polaridad: el HABER es la plata
                        # que entra y el DEBE la que sale, como en todos los
                        # bancos del proyecto. Antes un DEPOSITO (que entra)
                        # iba al DEBE y cualquier otra cosa al HABER, o sea al
                        # reves: el conciliador calcula haber - debe, con lo cual
                        # los pagos aparecian como ingresos y no cruzaban con
                        # Xubio.
                        #
                        # Ojo: el acierto de la heuristica en si (que la palabra
                        # detectada sea la correcta para cada banco) no se puede
                        # verificar sin un PDF real del Hipotecario.
                        es_credito = False # Por defecto asumimos que sale plata

                        # Palabras que indican ENTRADA de dinero
                        keywords_credito = ["DEPOSITO", "ACRED", "CREDITO", "N/C", "TRANSF REC","CR TRANSF"]

                        if any(kw in desc_temp for kw in keywords_credito):
                            es_credito = True

                        # Asignación
                        if es_credito:
                            debe = 0.0
                            haber = valor_abs
                        else:
                            debe = valor_abs
                            haber = 0.0

                        # --- LIMPIEZA DE DESCRIPCIÓN ---
                        # Tomamos todo desde la fecha hasta el primer número
                        indices_dinero = [i for i, p in enumerate(partes) if es_numero_bancario(p)]
                        idx_fin_desc = indices_dinero[0] if indices_dinero else len(partes)
                        
                        desc_cruda = " ".join(partes[1:idx_fin_desc])
                        # Quitamos códigos numéricos sueltos (Sucursal, Referencia)
                        descripcion = re.sub(r'\b\d{3,9}\b', '', desc_cruda).strip()
                        descripcion = re.sub(r'\s+', ' ', descripcion) # Espacios dobles

                        fila = {
                            "FECHA": fecha,
                            "DETALLE": descripcion,
                            "DEBE": debe, "HABER": haber, 
                            "SALDO": 0.0 # Se calcula en Excel
                        }
                        todas_las_filas.append(fila)

        return generar_excel_hipotecario(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error HIPOTECARIO: {str(e)}"

def generar_excel_hipotecario(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos HIPOTECARIO."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    # Aseguramos columnas
    df = df[["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"]]
    
    # pandas 3 no deja escribir un string dentro de una columna float64.
    # Sin este cast, el df.at[] de la formula de abajo revienta con TypeError.
    df["SALDO"] = df["SALDO"].astype(object)

    for i in range(len(df)):
        fila_excel = i + 2 
        if df.at[i, "FECHA"] == "INICIO":
            df.at[i, "FECHA"] = ""
            continue 
        else:
            fila_excel_anterior = fila_excel - 1
            # DEBE es la salida, HABER la entrada:
            # SaldoAnterior - Debe + Haber
            formula = f"=E{fila_excel_anterior}-C{fila_excel}+D{fila_excel}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)
