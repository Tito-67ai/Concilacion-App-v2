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

from app.services.importador_mayor import leer_mayor, leer_mayor_desde_json
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


def test_la_ruta_mayor_conserva_documento_cuenta_y_organizacion(tmp_path, client):
    """El response_model no puede borrar los campos del Libro Mayor.

    MovimientoMayor no declaraba documento/cuenta/organizacion/descripcion y
    FastAPI los descartaba de la respuesta: el archivo cargado con el boton
    "Libro Mayor" llegaba a la pantalla sin Documento ni Cuenta y el FO 02-03
    salia con las columnas B y C vacias.
    """
    ruta = _xlsx(
        tmp_path / "mayor_contable.xlsx",
        ["Fecha", "Documento", "Cuenta", "Organización", "Descripción", "Debe", "Haber"],
        [
            [
                "01/07/2026",
                "Movimiento de Fondos N 952",
                "1.1.1.2.01 I.C.B.C. Bank",
                "FUSION MKT S.R.L.",
                "RESCATE FCI.",
                32000000,
                None,
            ]
        ],
    )

    fila = _subir_mayor(client, ruta).json()["datos"][0]

    assert fila["documento"] == "Movimiento de Fondos N 952"
    assert fila["cuenta"] == "1.1.1.2.01 I.C.B.C. Bank"
    assert fila["organizacion"] == "FUSION MKT S.R.L."
    # "Descripción" cae en la columna del detalle (concepto): el papel de trabajo
    # escribe descripcion o concepto, asi que el texto no se pierde.
    assert fila["concepto"] == "RESCATE FCI."


def test_el_encabezado_organizacion_con_tilde_se_reconoce(tmp_path):
    """El export del contable nombra la columna "Organización", con tilde.

    El traductor compara sin acentos, pero ORGANIZACION no estaba entre los
    alias, asi que la columna H del papel de trabajo salia siempre vacia.
    """
    ruta = _xlsx(
        tmp_path / "mayor_org.xlsx",
        ["Fecha", "Detalle", "Organización", "Debe", "Haber"],
        [["01/07/2026", "Pago a proveedor", "FUSION MKT S.R.L.", None, 1000]],
    )

    mov = leer_mayor(str(ruta)).datos[0]

    assert mov["organizacion"] == "FUSION MKT S.R.L."


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


# --------------------------------------------------------------------------
# Libro Mayor por la via web de Xubio (la grilla del webreport como JSON)
# --------------------------------------------------------------------------


def test_lee_el_json_del_webreport_con_las_claves_p_():
    """El webreport contesta la grilla como JSON con las columnas del reporte
    (p_Fecha, p_...). Se reusa el mismo traductor de encabezados que el
    archivo: lo unico propio es sacar el prefijo 'p_' antes de traducir."""
    datos = {
        "data": [
            {"p_Fecha": "2026-07-01", "descripcion": "Pago a proveedor", "debe": 0.0, "haber": 1000.0},
            {"p_Fecha": "2026-07-02", "descripcion": "Ingreso por alquiler", "debe": 500.0, "haber": 0.0},
        ],
        "total": 2,
    }

    lectura = leer_mayor_desde_json(datos)

    assert lectura.convencion == "contable"
    assert [m["concepto"] for m in lectura.datos] == ["Pago a proveedor", "Ingreso por alquiler"]
    assert [m["fecha"].isoformat() for m in lectura.datos] == ["2026-07-01", "2026-07-02"]
    assert (lectura.datos[1]["debe"], lectura.datos[1]["haber"]) == (500.0, 0.0)


def test_lee_el_json_cuando_viene_la_lista_sola():
    """La grilla puede llegar como lista de primer nivel y con los nombres ya
    en castellano: no hay que atarse a una sola forma."""
    lectura = leer_mayor_desde_json(
        [{"Fecha": "2026-07-01", "Descripcion": "Cobro", "Debe": 900.0, "Haber": 0.0}]
    )

    assert len(lectura.datos) == 1
    assert lectura.datos[0]["debe"] == 900.0
    assert lectura.datos[0]["concepto"] == "Cobro"


def test_un_json_sin_columnas_conocidas_dice_que_columnas_habia():
    """Sin columnas de fecha/importe no se inventa nada: el error nombra las
    claves que trajo la grilla, que es lo unico para corregir el mapeo."""
    with pytest.raises(ErrorDeExtraccion) as excim:
        leer_mayor_desde_json({"data": [{"color": "rojo", "medida": 3}]})

    assert "color" in str(excim.value)


def test_un_json_sin_filas_lo_dice():
    with pytest.raises(ErrorDeExtraccion):
        leer_mayor_desde_json({"data": []})


