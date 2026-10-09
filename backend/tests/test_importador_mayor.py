"""
Tests de la via local: Libro Mayor desde archivo y cruce sin la API de Xubio.

La API de Xubio esta reservada a planes superiores al contratado, asi que el
mayor se trae como archivo exportado desde el navegador. Esta via tiene dos
trampas propias:

  - el mayor no es un banco: ahi el DEBE es la entrada de plata y el HABER la
    salida, al reves que en el extracto. Invertirlos haria que todo el cruce
    fallara en silencio (o peor, que cruzara filas que no son la misma). Y el
    export real de Xubio no siempre es un Libro Mayor: tambien viene como
    "Movimientos de CC" (debito = salida), que va invertido respecto del libro.
  - un contable no siempre exporta la columna de detalle del asiento, asi que
    la busqueda de encabezado no puede exigirla como si hace el extracto.

Ademas se prueba que la respuesta de /conciliacion/cruzar sea la misma que la de
/xubio/cruzar-datos: la pantalla no debe tener dos maneras de leerla.
"""

from pathlib import Path

import pandas as pd
import pytest

from app.services.importador_mayor import leer_mayor
from app.services.procesador_central import ErrorDeExtraccion

# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def _xlsx(ruta, encabezados, filas, con_titulo=False):
    if con_titulo:
        columnas = len(encabezados)
        bloque = [
            ["Libro Mayor - Cuenta 1105-0042"] + [None] * (columnas - 1),
            ["Periodo: 01/09/2026 al 30/09/2026"] + [None] * (columnas - 1),
            [None] * columnas,
            list(encabezados),
        ] + [list(f) for f in filas]
        pd.DataFrame(bloque).to_excel(ruta, index=False, header=False)
    else:
        pd.DataFrame([list(f) for f in filas], columns=list(encabezados)).to_excel(
            ruta, index=False
        )
    return ruta


def _csv(ruta, encabezados, filas, separador=";", encoding="utf-8"):
    with open(ruta, "w", encoding=encoding, newline="") as fh:
        fh.write(separador.join(encabezados) + "\n")
        for fila in filas:
            fh.write(separador.join(str(v) for v in fila) + "\n")
    return ruta


# --------------------------------------------------------------------------
# Lectura del archivo
# --------------------------------------------------------------------------


def test_lee_fecha_detalle_debe_haber(tmp_path):
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["01/09/2026", "Cobro cliente SRL", 15000, None],
         ["02/09/2026", "Pago proveedor", None, 4300]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert len(movimientos) == 2
    assert movimientos[0]["fecha"].isoformat() == "2026-09-01"
    assert movimientos[0]["concepto"] == "Cobro cliente SRL"
    assert movimientos[0]["debe"] == 15000.0
    assert movimientos[0]["haber"] == 0.0
    # El signo del banco es haber - debe; el del mayor es debe - haber. Si este
    # archivo se leyera con la convencion del banco, un cobro entraria como
    # salida y no cruzaria con nada.
    assert movimientos[1]["debe"] == 0.0
    assert movimientos[1]["haber"] == 4300.0


def test_lee_el_numero_de_comprobante_cuando_el_export_lo_trae(tmp_path):
    """La bandeja derecha muestra Fecha/Comprobante/Detalle/Importe: si el
    export del contable trae la columna de comprobante, la fila la conserva."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Comprobante", "Detalle", "Debe", "Haber"],
        [["01/09/2026", "FCA-0001-00000001", "Cobro cliente SRL", 15000, None]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert len(movimientos) == 1
    assert movimientos[0]["comprobante"] == "FCA-0001-00000001"
    assert movimientos[0]["concepto"] == "Cobro cliente SRL"


def test_el_numero_de_comprobante_se_reconoce_en_sus_aliases(tmp_path):
    """El export de Xubio suele llamar a la columna 'Nro comprobante': el
    traductor de encabezados la conoce como COMPROBANTE igual que 'Comprobante'."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Nro comprobante", "Debe", "Haber"],
        [["01/09/2026", "FCA-0001-00000005", 900, None]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert movimientos[0]["comprobante"] == "FCA-0001-00000005"


def test_sin_columna_de_comprobante_la_fila_queda_sin_uno(tmp_path):
    """Un Libro Mayor sin esa columna no inventa numeros: quedar '—' en la
    bandeja es mejor que confundir el comprobante con el detalle."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["01/09/2026", "Cobro cliente SRL", 15000, None]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert movimientos[0]["comprobante"] is None


def test_un_libro_mayor_contable_no_se_toca(tmp_path):
    """Un Libro Mayor de verdad trae 'Debe'/'Haber': ahi el debe es la entrada.
    Solo los movimientos de cuenta (debito = salida) se invierten."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["01/09/2026", "Cobro", 900, None],
         ["02/09/2026", "Pago", None, 300]],
    )

    lectura = leer_mayor(str(ruta))

    assert lectura.convencion == "contable"
    assert [(m["debe"], m["haber"]) for m in lectura.datos] == [
        (900.0, 0.0),
        (0.0, 300.0),
    ]


