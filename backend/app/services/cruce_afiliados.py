import re
import unicodedata

# Formas en que suele aparecer un CUIT en el texto de un movimiento:
# "30-71615408-0" o "30716154080".
_CUIT_PATRON = re.compile(r"\b\d{2}-\d{8}-\d\b|\b\d{11}\b")


def normalizar_afiliado(texto: str | None) -> str:
    """
    Mayusculas, sin tildes, sin puntuacion y espacios colapsados.

    "Compañia Argentina de Marketing Directo S.A." -> "COMPANIA ARGENTINA DE
    MARKETING DIRECTO SA". Asi el texto del extracto y el nombre de Xubio se
    pueden comparar aunque uno traiga tildes y el otro no, o difieran en un
    punto. Los puntos NO separan palabras ("S.A." queda "SA"), porque el
    extracto casi nunca los escribe y si separaran, "EMPRESA SA" nunca
    emparejaria con "EMPRESA S.A.".
    """
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.upper()
    texto = texto.replace(".", "")
    return re.sub(r"[^A-Z0-9]+", " ", texto).strip()


def _cuit_normalizado(texto: str | None) -> str:
    if not texto:
        return ""
    return re.sub(r"\D", "", texto)


def cruzar_movimientos_con_afiliados(movimientos, afiliados) -> list[dict]:
    """
    Marca cada movimiento del banco con el afiliado de Xubio que lo pago.

    Devuelve una entrada POR movimiento, en el mismo orden que la lista de
    entrada:

        {"indice": i, "afiliado": {...} | None, "metodo": "cuit"|"nombre"|None}

    El CUIT manda por encima del nombre: si el texto de la fila trae un CUIT
    que existe en la lista, ese emparejamiento es directo. Si no, se busca el
    nombre normalizado del afiliado dentro del texto normalizado del
    movimiento. Cuando dos nombres encajan, gana el mas largo (el mas
    especifico): asi "CONSORCIO CARACAS 4641 DTO B" no se empareja con
    "CONSORCIO CARACAS 4641".
    """
    por_cuit: dict[str, dict] = {}
    nombres: list[tuple[str, dict]] = []
    for afiliado in afiliados:
        cuit = _cuit_normalizado(afiliado.get("cuit"))
        if cuit:
            por_cuit.setdefault(cuit, afiliado)
        nombre = normalizar_afiliado(afiliado.get("organizacionNombre"))
        if nombre:
            nombres.append((nombre, afiliado))
    nombres.sort(key=lambda t: len(t[0]), reverse=True)

    resultado = []
    for i, movimiento in enumerate(movimientos):
        entrada: dict = {"indice": i, "afiliado": None, "metodo": None}

        texto_crudo = movimiento.concepto or ""
        if getattr(movimiento, "referencia", None):
            texto_crudo += " " + (movimiento.referencia or "")
        texto_normalizado = normalizar_afiliado(texto_crudo)

        encontrado = None
        for parte in _CUIT_PATRON.findall(texto_crudo):
            candidato = por_cuit.get(_cuit_normalizado(parte))
            if candidato:
                encontrado = (candidato, "cuit")
                break

        if encontrado is None:
            for nombre, candidato in nombres:
                if nombre and nombre in texto_normalizado:
                    encontrado = (candidato, "nombre")
                    break

        if encontrado is not None:
            entrada["afiliado"], entrada["metodo"] = encontrado

        resultado.append(entrada)

    return resultado