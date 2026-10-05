"""
Extractor generico de PDF: el ultimo recurso cuando el banco no tiene un parser
propio, o cuando el parser propio abrio el PDF pero no encontro movimientos.

Un extractor por banco se rompe apenas el banco cambia una coma en el PDF. Este
modulo no depende del banco: mira la forma de la linea.

    <fecha> <detalle> <importe(s)> [<saldo>]

Y se apoya en dos cosas que hacen la diferencia entre leer un extracto y leer un
PDF:

1. La cadena de saldos (TrackerSaldo). Muchos bancos imprimen los importes en
   valor absoluto y el signo va en una columna aparte. La unica forma fiable de
   saber si un movimiento suma o resta es probar contra el saldo de la linea
   anterior, que es lo que ya hace el resto del sistema.

2. Descarte de la papeleria. Entre dos movimientos hay logotipos rotos en ASCII,
   "TOTAL", numeros de pagina, textos legales y "Este resumen no tiene valor
   contable". Sin filtrarlos, cada importacion suma 5 o 10 movimientos falsos.
"""

import logging
import re

import pandas as pd
import pdfplumber

from app.services.Tools import (
    TrackerSaldo,
    es_numero_bancario,
    guardar_excel,
    limpiar_numero,
)

logger = logging.getLogger(__name__)

# Fecha al comienzo del token: 10/02/2026, 2026-02-10, 10.02.26
RE_FECHA = re.compile(r"^\d{1,4}[-/.]\d{1,2}([-/.]\d{2,4})?$")

# Papeleria del banco: encabezados, totales, pie de pagina, avisos legales.
# Va anclado al inicio de la linea, asi que un movimiento legitimo no se
# pisa nunca: los movimientos arrancan con la fecha, no con estas palabras.
RE_BASURA = re.compile(
    r"^\s*("
    r"TOTAL|TOTALES|TOTAL\s+GENERAL|TOTAL\s+CUENTA|"
    r"RESUMEN|RESUMEN\s+DE|SALDO\s+(FINAL|ACTUAL|DISPONIBLE|NUEVO|PROMEDIO)|"
    r"P[ÁA]GINA|HOJA|FECHA\s+DE\s+(DESCARGA|EMISI[ÓO]N)|"
    r"FECHA|FECHA\s+(OPER|DE|FONDO|VALOR|CONTABLE)|"
    r"DEBE|HABER|IMPORTE|MOVIMIENTO|CONCEPTO|DESCRIPCI[ÓO]N|DETALLE|"
    r"D[ÉE]BITO|C[ÉE]R[ÉE]DITO|CANTIDAD|COMPROBANTE|CODIGO|C[ÓO]D\.?|"
    r"NRO\.?|N[º°]\.?\s|N[ÚU]MERO|"
    r"BANCO|CUENTA|CUENTAS|RESUMEN\s+TOTAL|"
    r"Este\s+resumen|Generado|Emitido|El\s+presente|Los\s+datos|Sin\s+valor|"
    r"[ÍI]NDICE|Orden|Banco\s+Galicia|BBVA|Santander|Macro|HSBC|Patrimonio)"
    r"\b",
    re.IGNORECASE,
)

# Ruido que se cuela dentro del detalle y no aporta nada
RE_RUIDO_DETALLE = re.compile(r"^[\s\-*.,:;|]+|[\s\-*.,:;|]+$")

# Las mismas marcas que mira el conversor final. Estas filas no son movimientos:
# son el saldo con el que arranca la cuenta, asi que el numero que traen va en
# la columna SALDO y no como importe.
RE_SALDO_INICIAL = re.compile(
    r"SALDO\s+(INICIAL|ANTERIOR|[ÚU]LTIMO)|SALDO\s+A\s+LA\s+FECHA",
    re.IGNORECASE,
)

# Cuantas filas de una pagina mira el detector de tablas antes de rendirse
FILAS_PARA_BUSCAR_ENCABEZADO = 15