def test_encabezado_con_titulo_arriba_y_sin_columna_de_detalle(tmp_path):
    """El mayor de un contable puede venir sin DETALLE, que es lo que exige el
    extracto bancario. Sin esta flexibilidad pandas tomaba el titulo como
    encabezado y no quedaba ninguna fila con importe."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Cuenta", "Debe", "Haber"],
        [["05/09/2026", "1105-0042", 900, None]],
        con_titulo=True,
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert len(movimientos) == 1
    assert movimientos[0]["fecha"].isoformat() == "2026-09-05"
    assert movimientos[0]["debe"] == 900.0


def test_columna_importe_unica_el_positivo_es_entrada(tmp_path):
    """Un solo IMPORTE con signo: en el banco positivo es haber, en el mayor es
    debe. Traducirlo al reves cruzaria las filas al lado equivocado."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Concepto", "Importe"],
        [["03/09/2026", "Cobro", 700], ["04/09/2026", "Pago", -250]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert [(m["debe"], m["haber"]) for m in movimientos] == [
        (700.0, 0.0),
        (0.0, 250.0),
    ]


def test_las_filas_sin_importe_y_el_saldo_no_entran(tmp_path):
    """La fila de saldo y las de totales no son movimientos: si entrarian a la
    bandeja de pendientes para siempre, sin par posible."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [
            ["01/09/2026", "SALDO INICIAL", 0, 0],
            ["01/09/2026", "Cobro cliente", 100, None],
            ["30/09/2026", "Totales del periodo", 100, 0],
            [None, "Fila de titulo sin importe", None, None],
        ],
    )

    movimientos = leer_mayor(str(ruta)).datos

    # Totales del periodo tiene importe y si entra: es una fila que una persona
    # puede descartar a mano, y es mejor verla que perderla en silencio.
    assert [m["concepto"] for m in movimientos] == [
        "Cobro cliente",
        "Totales del periodo",
    ]


def test_csv_argentino_con_punto_y_coma(tmp_path):
    ruta = _csv(
        tmp_path / "mayor.csv",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["07/09/2026", "Transferencia recibida", "1.234,56", ""]],
    )

    movimientos = leer_mayor(str(ruta)).datos

    assert len(movimientos) == 1
    assert movimientos[0]["debe"] == pytest.approx(1234.56)


def test_un_extracto_de_cuenta_invierte_los_importes(tmp_path):
    """Xubio exporta 'Movimientos de CC' con los encabezados exactos que el
    usuario trae (Fecha contable, Cod de Concepto, Concepto, Debito/Credito en
    $). Ahi el DEBITO es plata que SALE: el banco te la debita. Sin invertir
    todo el cruce quedaria con el signo dado vuelta y no emparejaria nada.

    De paso se verifica la columna de detalle: "Cod de Concepto" contiene a
    "CONCEPTO" pero "Concepto" es literal, y la literal tiene que ganar. Si
    ganara el codigo, el concepto que se ve y se exporta seria "805" y no
    "CPA. MERPAGO MARKET83"."""
    ruta = _xlsx(
        tmp_path / "movimientos.xlsx",
        ["Fecha contable", "Cod de Concepto", "Concepto", "Debito en $", "Credito en $"],
        [
            ["2026-09-01", 805, "CPA. MERPAGO MARKET83", -51726, None],
            ["2026-09-02", 947, "CRED RESC FCI", None, 6000000],
        ],
    )

    lectura = leer_mayor(str(ruta))

    assert lectura.convencion == "cuenta"
    # La compra (debito) queda como salida...
    assert lectura.datos[0]["concepto"] == "CPA. MERPAGO MARKET83"
    assert lectura.datos[0]["debe"] == 0.0
    assert lectura.datos[0]["haber"] == 51726.0
    # ...y el credito (plata que entra) como entrada.
    assert lectura.datos[1]["debe"] == 6000000.0
    assert lectura.datos[1]["haber"] == 0.0


def test_sin_ninguna_fecha_reconocible_no_devuelve_una_bandeja_eterna(tmp_path):
    """Sin fecha el cruce no tiene como comparar (la tolerancia se mide en
    dias): el archivo se rechaza con el motivo en vez de devolver filas que
    nunca van a cruzarse."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["no-es-fecha", "Cobro", 100, None]],
    )

    with pytest.raises(ErrorDeExtraccion) as excim:
        leer_mayor(str(ruta))

    assert "fecha reconocible" in str(excim.value)


