import pdfplumber
import pandas as pd
import re

from app.services.Tools import es_numero_bancario, limpiar_numero, guardar_excel

# "PERIODO 01/07/2026 AL 01/07/2026" -> 2026
_RE_PERIODO = re.compile(r"PER[IÍ]ODO\s+\d{2}[/-]\d{2}[/-](\d{4})", re.IGNORECASE)
_RE_ANIO = re.compile(r"\b(20\d{2})\b")

# El BBVA imprime la fecha del movimiento como dd/mm, sin año.
_RE_FECHA_CORTA = re.compile(r"^\d{2}/\d{2}$")


def _anio_del_documento(texto):
    """
    Saca el año del extracto del propio PDF.

    Los movimientos de BBVA van fechados dd/mm ("01/07"), asi que sin el año no
    se pueden armar fechas validas y el pipeline los descartaba todos. El año
    esta en la linea de PERIODO del regimen SIRCREB, o en cualquier mencione del
    estilo "JULIO 2026" que imprima el banco.
    """
    m = _RE_PERIODO.search(texto)
    if m:
        return int(m.group(1))
    m = _RE_ANIO.search(texto)
    return int(m.group(1)) if m else None


def extraer_bbva(pdf_path, excel_path, log_callback):
    """
    Lógica BBVA "Single Line":
    - Asume que cada movimiento empieza y termina en la misma línea.
    - La fecha viene dd/mm: el año se toma del periodo del extracto.
    - Signo del importe: negativo = débito (sale), positivo = crédito (entra).
    """
    try:
        todas_las_filas = []

        cuenta_actual_nombre = None
        esperando_nombre_cuenta = False
        leyendo_movimientos = False
        saldo_inicial_capturado = False

        log_callback("🔵 Extrayendo pdf del BANCO BBVA...")

        with pdfplumber.open(pdf_path) as pdf:
            paginas = [(p.extract_text() or "") for p in pdf.pages]

        anio = _anio_del_documento("\n".join(paginas))
        if not anio:
            return False, (
                "No se encontro el periodo del extracto BBVA, asi que no se "
                "puede saber el año de las fechas (van como dd/mm)."
            )
        log_callback(f"📅 Periodo del extracto: año {anio}")

        total_pags = len(paginas)
        for i, texto_pagina in enumerate(paginas):
            log_callback(f"Leyendo página {i+1} de {total_pags}...")
            if not texto_pagina:
                continue

            lineas = texto_pagina.split("\n")

            for linea in lineas:
                if "PÁGINA" in linea.upper() or "SOBRE (" in linea.upper():
                    continue

                linea_limpia = linea.strip()
                linea_upper = linea_limpia.upper()
                partes = linea_limpia.split()
                if not partes:
                    continue

                # 1. CONTROL DE SECCIONES

                # Encabezado de cuenta (ej: "CC $ 001-022603/4 (Cta.Cte.Bancaria) - Iva-Responsable
                # Inscripto", o en dólares "CC U$S 001-022603/4 (...)"). Se busca este patrón en
                # CUALQUIER línea, no solo la que sigue a "MOVIMIENTOS EN CUENTAS": cuando el extracto
                # trae más de una cuenta, el BBVA repite este encabezado antes de cada bloque de
                # movimientos SIN volver a imprimir "MOVIMIENTOS EN CUENTAS" en el medio. Antes de
                # este fix, el bot solo reconocía la primera cuenta y dejaba de leer apenas aparecía
                # "TOTAL MOVIMIENTOS".
                # "U\$S" va primero en la alternativa para que "pesos" no se quede con la "U" suelta.
                if re.match(r"^(CC|CA)\s*(U\$S|\$)\s*[\d/\-]+\s*\(", linea_limpia, re.IGNORECASE):
                    cuenta_actual_nombre = linea_limpia
                    log_callback(f"📂 Cuenta detectada: {cuenta_actual_nombre}")
                    esperando_nombre_cuenta = False
                    leyendo_movimientos = True
                    saldo_inicial_capturado = False
                    continue

                if "MOVIMIENTOS EN CUENTAS" in linea_upper:
                    esperando_nombre_cuenta = True
                    leyendo_movimientos = False
                    saldo_inicial_capturado = False
                    continue

                if esperando_nombre_cuenta:
                    # Reserva por si el encabezado de la cuenta no matchea el patrón "CC $ / CA $"
                    # de arriba (algún tipo de cuenta con formato distinto).
                    cuenta_actual_nombre = linea_limpia
                    log_callback(f"📂 Cuenta detectada: {cuenta_actual_nombre}")
                    esperando_nombre_cuenta = False
                    leyendo_movimientos = True
                    continue

                if not leyendo_movimientos or not cuenta_actual_nombre:
                    continue

                if "TOTAL MOVIMIENTOS" in linea_upper:
                    leyendo_movimientos = False
                    cuenta_actual_nombre = None
                    continue

                # 2. SALDO INICIAL
                if not saldo_inicial_capturado and "SALDO ANTERIOR" in linea_upper:
                    numeros = [p for p in partes if es_numero_bancario(p)]
                    if numeros:
                        saldo_ini_val = limpiar_numero(numeros[-1])
                        fila_inicio = {
                            "CUENTA": cuenta_actual_nombre, "FECHA": "INICIO",
                            "DETALLE": "SALDO ANTERIOR (Automático)",
                            "DEBE": 0.0, "HABER": 0.0, "SALDO_CALC": saldo_ini_val
                        }
                        todas_las_filas.append(fila_inicio)
                        saldo_inicial_capturado = True
                    continue

                # 3. PROCESAMIENTO DE MOVIMIENTO
                if _RE_FECHA_CORTA.match(partes[0]):
                    # "00/00 SIN MOVIMIENTOS" es una fila que el banco imprime
                    # para decir que la cuenta no tuvo movimientos: no es una
                    # fila real y antes se colaba como movimiento en cero.
                    if partes[0] == "00/00":
                        continue

                    indices_nums = [idx for idx, p in enumerate(partes) if es_numero_bancario(p)]

                    if len(indices_nums) >= 2:
                        idx_saldo = indices_nums[-1]
                        idx_monto = indices_nums[-2]

                        # Si el segundo numero "de atras" es la propia fecha, la
                        # linea no tiene importe y saldo: no es un movimiento.
                        if idx_monto == 0:
                            continue

                        partes = partes[:idx_saldo + 1]

                        fecha = f"{partes[0]}/{anio}"
                        str_monto = partes[idx_monto]

                        idx_inicio_desc = 1
                        if len(partes) > 2 and idx_monto > 2:
                            token_letra = partes[1].upper()
                            token_codigo = partes[2]
                            if token_letra in ["D", "C"] and re.match(r"^\d+$", token_codigo):
                                idx_inicio_desc = 3

                        descripcion = " ".join(partes[idx_inicio_desc:idx_monto])
                        valor_monto = limpiar_numero(str_monto)

                        # El BBVA imprime el débito en negativo y el crédito en
                        # positivo. Se usaba al revés, así que todos los
                        # movimientos quedaban invertidos.
                        if valor_monto < 0:
                            debe = abs(valor_monto)
                            haber = 0.0
                        else:
                            debe = 0.0
                            haber = abs(valor_monto)

                        fila = {
                            "CUENTA": cuenta_actual_nombre, "FECHA": fecha,
                            "DETALLE": descripcion, "DEBE": debe, "HABER": haber,
                            "SALDO_CALC": 0.0
                        }
                        todas_las_filas.append(fila)

        return generar_excel_bbva(todas_las_filas, excel_path, log_callback)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Error BBVA: {str(e)}"

def generar_excel_bbva(filas, excel_path, log_callback):
    if not filas:
        return False, "No se encontraron movimientos BBVA."

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
            continue
        else:
            fila_excel_anterior = fila_excel_actual - 1
            # BBVA: Saldo - Debe + Haber
            formula = f"=F{fila_excel_anterior}-D{fila_excel_actual}+E{fila_excel_actual}"
            df.at[i, "SALDO"] = formula

    # USO DE LA HERRAMIENTA CENTRALIZADA
    return guardar_excel(df, excel_path)