def es_pdf_escaneado(ruta_pdf: str, caracteres_minimos: int = 60) -> bool:
    """
    True si el PDF no tiene texto seleccionable, o sea que es una foto o escaneo.

    Un PDF escaneado abre sin problema pero extract_text() devuelve cadena vacia,
    y ahi el parser no tiene nada que parsear. Mejor decirlo explicitamente que
    devolver cero movimientos sin explicar por que.
    """
    with pdfplumber.open(ruta_pdf) as pdf:
        paginas = list(pdf.pages[:5])
        texto = "".join((pagina.extract_text() or "") for pagina in paginas)

    return len(texto.strip()) < caracteres_minimos


# El periodo del extracto es la unica fuente del ano cuando las fechas van como
# dd-mm: "PERIODO 01-07-2026 AL 31-07-2026" o "01/07/2026 al 31/07/2026".
RE_PERIODO = re.compile(
    r"(?:PER[IÍ]ODO|PERIODO|DESDE)\s+(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})",
    re.IGNORECASE,
)

RE_ANIO_SUELTO = re.compile(r"\b(20\d{2})\b")

# Indica que en el documento las fechas vienen dd-mm (sin ano)
RE_FECHA_ANIO_MAYUS = re.compile(r"\b\d{2}-\d{2}\b(?!-)")


def _anio_del_documento(texto: str):
    """
    Saca el ano del extracto.

    Necesario para los bancos que imprimen las fechas como dd-mm: sin ano, la
    fecha no se puede convertir y todas las filas se descartan.
    """
    match = RE_PERIODO.search(texto)
    if match:
        return int(match.group(3))
    match = RE_ANIO_SUELTO.search(texto)
    return int(match.group(1)) if match else None


def _completar_anio(fecha: str, anio) -> str:
    """
    Le pone el ano a una fecha dd-mm. El resto de los formatos ya lo traen.
    """
    if anio is None:
        return fecha
    if re.fullmatch(r"\d{1,2}[-/.]\d{1,2}", fecha):
        return f"{fecha}-{anio}"
    return fecha


# Numero entero de 3 o 4 digitos sin separador: en la mayoria de los extractos
# son el numero de comprobante, la sucursal o el canal (0543, 0501, 0187), no un
# importe. Los importes siempre vienen con miles o con centavos.
RE_CODIGO_DE_COLUMNA = re.compile(r"^\d{3,4}$")

# Importe con el signo pegado al final, como lo imprime el portal de Santander:
# "55.000,00-" es un debito de 55.000.
RE_IMPORTE_CON_SIGNO_FINAL = re.compile(r"^[\d.,]+[+-]$")

# Un importe es solo numeros, separadores y un signo. No puede tener letras:
# 'TR.4965724' es un numero de comprobante, pero si se le quitan las letras
# queda '.4965724' y se lee como el decimal 0,50. Eso vacia el concepto de la
# fila y descuadra el saldo.
RE_TOKEN_NUMERICO = re.compile(r"^(?=.*\d)[+-]?[\d.,]+[+-]?$")

RE_SIGNO = re.compile(r"^[+-]|[-+]$")


def _limpiar_detalle(detalle) -> str:
    """
    Limpia el concepto: guiones de los bordes y los codigos de columna.

    Muchos bancos meten entre el concepto y los importes un codigo de 4 digitos
    (comprobante, sucursal o canal). No es parte de la cuenta y ensucia lo que
    se muestra en pantalla y lo que despues se busca con fuzzy matching.
    """
    detalle = RE_RUIDO_DETALLE.sub("", str(detalle))
    detalle = re.sub(r"\b0\d{3}\b", " ", detalle)
    detalle = re.sub(r"  +", " ", detalle).strip()
    return detalle


def _es_importe(token) -> bool:
    """
    True si el token es un importe, con signo pegado adelante o al final.

    Los bancos usan las tres formas: "1.500,00", "-1.500,00" y "1.500,00-".
    """
    texto = str(token).strip()
    if not RE_TOKEN_NUMERICO.match(texto):
        return False
    # Todo importe impreso trae miles o centavos. Un entero suelto, sea de 3, 4
    # o 7 digitos, es un dato de referencia: la sucursal (0543), el canal
    # (0187) o el comprobante (0109239). Sin esta regla, "DEBITO TRANSF
    # CONNECTION B 0109239" se leia como un movimiento de 1.092.239.
    if not ("," in texto or "." in texto or RE_SIGNO.search(texto)):
        return False
    if RE_IMPORTE_CON_SIGNO_FINAL.match(texto):
        return True
    return es_numero_bancario(texto)