def test_sin_columnas_de_importe_el_error_dice_que_columnas_habia(tmp_path):
    """El unico dato que le sirve al usuario para arreglar el archivo es que
    columnas encontro."""
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Observacion"],
        [["01/09/2026", "algo"]],
    )

    with pytest.raises(ErrorDeExtraccion) as excim:
        leer_mayor(str(ruta))

    assert "Observacion" in str(excim.value)


def test_archivo_que_no_es_un_libro_no_se_come_el_motivo(tmp_path):
    ruta = tmp_path / "mayor.xlsx"
    ruta.write_bytes(b"esto no es un zip de Excel")

    with pytest.raises(ErrorDeExtraccion):
        leer_mayor(str(ruta))


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------


def _subir_mayor(client, ruta: Path):
    return client.post(
        "/api/conciliacion/mayor",
        files={"archivo": (ruta.name, ruta.read_bytes(), "application/octet-stream")},
    )


def test_las_rutas_de_conciliacion_estan_montadas():
    from app.main import app

    rutas = set(app.openapi()["paths"].keys())
    assert "/api/conciliacion/mayor" in rutas
    assert "/api/conciliacion/cruzar" in rutas


def test_la_ruta_mayor_devuelve_las_filas(tmp_path, client):
    ruta = _xlsx(
        tmp_path / "mayor.xlsx",
        ["Fecha", "Detalle", "Debe", "Haber"],
        [["01/09/2026", "Cobro cliente", 15000, None]],
    )

    r = _subir_mayor(client, ruta)

    assert r.status_code == 200
    assert r.json()["exito"] is True
    assert r.json()["cantidad_movimientos"] == 1
    assert r.json()["convencion"] == "contable"
    assert r.json()["datos"][0]["fecha"] == "2026-09-01"
    assert r.json()["datos"][0]["debe"] == 15000.0


def test_la_ruta_mayor_reporta_la_convencion_de_cuenta(tmp_path, client):
    """El archivo real de Xubio es 'Movimientos de CC', no un Libro Mayor: la
    pantalla tiene que enterarse para poder mostrarlo y no confundir una
    convencion con la otra."""
    ruta = _xlsx(
        tmp_path / "movimientos.xlsx",
        ["Fecha contable", "Concepto", "Debito en $", "Credito en $"],
        [["2026-09-01", "COMPRA EN KOBO", -51726, None]],
    )

    r = _subir_mayor(client, ruta)

    assert r.status_code == 200
    assert r.json()["convencion"] == "cuenta"
    # El debito es salida para el banco: en el mayor queda como haber.
    assert r.json()["datos"][0]["haber"] == 51726.0


