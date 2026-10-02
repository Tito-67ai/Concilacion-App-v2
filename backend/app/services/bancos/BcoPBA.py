import pdfplumber
import pandas as pd
import re
import sys
import os

# Configuración de rutas para importar Tools
carpeta_padre = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(carpeta_padre)

# Importamos las herramientas existentes
# Usaremos es_formato_ingles=True para que acepte el punto como decimal
from Tools import limpiar_numero, guardar_excel, TrackerSaldo

def extraer_provincia(pdf_path, excel_path, log_callback):
    """
    Motor Banco Provincia:
    - Estructura: Fecha | Concepto | Importe | Fecha Valor | Saldo
    - Integra Tools.limpiar_numero con es_formato_ingles=True para leer decimales con punto.
    """
    try:
        filas = []
        buscando = False
        
        # Regex para fecha (dd/mm/aaaa)
        patron_fecha = r'^(\d{2}/\d{2}/\d{4})'
        
        log_callback("🟢 Extrayendo pdf del BANCO PROVINCIA...")

        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)
            for i, pagina in enumerate(pdf.pages):
                log_callback(f"Procesando página {i+1} de {total_pags}...")
                
                texto = pagina.extract_text()
                if not texto: continue
                
                lineas = texto.split('\n')
                
                for linea in lineas:
                    linea = linea.strip()
                    if not linea: continue
                    
                    # 1. CONDICIÓN DE CORTE (Fin del extracto)
                    if "Tot. Retención ARBA" in linea or "Tot. Retención" in linea:
                        log_callback("Fin del extracto detectado.")
                        return generar_excel_provincia(filas, excel_path, log_callback)

                    # 2. DETECCIÓN DE INICIO / CABECERA
                    if "Fecha" in linea and "Concepto" in linea and "Importe" in linea:
                        buscando = True
                        continue

                    # 3. PROCESAMIENTO DE FILAS
                    if buscando:
                        match_fecha = re.match(patron_fecha, linea)
                        
                        if match_fecha:
                            fecha = match_fecha.group(1)
                            partes = linea.split()
                            
                            # --- CASO: SALDO ANTERIOR ---
                            if "SALDO ANTERIOR" in linea.upper():
                                # El último elemento es el saldo
                                # Usamos es_formato_ingles=True porque viene con punto (ej: -49728.18)
                                saldo_actual = limpiar_numero(partes[-1], es_formato_ingles=True)
                                
                                filas.append({
                                    "FECHA": "INICIO", "DETALLE": "SALDO ANTERIOR",
                                    "DEBE": 0.0, "HABER": 0.0, "SALDO": saldo_actual
                                })
                                continue

                            # --- CASO: MOVIMIENTO NORMAL ---
                            try:
                                # Estructura: Fecha ... Concepto ... Importe FechaValor Saldo
                                str_saldo = partes[-1]      # Último
                                str_importe = partes[-3]    # Antepenúltimo (saltando Fecha Valor)
                                
                                # Usamos la herramienta centralizada
                                valor_importe = limpiar_numero(str_importe, es_formato_ingles=True)
                                valor_saldo = limpiar_numero(str_saldo, es_formato_ingles=True)
                                
                                # Recuperar Descripción (Todo lo que está en el medio)
                                idx_importe = linea.rfind(str_importe)
                                if idx_importe != -1:
                                    # Cortamos desde char 10 (fin de fecha) hasta inicio importe
                                    detalle = linea[10:idx_importe].strip()
                                else:
                                    # Fallback por si rfind falla
                                    detalle = " ".join(partes[1:-3])

                                # Lógica DEBE / HABER
                                # En este extracto: Negativo disminuye saldo (DEBE), Positivo aumenta (HABER)
                                if valor_importe < 0:
                                    debe = 0.0
                                    haber = abs(valor_importe)
                                else:
                                    debe = abs(valor_importe)
                                    haber = 0.0

                                filas.append({
                                    "FECHA": fecha,
                                    "DETALLE": detalle,
                                    "DEBE": debe, "HABER": haber, "SALDO": valor_saldo
                                })

                            except Exception:
                                # Si falla algo, lo tratamos como texto de continuación
                                if filas: filas[-1]["DETALLE"] += " " + linea

                        else:
                            # --- LÍNEA DE CONTINUACIÓN DE TEXTO ---
                            if filas and buscando:
                                if "SALDO" not in linea.upper() and len(linea) > 2:
                                    filas[-1]["DETALLE"] += " " + linea

        return generar_excel_provincia(filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error Provincia: {str(e)}"

def generar_excel_provincia(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos Provincia."

    log_callback(f"Generando Excel Provincia con {len(filas)} filas...")
    df = pd.DataFrame(filas)
    
    # Asegurar columnas
    df = df[["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"]]
    
    # pandas 3 no deja escribir un string dentro de una columna float64.
    # Sin este cast, el df.at[] de la formula de abajo revienta con TypeError.
    df["SALDO"] = df["SALDO"].astype(object)

    for i in range(len(df)):
        fila_excel = i + 2
        if df.at[i, "FECHA"] == "INICIO":
            df.at[i, "FECHA"] = ""
            continue
        
        # Fórmula: SaldoAnterior + Haber - Debe
        formula = f"=E{fila_excel-1}+C{fila_excel}-D{fila_excel}"
        df.at[i, "SALDO"] = formula

    return guardar_excel(df, excel_path)
