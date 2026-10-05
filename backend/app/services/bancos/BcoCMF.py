import pdfplumber # Librería para abrir y extraer texto de archivos PDF
import pandas as pd # Librería para crear y manipular tablas de datos (DataFrames)
import re # Librería de Expresiones Regulares (Regex) para buscar patrones de texto

from app.services.Tools import limpiar_numero, TrackerSaldo, guardar_excel

def extraer_cmf(pdf_path, excel_path, log_callback):
    """
    Motor CMF V3 (Con Interruptor Inteligente):
    - Usa formato argentino para montos.
    - Apaga la recolección de texto al detectar palabras de pie de página/totales.
    """
    try:
        # Creamos una lista vacía donde iremos guardando cada movimiento como un diccionario
        todas_las_filas = []
        # Definimos el nombre de la cuenta por defecto para este banco
        cuenta_actual = "Cuenta Única CMF"
        # Iniciamos nuestro "rastreador" matemático para saber si un monto es Debe o Haber
        tracker = TrackerSaldo()
        
        # Enviamos un mensaje a la pantalla de la aplicación
        log_callback("🟢 Extrayendo pdf del BANCO CMF...")
        
        # --- REGEX (Expresión Regular) para encontrar dinero en formato Argentino ---
        # Explicación del patrón:
        # -?           -> Puede tener un signo menos al principio (opcional)
        # \s* -> Puede tener espacios en blanco después del signo (opcional)
        # \d{1,3}      -> Debe iniciar con entre 1 y 3 números
        # (?:\.\d{3})* -> Puede tener grupos de 3 números separados por puntos (los miles)
        # ,\d{2}       -> Debe terminar OBLIGATORIAMENTE con una coma y dos números (los centavos)
        patron_monto_arg = r'(-?\s*\d{1,3}(?:\.\d{3})*,\d{2})'
        
        # --- INTERRUPTOR INTELIGENTE ---
        # Empieza apagado. Solo se prenderá cuando leamos una fecha, indicando que hay una transacción.
        leyendo_movimientos = False
        
        # Lista de palabras que nos indican que llegamos al final de la tabla de movimientos o son encabezados
        frases_corte_texto = [
            "TOTAL", "SALDO", "HOJA", "CANTIDAD", "IMPORTE", 
            "RESUMEN", "PÁGINA", "PAGINA", "FECHA", "COMPROB",
            "DÉBITOS", "CRÉDITOS"
        ]
        
        # Abrimos el archivo PDF de forma segura
        with pdfplumber.open(pdf_path) as pdf:
            # Contamos cuántas páginas tiene el PDF
            total_pags = len(pdf.pages)
            
            # Bucle para recorrer página por página (enumerate nos da el número de página 'i' y el contenido)
            for i, pagina in enumerate(pdf.pages):
                log_callback(f"Leyendo página {i+1} de {total_pags}...")
                
                # Extraemos todo el texto de la página actual como un bloque gigante
                texto_pagina = pagina.extract_text()
                # Si la página está vacía (es una imagen sin texto), pasamos a la siguiente hoja
                if not texto_pagina: continue
                
                # Dividimos todo el texto de la página en una lista de líneas separadas por un "enter" (\n)
                lineas = texto_pagina.split('\n')
                
                # Bucle para analizar cada línea de texto de esa página
                for linea in lineas:
                    linea_limpia = linea.strip() # Borramos los espacios en blanco inútiles al principio y al final
                    linea_upper = linea_limpia.upper() # Convertimos la línea a MAYÚSCULAS para facilitar la búsqueda
                    
                    # Si la línea quedó vacía tras limpiarla, saltamos a la siguiente línea
                    if not linea_limpia: continue
                    
                    # --- 0. CONTROL DEL INTERRUPTOR ---
                    # Revisamos si alguna de nuestras "palabras de corte" está en esta línea
                    if any(palabra in linea_upper for palabra in frases_corte_texto):
                        # Si encontramos una palabra de corte, APAGAMOS el interruptor para dejar de guardar basura
                        leyendo_movimientos = False
                        
                    # --- 1. SALDO INICIAL ---
                    # Buscamos la línea exacta donde el banco CMF dice el saldo inicial
                    if "SALDO RESUMEN ANTERIOR" in linea_upper:
                        partes = linea_limpia.split() # Cortamos la línea palabra por palabra (por espacios)
                        try:
                            # El saldo suele ser la última palabra de esa línea
                            texto_saldo = partes[-1]
                            # A veces el signo menos queda separado en la palabra anterior. Lo verificamos:
                            if len(partes) > 1 and partes[-2] == '-': 
                                texto_saldo = "-" + texto_saldo # Unimos el signo menos con el número
                            
                            # Usamos Tools para limpiar el texto y convertirlo en un número matemático real
                            valor_saldo_inicial = limpiar_numero(texto_saldo)
                            # Le informamos este número a nuestro rastreador matemático
                            tracker.iniciar(valor_saldo_inicial)
                            
                            # Buscamos la fecha, que suele estar 3 posiciones atrás. Si no tiene forma de fecha, ponemos "INICIO"
                            fecha_ini = partes[-3] if "/" in partes[-3] else "INICIO"
                            
                            # Creamos el diccionario (la fila) que representa el saldo inicial
                            fila = {
                                "CUENTA": cuenta_actual, "FECHA": fecha_ini,
                                "DETALLE": "SALDO ANTERIOR (Automático)",
                                "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": valor_saldo_inicial
                            }
                            # Guardamos esta fila en nuestra lista maestra
                            todas_las_filas.append(fila)
                        except:
                            pass # Si algo falla en esta línea específica, no hacemos nada y continuamos
                        continue # Terminamos de procesar esta línea, pasamos a la siguiente

                    # --- 2. MOVIMIENTOS ---
                    # Buscamos si la línea EMPIEZA con una fecha exacta (Ej: 01/12/2026)
                    match_fecha = re.match(r'^(\d{2}/\d{2}/\d{4})', linea_limpia)
                    
                    if match_fecha:
                        leyendo_movimientos = True # <--- ¡Encontramos una fecha! PRENDEMOS EL INTERRUPTOR
                        ultima_fecha = match_fecha.group(1) # Guardamos la fecha detectada para usarla
                        
                        # Buscamos todos los montos de dinero en esta línea usando nuestro Regex
                        montos_encontrados = re.findall(patron_monto_arg, linea_limpia)
                        
                        # Para ser un movimiento bancario, debe tener al menos 2 montos (Importe y Saldo final)
                        if len(montos_encontrados) >= 2:
                            str_saldo = montos_encontrados[-1] # El último monto encontrado siempre es el Saldo
                            str_monto = montos_encontrados[-2] # El anteúltimo monto es el Importe
                            
                            # Convertimos los textos encontrados a números con decimales
                            valor_saldo_linea = limpiar_numero(str_saldo)
                            valor_monto_abs = abs(limpiar_numero(str_monto)) # Lo hacemos positivo (abs) para clasificarlo luego
                            
                            # Le pedimos a nuestro tracker que evalúe si este importe restó o sumó al saldo
                            tipo_mov = tracker.identificar_movimiento(valor_monto_abs, valor_saldo_linea)
                            if tipo_mov is None:
                                # La linea no cuadra contra el saldo anterior: la omitimos.
                                # Antes caia en el 'else' y se contabilizaba como HABER.
                                log_callback(
                                    f"CMF: linea sin cuadrar (importe {valor_monto_abs:.2f}, "
                                    f"saldo {valor_saldo_linea:.2f}, "
                                    f"saldo previo {tracker.saldo_actual:.2f}); se omite"
                                )
                                continue

                            # Si fue una resta (salida de dinero), va al DEBE
                            if tipo_mov == 'DEBE':
                                debe = valor_monto_abs
                                haber = 0.0
                            # Si fue una suma (entrada de dinero), va al HABER
                            else: 
                                debe = 0.0
                                haber = valor_monto_abs
                            
                            # --- LIMPIEZA DE LA DESCRIPCIÓN ---
                            # 1. Quitamos la fecha del principio de la línea
                            texto_sin_fecha = linea_limpia[len(ultima_fecha):].strip()
                            # 2. Quitamos el número de comprobante si quedó pegado al inicio
                            texto_sin_comprob = re.sub(r'^\d+\s+', '', texto_sin_fecha).strip()
                            
                            # 3. Buscamos de derecha a izquierda dónde empieza nuestro importe para aislar el texto
                            idx_monto = texto_sin_comprob.rfind(str_monto)
                            if idx_monto != -1:
                                concepto_sucio = texto_sin_comprob[:idx_monto].strip() # Cortamos antes del monto
                            else:
                                concepto_sucio = texto_sin_comprob # Si falla, dejamos lo que teníamos
                                
                            # 4. Limpieza final: borramos códigos raros al principio del concepto (Ej: "80 .-080-DB-")
                            descripcion = re.sub(r'^\d+\s*[.-]\d+-', '', concepto_sucio).strip()

                            # Armamos la fila final para esta transacción
                            fila = {
                                "CUENTA": cuenta_actual, "FECHA": ultima_fecha,
                                "DETALLE": descripcion, "DEBE": debe, "HABER": haber,
                                "SALDO_CALC": valor_saldo_linea 
                            }
                            # La agregamos a la lista maestra de resultados
                            todas_las_filas.append(fila)
                            continue # Terminamos con esta línea, vamos a la siguiente

                    # --- 3. CONTINUACIÓN DE TEXTO (Sub-líneas descriptivas) ---
                    # Si la línea no fue Saldo Inicial, ni empezó con Fecha... puede ser texto de descripción extra
                    # SOLO anexamos el texto si el interruptor está PRENDIDO y si ya tenemos al menos una fila guardada
                    if leyendo_movimientos and todas_las_filas:
                        if len(linea_limpia) > 2: # Evitamos pegar renglones con basura de 1 o 2 letras
                            # Pegamos este texto al final del "DETALLE" de la ÚLTIMA fila guardada (índice -1)
                            todas_las_filas[-1]["DETALLE"] += " " + linea_limpia

        # Al terminar de leer todas las páginas, enviamos la lista completa al generador de Excel
        return generar_excel_cmf(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        # Si ocurre un error inesperado, imprimimos el historial del error para debugear
        import traceback
        traceback.print_exc()
        return False, f"Error CMF: {str(e)}"

def generar_excel_cmf(filas, excel_path, log_callback):
    """
    Toma la lista de datos procesados, la convierte en tabla y genera el archivo Excel con fórmulas.
    """
    # Verificamos si la lista tiene datos antes de continuar
    if not filas:
        return False, "No se encontraron movimientos CMF."

    log_callback(f"Generando Excel con {len(filas)} filas...")
    
    # Convertimos la lista de diccionarios en un DataFrame (una tabla estilo Excel en memoria)
    df = pd.DataFrame(filas)
    
    # Ordenamos las columnas en el orden exacto que queremos exportar
    df = df[["CUENTA", "FECHA", "DETALLE", "DEBE", "HABER", "SALDO_CALC"]]
    
    # Renombramos la columna SALDO_CALC para que en el Excel diga simplemente "SALDO"
    df.rename(columns={"SALDO_CALC": "SALDO"}, inplace=True)

    # Bucle para inyectar fórmulas matemáticas de Excel en la columna Saldo fila por fila
    # pandas 3 no deja escribir un string dentro de una columna float64.
    # Sin este cast, el df.at[] de la formula de abajo revienta con TypeError.
    df["SALDO"] = df["SALDO"].astype(object)

    for i in range(len(df)):
        fila_excel_actual = i + 2 # Sumamos 2 porque el índice en Python empieza en 0 y el Excel tiene 1 fila de encabezado
        
        # Si estamos en la fila del Saldo Inicial, no ponemos fórmula
        if "SALDO ANTERIOR" in str(df.at[i, "DETALLE"]).upper():
             # Borramos la palabra "INICIO" de la columna fecha para que quede más prolijo
             if df.at[i, "FECHA"] == "INICIO":
                 df.at[i, "FECHA"] = ""
             continue # Pasamos a la siguiente iteración del bucle
        else:
            # Para todas las demás filas: Saldo de arriba - Debe + Haber.
            # Las letras SIEMPRE son D=Debe, E=Haber, F=Saldo con este orden de
            # columnas. Antes la formula restaba el HABER y suma el DEBE, al
            # reves de lo que hace el procesador.
            fila_excel_anterior = fila_excel_actual - 1
            formula = f"=F{fila_excel_anterior}-D{fila_excel_actual}+E{fila_excel_actual}"
            
            # Escribimos la fórmula (como si la tecleáramos) en la celda correspondiente
            df.at[i, "SALDO"] = formula

    # Invocamos la herramienta central para guardar esta tabla físicamente en tu disco duro
    return guardar_excel(df, excel_path)