def test_un_mayor_de_movimientos_de_cuenta_cruza_contra_el_extracto(tmp_path, client):
    """El caso real de punta a punta: se sube el mayor en formato de cuenta y se
    cruza contra el extracto del banco. El debito del banco (COMPRA, 51726) y el
    debito del mayor son LA MISMA operacion: tienen que emparejar."""
    ruta = _xlsx(
        tmp_path / "movimientos.xlsx",
        ["Fecha contable", "Concepto", "Debito en $", "Credito en $"],
        [["2026-09-01", "COMPRA EN KOBO", -51726, None]],
    )
    lectura = leer_mayor(str(ruta))

    r = client.post(
        "/api/conciliacion/cruzar",
        json={
            "movimientos_banco": [
                {
                    "fecha": "2026-09-01",
                    "concepto": "COMPRA EN KOBO",
                    "debe": 51726.0,
                    "haber": 0.0,
                    "saldo": 100000.0,
                }
            ],
            "movimientos_xubio": [
                {
                    "fecha": m["fecha"].isoformat() if m["fecha"] else None,
                    "concepto": m["concepto"],
                    "debe": m["debe"],
                    "haber": m["haber"],
                }
                for m in lectura.datos
            ],
        },
    )

    assert r.status_code == 200
    assert r.json()["resumen"]["pares_encontrados"] == 1
    assert len(r.json()["tablas"]["conciliados"]) == 1


def test_la_ruta_mayor_rechaza_otro_formato(tmp_path, client):
    ruta = tmp_path / "mayor.pdf"
    ruta.write_bytes(b"%PDF-1.4")

    r = _subir_mayor(client, ruta)

    assert r.status_code == 422
    assert ".xlsx" in r.json()["detail"]


def test_con_cruce_empareja_un_cobro_del_banco_con_un_debe_del_mayor(client):
    """El objetivo de toda esta via: el cobro del extracto contra el asiento del
    sistema, sin tocar la API de nadie."""
    r = client.post(
        "/api/conciliacion/cruzar",
        json={
            "movimientos_banco": [
                {
                    "fecha": "2026-09-01",
                    "concepto": "COBRO CLIENTE SRL",
                    "debe": 0.0,
                    "haber": 15000.0,
                    "saldo": 15000.0,
                },
                {
                    "fecha": "2026-09-02",
                    "concepto": "PAGO PROVEEDOR",
                    "debe": 4300.0,
                    "haber": 0.0,
                    "saldo": 10700.0,
                },
            ],
            "movimientos_xubio": [
                {"fecha": "2026-09-01", "concepto": "Cobro cliente SRL", "debe": 15000.0, "haber": 0.0},
                {"fecha": "2026-09-02", "concepto": "Pago proveedor", "debe": 0.0, "haber": 4300.0},
                {"fecha": "2026-09-15", "concepto": "Sobresueldo", "debe": 8000.0, "haber": 0.0},
            ],
        },
    )

    assert r.status_code == 200
    cuerpo = r.json()
    # Misma forma que /xubio/cruzar-datos, para que la pantalla no tenga dos
    # maneras de leer el resultado.
    assert set(cuerpo) == {"exito", "resumen", "tablas"}
    assert len(cuerpo["tablas"]["conciliados"]) == 2
    assert len(cuerpo["tablas"]["pendientes_banco"]) == 0
    assert len(cuerpo["tablas"]["pendientes_xubio"]) == 1
    assert cuerpo["resumen"]["pares_encontrados"] == 2


def test_con_cruce_sin_mayor_no_se_pasa_de_largo(client):
    r = client.post(
        "/api/conciliacion/cruzar",
        json={
            "movimientos_banco": [
                {"fecha": "2026-09-01", "concepto": "X", "debe": 0.0, "haber": 1.0, "saldo": 1.0}
            ],
            "movimientos_xubio": [],
        },
    )

    assert r.status_code == 400
    assert "Libro Mayor" in r.json()["detail"]


def test_con_cruce_sin_extracto_no_se_pasa_de_largo(client):
    r = client.post(
        "/api/conciliacion/cruzar",
        json={"movimientos_banco": [], "movimientos_xubio": [{"fecha": "2026-09-01", "debe": 1.0}]},
    )

    assert r.status_code == 400
    assert "extracto" in r.json()["detail"]
