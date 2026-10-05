import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, guardar_excel

def extraer_mp(pdf_path, excel_path, log_callback):
    """
    Motor Mercado Pago (MP) - Versión Anti-Huecos:
    - Asegura que la descripción nunca quede vacía uniendo buffers.
    - Captura líneas huérfanas arriba del ID.
    - Filtra encabezados que se meten en el medio.
    """
    try:
        todas_las_filas = []
        saldo_inicial_capturado = False
        
        # Variables de memoria (Buffer)
        temp_fecha = None
        temp_desc = ""

        log_callback("🔵 Extrayendo pdf del MERCADO PAGO...")

        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                log_callback(f"Leyendo página {i+1} de {total_pags}...")
                
                texto_pagina = pagina.extract_text()
                if not texto_pagina: continue

                lineas = texto_pagina.split('\n')

                for linea in lineas:
                    linea_limpia = linea.strip()
                    if not linea_limpia: continue

                    # --- 1. FILTROS DE BASURA ---
                    palabras_clave_encabezado = ["Fecha", "Descripción", "Valor", "Saldo", "ID de la", "operación"]
                    # Si la línea es SOLO encabezados, chau
                    if linea_limpia in palabras_clave_encabezado: continue
                    
                    # Si tiene 2 o más palabras clave juntas, chau
                    coincidencias = sum(1 for p in palabras_clave_encabezado if p in linea_limpia)
                    if coincidencias >= 2: continue

                    frases_ignorar = [
                        "Fecha de generación:", "Mercado Libre S.R.L.", "CUIT 30-70308853-4",
                        "Av. Caseros", "mercadopago.com.ar", "Saldo final:",
                        "DETALLE DE MOVIMIENTOS", "Canales de consulta", "Entradas:", "Salidas:"
                    ]
                    es_basura = False
                    for frase in frases_ignorar:
                        if frase in linea_limpia:
                            es_basura = True; break
                    
                    if re.search(r'\d+\s*/\s*\d+$', linea_limpia) and len(linea_limpia) < 10:
                        es_basura = True

                    if es_basura: continue

                    # --- 2. SALDO INICIAL ---
                    if not saldo_inicial_capturado:
                        match_saldo = re.search(r'Saldo\s+Inicial.*?\$?\s*([\d\.,]+)', linea_limpia, re.IGNORECASE)
                        if match_saldo:
                            str_saldo = match_saldo.group(1)
                            if es_numero_bancario(str_saldo):
                                saldo_val = limpiar_numero(str_saldo)
                                fila_inicio = {
                                    "FECHA": "INICIO", "DETALLE": "SALDO ANTERIOR (Automático)",
                                    "ID_OPERACION": "-", "IMPORTE": 0.0, "SALDO_CALC": saldo_val
                                }
                                todas_las_filas.append(fila_inicio)
                                saldo_inicial_capturado = True
                                log_callback(f"   💰 Saldo inicial: {saldo_val}")
                                continue

                    # --- 3. BÚSQUEDA DEL ID (El Ancla) ---
                    # Buscamos bloque de 10+ dígitos (ID Operación)
                    match_id = re.search(r'\b(\d{10,})\b', linea_limpia)

                    # CASO A: ENCONTRAMOS UN ID (Aquí cerramos la transacción)
                    if match_id:
                        id_operacion = match_id.group(1)
                        
                        # Verificamos si esta misma línea tiene fecha
                        match_fecha_local = re.match(r'^(\d{2}-\d{2}-\d{4})', linea_limpia)
                        
                        texto_izquierda_id = linea_limpia[:match_id.start()].strip()
                        
                        if match_fecha_local:
                            # Todo en una línea: Fecha + Descrip + ID
                            fecha = match_fecha_local.group(1)
                            # Quitamos la fecha del texto de la izquierda
                            descripcion_local = texto_izquierda_id[len(fecha):].strip()
                            # Si traíamos algo del buffer (raro pero posible), lo sumamos
                            descripcion_final = (temp_desc + " " + descripcion_local).strip()
                        else:
                            # La fecha está en el buffer (renglón anterior)
                            fecha = temp_fecha if temp_fecha else "S/D"
                            # Descripción = Buffer + Texto a la izquierda del ID
                            descripcion_final = (temp_desc + " " + texto_izquierda_id).strip()

                        # Respaldo por si quedó vacío
                        if not descripcion_final:
                            descripcion_final = "Movimiento MP (Sin descripción)"

                        # Extraer Montos (A la derecha del ID)
                        resto_linea = linea_limpia[match_id.end():].strip()
                        numeros_hallados = re.findall(r'[\-\$]?\s*[\d]{1,3}(?:[.,]\d{3})*[.,]\d{2}', resto_linea)
                        
                        if len(numeros_hallados) >= 2:
                            str_valor = numeros_hallados[-2]
                            valor_importe = limpiar_numero(str_valor)

                            fila = {
                                "FECHA": fecha,
                                "DETALLE": descripcion_final,
                                "ID_OPERACION": id_operacion,
                                "IMPORTE": valor_importe,
                                "SALDO_CALC": 0.0
                            }
                            todas_las_filas.append(fila)
                        
                        # ¡IMPORTANTE! Limpiamos el buffer
                        temp_fecha = None
                        temp_desc = ""

                    # CASO B: NO HAY ID (Línea incompleta o parte de descripción)
                    else:
                        match_fecha_inicio = re.match(r'^(\d{2}-\d{2}-\d{4})', linea_limpia)
                        
                        if match_fecha_inicio:
                            # Empieza nueva transacción partida
                            # Si ya teníamos algo en el buffer sin cerrar, lo perdemos (o era basura)
                            temp_fecha = match_fecha_inicio.group(1)
                            temp_desc = linea_limpia[len(temp_fecha):].strip()
                        
                        elif temp_fecha is not None:
                            # No tiene fecha, pero ya abrimos una transacción antes -> Es continuación de texto
                            temp_desc += " " + linea_limpia
                        
                        # Si no hay fecha y temp_fecha es None, es una línea huérfana (basura)

        return generar_excel_mp(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Mercado Pago: {str(e)}"

def generar_excel_mp(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos MP."

    log_callback(f"Generando Excel MP con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    df = df[["FECHA", "DETALLE", "ID_OPERACION", "IMPORTE", "SALDO_CALC"]]
    df.rename(columns={"SALDO_CALC": "SALDO"}, inplace=True)

    df["SALDO"] = df["SALDO"].astype(object)

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
            formula = f"=E{fila_excel_anterior}+D{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)