# --------------------------------------------------------------------------
# El webreport real: XML con los 43 campos de la grilla
# --------------------------------------------------------------------------
#
# El XML tiene <fields> (metadatos) y <data> (CSV con ; de fila y , de campo).
# Los campos que el Libro Mayor del papel de trabajo necesita (Documento,
# Cuenta, Organizacion, Descripcion) salen de DOCUMENTO/CUENTA/ORGANIZACION/
# DESCRIPCION, no de las columnas de importe.

CAMPOS_WEBREPORT = [
    "FECHA", "ORDERID", "DOCUMENTO", "CUENTA", "MONEDA", "DEBEMONPRINCIPAL",
    "HABERMONPRINCIPAL", "SALDOMONPRINCIPAL", "DESCRIPCION", "ORGANIZACION",
    "ASIENTOITEMID", "TRANSACCIONID", "ORGANIZACIONID", "CENTRODECOSTOID",
    "CENTRODECOSTO", "CUIT", "CUENTAID", "CUENTACODIGO", "COMPROBANTE",
    "MONEDAID", "DEBEMONSECUNDARIA", "HABERMONSECUNDARIA", "SALDOMONSECUNDARIA",
    "DEBEMONTRANSACCION", "HABERMONTRANSACCION", "SALDOMONTRANSACCION",
    "DEBE", "HABER", "SALDO", "@@CLASEVO", "@@FORMXML", "ANO", "ANOMES",
    "EMPRESA", "DETALLE", "IMPORTEOPERACIONPPAL", "IMPORTEOPERACIONSEC",
    "IMPORTEOPERACIONTRANS", "CUENTARAMA1", "CUENTARAMA2", "CUENTARAMA3",
    "CUENTARAMAN", "USRCODE",
]


def _fila_webreport(**valores) -> list[str]:
    """Una fila del CSV del webreport con solo los campos que el test usa."""
    fila = {campo: "" for campo in CAMPOS_WEBREPORT}
    fila.update(valores)
    return [fila[campo] for campo in CAMPOS_WEBREPORT]


def _xml_webreport(filas) -> str:
    fields = "".join(f'<field name="{n}" />' for n in CAMPOS_WEBREPORT)
    data = "".join("PK," + ",".join(f) + ";" for f in filas)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<root><dataset><firstfieldPK>1</firstfieldPK>"
        f"<fields>{fields}</fields><data>{data}</data>"
        "</dataset></root>"
    )


def test_webreport_extrae_documento_cuenta_y_organizacion():
    xml = _xml_webreport([
        _fila_webreport(
            FECHA="2026-07-01",
            DOCUMENTO="Movimiento de Fondos N 952",
            CUENTA="1.1.1.2.01 I.C.B.C. Bank",
            DESCRIPCION="RESCATE FCI.",
            ORGANIZACION="FUSION MKT S.R.L.",
            DEBEMONPRINCIPAL="32000000",
            DEBE="32000000",
            CUENTACODIGO="1.1.1.2.01",
            COMPROBANTE="X-0001-00004519",
        )
    ])

    mov = leer_mayor_desde_json(xml).datos[0]

    assert mov["documento"] == "Movimiento de Fondos N 952"
    assert mov["cuenta"] == "1.1.1.2.01 I.C.B.C. Bank"
    assert mov["organizacion"] == "FUSION MKT S.R.L."
    assert mov["descripcion"] == "RESCATE FCI."
    assert mov["debe"] == 32000000.0


def test_webreport_cuenta_cae_al_codigo_cuando_no_hay_display():
    """Si el webreport no llena CUENTA, el codigo contable es mejor que nada."""
    xml = _xml_webreport([
        _fila_webreport(
            FECHA="2026-07-02",
            DEBEMONPRINCIPAL="1",
            DEBE="1",
            CUENTACODIGO="1.1.1.2.01",
        )
    ])

    assert leer_mayor_desde_json(xml).datos[0]["cuenta"] == "1.1.1.2.01"


def test_las_celdas_vacias_no_se_escriben_como_nan():
    """pandas deja NaN en las celdas vacias y str(NaN) == 'nan': sin filtrarlo,
    la Descripcion del Libro Mayor salia con la cadena 'nan'."""
    import numpy as np

    from app.services.importador_mayor import _desde_dataframe

    df = pd.DataFrame([
        {
            "FECHA": "2026-07-02",
            "DEBE": 500,
            "HABER": 0,
            "DETALLE": np.nan,
            "DOCUMENTO": np.nan,
            "CUENTA": np.nan,
            "ORGANIZACION": np.nan,
            "DESCRIPCION": np.nan,
        }
    ])

    mov = _desde_dataframe(df).datos[0]

    assert mov["concepto"] == ""
    assert mov["descripcion"] is None
    assert mov["documento"] is None
    assert mov["cuenta"] is None
    assert mov["organizacion"] is None