def _indices_de_importes(partes, desde=0):
    """
    Devuelve los indices de los tokens que son importes de verdad.

    Filtra los codigos de 3-4 digitos sin separador. Sin este filtro, en un
    extracto de Santander la linea

        08-07 IMP S/DEBITOS EN CTA CTE 0543 4,36-

    se lee como "importe 543" y el movimiento real de 4,36 se pierde.
    """
    indices = []
    for i, token in enumerate(partes[desde:], start=desde):
        limpio = str(token).strip().strip(",")
        if RE_CODIGO_DE_COLUMNA.match(limpio):
            continue
        if _es_importe(token):
            indices.append(i)
    return indices


def _armar_fila(partes, desde=1):
    """
    Convierte los tokens de una linea en una fila canonica.

    Devuelve la fila aunque la linea no traiga importes: en ese caso la deja en
    cero y marcada como incompleta, porque hay bancos que dejan el concepto en
    una linea y los numeros en la siguiente. El signo se resuelve despues: si
    hay saldo de la linea, la cadena de saldos tiene mas palabra que el signo.
    """
    indices = _indices_de_importes(partes, desde)

    detalle = " ".join(partes[desde : indices[0]]) if indices else " ".join(partes[desde:])
    detalle = _limpiar_detalle(detalle)
    if not detalle:
        detalle = "Sin concepto"

    fila = {
        "FECHA": partes[0] if desde == 1 else None,
        "DETALLE": detalle,
        "DEBE": 0.0,
        "HABER": 0.0,
        "SALDO": None,
        # El signo impreso se guarda aparte: es el fallback si despues la cadena
        # de saldos no puede confirmar la direccion de la fila.
        "_direccion": "DEBE",
        "_incompleta": not indices,
        "_es_apertura": False,
    }

    if not indices:
        return fila

    # Una fila de saldo inicial trae un solo numero, y ese numero es el saldo
    # con el que abre la cuenta, no un movimiento. Va en SALDO.
    if RE_SALDO_INICIAL.search(detalle) and len(indices) == 1:
        fila["SALDO"] = limpiar_numero(partes[indices[0]])
        fila["_es_apertura"] = True
        fila["_incompleta"] = False
        return fila

    _cargar_importes(fila, partes, indices)
    fila["_incompleta"] = False
    return fila


def _cargar_importes(fila, partes, indices):
    """Pone DEBE, HABER y SALDO en la fila segun los tokens de importe."""
    valores = [limpiar_numero(partes[i]) for i in indices]
    debe, haber, saldo = 0.0, 0.0, None

# Layout A: columnas DEBE y HABER separadas.
    #   10/02 TRANSFERENCIA 0,00 1.500,00 25.000,00
    # El que no se mueve es 0,00 y eso los delata: con un solo importe seguido
    # del saldo, los dos primeros numeros nunca serian ambos 0,00.
    if len(valores) >= 3 and (valores[0] == 0) != (valores[1] == 0):
        debe, haber = valores[0], valores[1]
        saldo = valores[2]
    else:
        # Layout B: un importe (con signo, o con el signo en un token aparte) y
        # despues el saldo.
        #   10/02 TRANSFERENCIA -1.500,00 25.000,00
        #   10/02 TRANSFERENCIA - 1.500,00 25.000,00
        if len(valores) >= 2:
            saldo = valores[-1]
        if valores:
            importe = valores[0]
            if _signo_explicito(partes, indices[0]) is not None:
                importe = abs(importe)
            debe, haber = (
                (abs(importe), 0.0) if importe < 0 else (0.0, abs(importe))
            )

    fila["DEBE"] = debe
    fila["HABER"] = haber
    fila["SALDO"] = saldo
    fila["_direccion"] = "HABER" if haber else "DEBE"


def _signo_explicito(partes, indice_importe):
    """'+ 1.500,00' y '- 1.500,00' con el signo en un token aparte."""
    if indice_importe > 0:
        previo = partes[indice_importe - 1]
        if previo == "+":
            return 1
        if previo == "-":
            return -1
    return None


