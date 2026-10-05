"""Genera los PDF de muestra que usan los tests, en backend/muestras/.

Por que PDF sinteticos y no los extractos reales: el repo es publico, y un
extracto bancario lleva CBU, CUIT, cuenta y movimientos reales de la empresa.

Cada fixture reproduce la estructura que hizo fallar a su parser:

- santander.pdf: las mismas columnas, fechas dd-mm sin ano, signo pegado al
  final, codigos de 3 y 4 digitos, saltos de pagina con SALDO PAGINA ANTERIOR,
  pie de pagina con papeleria del banco. Mantiene los MISMOS importes que el
  extracto real, asi los tests afirman sobre 133 movimientos y 556.238,11.

- icbc.pdf: mismo layout del portal "reportes" pero con importes INVENTADOS,
  para no publicar los movimientos de la empresa. Cubre el pie que identifica
  al banco, el TOT.IMP.LEY COMP. y el SALDO FINAL que cierra la cuenta.

Uso:  python -m tests.generar_muestras   (desde backend/)
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

MUESTRAS = Path(__file__).resolve().parent.parent / "muestras"

# (modulo de datos, nombre del PDF)
FIXTURES = [
    ("tests.datos_santander", "santander.pdf"),
    ("tests.datos_icbc", "icbc.pdf"),
]


def construir(destino: Path, paginas):
    c = canvas.Canvas(str(destino), pagesize=A4)

    for lineas in paginas:
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


def _lineas_de_movimiento(linea):
    """Una linea de movimiento arranca con dd-mm y trae un importe con signo."""
    return len(linea) > 5 and linea[2] == "-" and linea[5] == " "


if __name__ == "__main__":
    from importlib import import_module

    MUESTRAS.mkdir(exist_ok=True)

    for nombre_modulo, nombre_pdf in FIXTURES:
        modulo = import_module(nombre_modulo)
        destino = MUESTRAS / nombre_pdf
        construir(destino, modulo.PAGINAS)

        movimientos = sum(
            1
            for pagina in modulo.PAGINAS
            for linea in pagina
            if _lineas_de_movimiento(linea)
        )
        print(f"{nombre_pdf}: {len(modulo.PAGINAS)} paginas, {movimientos} movimientos")