"""Genera backend/muestras/santander.pdf, el PDF que usan los tests.

Por que un PDF sintetico y no el extracto real: el repo es publico, y un
extracto bancario lleva CBU, CUIT, cuenta y movimientos reales de la empresa.
Este fixture reproduce la misma estructura que hizo fallar al parser (las
mismas columnas, fechas dd-mm sin ano, signo pegado al final, codigos de 3 y 4
digitos, saltos de pagina con SALDO PAGINA ANTERIOR, pie de pagina con papeleria
del banco) y mantiene los MISMOS importes, asi que los tests pueden seguir
afirmando sobre 133 movimientos y el saldo final de 556.238,11.

Uso:  python -m tests.generar_muestras   (desde backend/)
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from tests.datos_santander import PAGINAS

SALIDA = Path(__file__).resolve().parent.parent / "muestras" / "santander.pdf"


def construir(destino: Path):
    c = canvas.Canvas(str(destino), pagesize=A4)

    for lineas in PAGINAS:
        y = 800.0
        for linea in lineas:
            # Courier 6.5 entra las lineas largas del pie de pagina sin cortar.
            c.setFont("Courier", 6.5)
            c.drawString(28, y, linea)
            y -= 8.2
            if y < 40:
                break
        c.showPage()

    c.save()


if __name__ == "__main__":
    SALIDA.parent.mkdir(exist_ok=True)
    construir(SALIDA)
    movimientos = sum(
        1
        for pagina in PAGINAS
        for linea in pagina
        if len(linea) > 5 and linea[2] == "-" and linea[5] == " "
    )
    print(f"{len(PAGINAS)} paginas, {movimientos} movimientos -> {SALIDA}")