def _ajustar_direccion_con_saldo(filas):
    """
    Reconfirma DEBE/HABER usando la cadena de saldos.

    Cuando el banco imprime importes en valor absoluto, el signo impreso puede
    ser cualquier cosa. Si el saldo de la linea cierra con una de las dos
    direcciones, esa es la buena y se corrige la fila. Si no cierra con ninguna
    (redondeo del banco, o extracto sin columna de saldo) se respeta el signo
    impreso: adivinar es peor que mostrar la fila sin confirmar.
    """
    tracker = TrackerSaldo()
    for fila in filas:
        saldo = fila.get("SALDO")
        importe = fila.get("DEBE", 0.0) + fila.get("HABER", 0.0)
        if saldo is None:
            continue
        if not tracker.iniciado:
            # La primera fila con saldo no se puede verificar (no hay saldo
            # anterior contra el cual comparar), pero fija la referencia.
            tracker.iniciar(0.0)
            tracker.saldo = float(saldo)
            tracker.iniciado = True
            continue
        if importe <= 0:
            continue

        direccion = tracker.identificar_movimiento(importe, float(saldo))
        if direccion is None:
            continue
        if direccion == "DEBE":
            fila["DEBE"], fila["HABER"] = importe, 0.0
        else:
            fila["DEBE"], fila["HABER"] = 0.0, importe
        fila["_direccion"] = direccion


def _filas_desde_texto(pagina_texto: str, anio=None):
    """
    Extrae filas del texto crudo de una pagina.

    Una linea que arranca con fecha es un movimiento; una linea sin numeros que
    viene despues es la continuacion del concepto (los bancos parten los
    conceptos largos en varias lineas), y una linea con numeros que llega sin
    fila abierta es la segunda parte de ese concepto.
    """
    filas = []
    actual = None

    def cerrar():
        nonlocal actual
        if actual and not actual["_incompleta"]:
            filas.append(actual)
        actual = None

    for linea in pagina_texto.splitlines():
        limpia = linea.strip()
        if not limpia:
            continue

        if RE_BASURA.match(limpia):
            # La papeleria corta el bloque: si venia un concepto partido, ya no
            # sabemos donde terminaba, asi que se cierra.
            cerrar()
            continue

        partes = limpia.split()
        con_importes = bool(_indices_de_importes(partes))

        if RE_FECHA.match(partes[0]):
            # La fila anterior se cierra siempre, haya o no importe en esta
            # linea: si se cuelga, el movimiento anterior se pierde.
            cerrar()
            actual = _armar_fila(partes)
            if actual and actual["FECHA"]:
                actual["FECHA"] = _completar_anio(actual["FECHA"], anio)
            continue

        # Saldo inicial sin fecha: "SALDO INICIAL 1.000.000,00".
        if actual is None and RE_SALDO_INICIAL.search(limpia) and con_importes:
            actual = _armar_fila(partes, desde=0)
            cerrar()
            continue

        # Los importes quedaron en la linea siguiente al concepto:
        #   01/02/2026 TRANSFERENCIA RECIBIDA
        #              DESDE OTRA CUENTA   75.000,00   722.000,00
        # La fila ya tiene fecha y concepto, asi que estos numeros son suyos.
        if actual is not None and actual["_incompleta"] and con_importes:
            indice_importes = _indices_de_importes(partes)
            if not indice_importes:
                # No hay importes claros, anexa el texto al concepto y sigue
                actual["DETALLE"] = f"{actual['DETALLE']} {limpia}".strip()
                continue
            # El texto que precede al primer numero es la cola del concepto.
            detalle = RE_RUIDO_DETALLE.sub(
                "", f"{actual['DETALLE']} {' '.join(partes[:indice_importes[0]])}"
            ).strip()
            if detalle:
                actual["DETALLE"] = detalle
            _cargar_importes(actual, partes, indice_importes)
            actual["_incompleta"] = False
            cerrar()
            continue

        # Continuacion del concepto anterior
        if actual is not None and not con_importes and any(c.isalpha() for c in limpia):
            actual["DETALLE"] = f"{actual['DETALLE']} {limpia}".strip()

    cerrar()

    return filas


