import os
import re
import pandas as pd

# Regex de numeros bankers: separador de miles '.' y decimal ',' (formato argentino)
_RE_NO_NUMERICO = re.compile(r"[^\d.,+-]")
_RE_SEPARADORES = re.compile(r"[^\d.,-]")


def es_numero_bancario(s) -> bool:
    """True si el texto es un numero (con o sin signo, moneda o separadores)."""
    if s is None:
        return False
    solo_numeros = _RE_NO_NUMERICO.sub("", str(s).strip())
    solo_numeros = solo_numeros.lstrip("+-").replace(".", "").replace(",", "")
    return bool(solo_numeros) and solo_numeros.isdigit()


def limpiar_numero(s, es_formato_ingles: bool = False) -> float:
    """
    Convierte un importe escrito como lo imprime el banco a float.

    Acepta las dos convenciones que aparecen en los PDF:
      - '1.234,56'  -> 1234.56   (punto de miles, coma decimal)
      - '1,234.56'  -> 1234.56   (coma de miles, punto decimal)

    Sabe manejar signos y simbolos pegados al numero: '-$ 29.000,00' -> -29000.0

    es_formato_ingles=True le dice que en ese PDF el punto es el separador
    decimal y la coma es el de miles ('-49728.18', '1,234.56'). Sin el flag se
    autodetecta el separador mirando cual de los dos aparece mas a la derecha.
    """
    if s is None:
        return 0.0
    if isinstance(s, (int, float)):
        # pandas mete los vacios como float nan: los tratamos como 'sin valor'
        try:
            if s != s:
                return 0.0
        except Exception:
            return 0.0
        return float(s)

    texto = _RE_SEPARADORES.sub("", str(s).strip())
    if not texto or texto in ("-", "+", ".", ",", "-.", "+."):
        return 0.0

    negativo = texto.startswith("-")
    texto = texto.lstrip("+-")

    if es_formato_ingles:
        # La coma es de miles y el punto es decimal
        texto = texto.replace(",", "")
    elif "," in texto and "." in texto:
        # El separador decimal es el que aparece mas a la derecha
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    elif texto.count(".") > 1:
        texto = texto.replace(".", "")

    try:
        valor = float(texto)
    except ValueError:
        digitos = re.sub(r"[^\d.]", "", texto)
        try:
            valor = float(digitos) if digitos not in ("", ".") else 0.0
        except ValueError:
            return 0.0

    return -valor if negativo else valor


def guardar_excel(df, excel_path):
    """Escribe el DataFrame en disco. Devuelve (ok, ruta_o_error) sin tragarse la excepcion."""
    try:
        carpeta = os.path.dirname(excel_path)
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        df.to_excel(excel_path, index=False)
        return True, excel_path
    except Exception as e:
        return False, f"No se pudo escribir {excel_path}: {e}"


class TrackerSaldo:
    """
    Lleva el saldo de la cuenta para deducir si cada importe resta o suma.

    Los extractoresparsers el PDF en dos columnas (importe y saldo final de la linea).
    La unica forma fiable de saber el signo es probar contra el saldo anterior:

        saldo_linea == saldo_anterior - importe  ->  DEBE (sale plata)
        saldo_linea == saldo_anterior + importe  ->  HABER (entra plata)

    Las diferencias hasta `tolerancia` se consideran redondeo del banco.
    """

    TOLERANCIA = 0.05

    def __init__(self, tolerancia: float = TOLERANCIA):
        self.saldo = 0.0
        self.tolerancia = tolerancia
        self.iniciado = False
        self.descartes = 0

    def iniciar(self, saldo_inicial: float) -> None:
        """Fija el saldo de partida de la cuenta (el 'SALDO INICIAL' del PDF)."""
        self.saldo = float(saldo_inicial or 0.0)
        self.iniciado = True
        self.descartes = 0

    @property
    def saldo_actual(self) -> float:
        return self.saldo

    def identificar_movimiento(self, importe: float, saldo_linea: float):
        """
        Devuelve 'DEBE', 'HABER' o None si la linea no cuadra con el saldo.

        Cuando puede determinarlo avanza el tracker hasta `saldo_linea`.
        Cuando no, NO avanza el saldo: asi la linea siguiente sigue
        comparandose contra el ultimo saldo bueno y no se pierde la cuenta.
        Devolver None en vez de adivinar es lo que evita marcar un debito
        como si fuera un haber.
        """
        if not self.iniciado:
            raise RuntimeError(
                "TrackerSaldo: hay que llamar iniciar() antes de identificar_movimiento()"
            )

        importe = abs(float(importe))
        saldo_linea = float(saldo_linea)

        if abs((self.saldo - importe) - saldo_linea) < self.tolerancia:
            self.saldo = saldo_linea
            return "DEBE"
        if abs((self.saldo + importe) - saldo_linea) < self.tolerancia:
            self.saldo = saldo_linea
            return "HABER"

        self.descartes += 1
        return None