def _encabezado_de_tabla(tabla):
    """
    Busca la fila de encabezados de una tabla de pdfplumber y devuelve
    (indice, mapa canonico -> indice de columna).
    """
    from app.services.importador_tablas import _columna_canonica

    for indice, fila in enumerate(tabla[:FILAS_PARA_BUSCAR_ENCABEZADO]):
        mapa = {}
        for i, celda in enumerate(fila):
            canonica = _columna_canonica(celda)
            if canonica and canonica not in mapa:
                mapa[canonica] = i
        if "FECHA" in mapa and ({"DEBE", "HABER"} & set(mapa) or "IMPORTE" in mapa):
            return indice, mapa

    return None, None


def _filas_de_tabla(tabla, mapa, desde, anio=None):
    filas = []
    columnas = max(mapa.values()) if mapa else 0
    for fila in tabla[desde + 1 :]:
        def celda(canonica):
            indice = mapa.get(canonica)
            if indice is None or indice >= len(fila):
                return None
            valor = fila[indice]
            return valor if valor is not None else None

        fecha = celda("FECHA")
        if not fecha or not RE_FECHA.match(str(fecha).strip()):
            continue

        detalle = celda("DETALLE") or celda("CONCEPTO") or "Sin concepto"
        detalle = _limpiar_detalle(detalle) or "Sin concepto"

        def importe(canonica):
            valor = celda(canonica)
            return 0.0 if valor is None else limpiar_numero(valor)

        debe, haber = importe("DEBE"), importe("HABER")
        if not debe and not haber:
            # Columna unica de importe: el signo define la direccion.
            unico = importe("IMPORTE")
            debe, haber = (abs(unico), 0.0) if unico < 0 else (0.0, abs(unico))

        saldo_crudo = celda("SALDO")
        filas.append(
            {
                "FECHA": _completar_anio(str(fecha).strip(), anio),
                "DETALLE": detalle,
                "DEBE": debe,
                "HABER": haber,
                "SALDO": None if saldo_crudo is None else limpiar_numero(saldo_crudo),
                "_direccion": "HABER" if haber else "DEBE",
                "_referencia": celda("REFERENCIA"),
                "_incompleta": False,
                "_es_apertura": False,
            }
        )

    return filas


def _tablas_sin_bordes():
    """
   pdfplumber detecta tablas por las lineas del PDF. Los extractos que se
    descargan del portal del banco muchas veces no tienen ni una, asi que se
    prueba tambien por la disposicion del texto.
    """
    return {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "intersection_tolerance": 5,
    }


def _filas_de_pagina(pagina, anio=None):
    """
    Devuelve las filas de una pagina, usando tablas si el PDF las trae y
    recurriendo al texto cuando no.
    """
    mejor_tablas = []
    for ajustes in (None, _tablas_sin_bordes()):
        try:
            tablas = pagina.extract_tables(ajustes) if ajustes else pagina.extract_tables()
        except Exception as e:
            logger.debug("extract_tables fallo con ajustes %s: %s", ajustes, e)
            continue
        tablas = [t for t in tablas if t]
        if len(tablas) > len(mejor_tablas):
            mejor_tablas = tablas

    filas_de_tabla = []
    for tabla in mejor_tablas:
        indice, mapa = _encabezado_de_tabla(tabla)
        if mapa is None:
            continue
        filas_de_tabla.extend(_filas_de_tabla(tabla, mapa, indice, anio))

    texto = pagina.extract_text() or ""
    filas_de_texto = _filas_desde_texto(texto, anio)

    # No alcanza con contar filas: una tabla puede tener la cantidad correcta de
    # filas y aun asi perder los importes, si la celda de DEBITO cae fuera del
    # recorte y el texto plano la rescata. Por eso se comparan las filas que
    # Traen importe de verdad. Las tablas ganan el empate porque el concepto
    # sale entero y sin numeros pegados.
    con_importe_tabla = sum(
        1 for f in filas_de_tabla if f["DEBE"] or f["HABER"]
    )
    con_importe_texto = sum(
        1 for f in filas_de_texto if f["DEBE"] or f["HABER"]
    )
    if con_importe_tabla >= con_importe_texto:
        return filas_de_tabla
    return filas_de_texto


def extraer_generico(pdf_path, excel_path, log_callback):
    """
    Lee cualquier extracto de PDF y escribe el Excel canonico que espera el
    resto del sistema.

    Mismo contrato que los extractores por banco: devuelve (ok, ruta_o_mensaje).
    """
    try:
        if es_pdf_escaneado(pdf_path):
            log_callback("El PDF no tiene texto seleccionable: parece un escaneo.")
            return (
                False,
                "Este PDF es un escaneo o una foto, asi que no hay texto para leer. "
                "Abri el extracto en el portal del banco y descargalo como PDF de "
                "texto, o pasalo a Excel/CSV. Si el banco solo entrega escaneos, "
                "hay que instalar OCR (Tesseract) y queda pendiente.",
            )

        filas = []
        with pdfplumber.open(pdf_path) as pdf:
            total_pags = len(pdf.pages)

            # El ano se busca en todo el documento, no pagina por pagina: el
            # periodo suele estar solo en la primera.
            texto_documento = "\n".join(
                (p.extract_text() or "") for p in pdf.pages[:3]
            )
            anio = _anio_del_documento(texto_documento)
            fechas_sin_ano = bool(RE_FECHA_ANIO_MAYUS.match(texto_documento))
            if anio and fechas_sin_ano:
                log_callback(f"Año del periodo detectado: {anio}")

            for i, pagina in enumerate(pdf.pages):
                log_callback(f"Motor generico: leyendo pagina {i + 1} de {total_pags}...")
                filas.extend(_filas_de_pagina(pagina, anio))

        filas = _fusionar_duplicados(filas)

        sin_fecha = [f for f in filas if not f.get("FECHA")]
        if sin_fecha and any(not f["_es_apertura"] for f in sin_fecha):
            # Hay filas con importes pero sin fecha. Casi siempre es que las
            # fechas venían dd-mm y no se pudo sacar el año del encabezado.
            sin_anio = any(
                RE_FECHA.match(str(f.get("FECHA") or "")) is None
                and not f["_es_apertura"]
                for f in sin_fecha
            )
            if sin_anio or anio is None:
                return (
                    False,
                    "Se leyeron movimientos pero las fechas no traen año (venen "
                    "como dd-mm) y no se encontró el período del extracto para "
                    "completarlo. Bajalo como Excel/CSV o usá el motor de tu banco.",
                )
            filas = [f for f in filas if f.get("FECHA") or f["_es_apertura"]]

        if not filas:
            return (
                False,
                "Se abrio el PDF pero no se encontro ninguna fila con fecha e "
                "importes. Si el extracto esta en una tabla compleja o el PDF "
                "tiene las columnas en otro orden, proba bajarlo como Excel.",
            )

        log_callback(f"Motor generico: {len(filas)} filas con fecha e importes.")
        _ajustar_direccion_con_saldo(filas)

        df = pd.DataFrame(filas)
        if "_referencia" in df.columns and df["_referencia"].notna().any():
            df["REFERENCIA"] = df.pop("_referencia")
        else:
            if "_referencia" in df.columns:
                df = df.drop(columns=["_referencia"])
        if "_direccion" in df.columns:
            df = df.drop(columns=["_direccion"])

        columnas = ["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"]
        if "REFERENCIA" in df.columns:
            columnas.insert(2, "REFERENCIA")
        df = df[columnas]

        # pandas 3 no escribe un string dentro de una columna float64
        df["SALDO"] = df["SALDO"].astype(object)

        return guardar_excel(df, excel_path)

    except Exception as e:
        logger.exception("Fallo el extractor generico")
        return False, f"Error en el motor generico: {e}"


def _fusionar_duplicados(filas):
    """
    Junta filas que se repiten con la misma fecha e importe.

    Cuando el concepto de una fila arranca en una pagina, el texto partido puede
    generar dos filas con los mismos numeros. Sin esta fusion salen dos
    movimientos de 1.500,00 donde habia uno.
    """
    fusionadas = []
    clave_anterior = None
    for fila in filas:
        clave = (fila["FECHA"], round(fila["DEBE"] + fila["HABER"], 2))
        # Solo se fusiona con la fila inmediatamente anterior: el problema que
        # resuelve es el concepto partido en dos renglones del PDF, que produce
        # dos filas contiguas. Dos movimientos legítimos e iguales pero en fechas
        # distintas tienen claves distintas y no se tocan.
        if clave == clave_anterior and fusionadas:
            previa = fusionadas[-1]
            previa["DETALLE"] = f"{previa['DETALLE']} {fila['DETALLE']}".strip()
            continue
        clave_anterior = clave
        fusionadas.append(fila)
    return fusionadas