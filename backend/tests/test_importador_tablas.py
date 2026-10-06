"""
Tests de la importacion por tabla (xlsx / csv).

El PDF ya tenia cobertura; el Excel es el camino nuevo y tiene sus propias
trampas:

  - los Excel del portal del banco no usan FECHA/DETALLE/DEBE/HABER, sino
    "Fecha operacion", "Descripcion", "Debito", "Credito"
  - arrancan con titulo, cuenta y periodo antes de la tabla, asi que pandas
    tomaba esa linea como encabezado y todas las columnas quedaban con nombre
    numerico
  - hay bancos que traen una sola columna IMPORTE con el signo ya puesto (MP)
  - los CSV vienen en cp1252 y separados por ';', y algunos en formato ingles

Cada caso que se rompio deberia tener un test que lo vuelva a romper.
"""

from datetime import date
from pathlib import Path
import re

import pandas as pd
import pytest

from app.api.rutas.extractos import FORMATOS
from app.services.importador_tablas import (
    _columna_canonica,
    normalizar_columnas,
    procesar_tabla,
)
from app.services.procesador_central import ErrorDeExtraccion, _df_to_movimientos

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
            ["Extracto BBVA - Cuenta 001-022603/4"] + [None] * (columnas - 1),
            ["Periodo: 01/07/2026 al 31/07/2026"] + [None] * (columnas - 1),
            [None] * columnas,
            list(encabezados),
        ] + [list(f) for f in filas]
        pd.DataFrame(bloque).to_excel(ruta, index=False, header=False)
    else:
        # columns=encabezados es obligatorio: sin esto pandas escribe una fila
        # extra con 0,1,2,3 en el Excel y el archivo de prueba no se parece en
        # nada a lo que baja el banco.
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
# Reconocimiento de encabezados
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encabezado, canonico",
    [
        ("FECHA", "FECHA"),
        ("Fecha", "FECHA"),
        ("Fecha operacion", "FECHA"),
        ("FECHA DE OPERACIÓN", "FECHA"),
        ("Fecha movimiento", "FECHA"),
        ("DETALLE", "DETALLE"),
        ("Concepto", "DETALLE"),
        ("Descripción", "DETALLE"),
        ("Glosa", "DETALLE"),
        ("DEBE", "DEBE"),
        ("Débito", "DEBE"),
        ("HABER", "HABER"),
        ("Crédito", "HABER"),
        ("Importe", "IMPORTE"),
        ("Monto", "IMPORTE"),
        ("Saldo", "SALDO"),
        ("Nro. comprobante", "REFERENCIA"),
        ("NRO OPERACION", "REFERENCIA"),
    ],
)
def test_reconoce_los_encabezados_de_los_bancos(encabezado, canonico):
    assert _columna_canonica(encabezado) == canonico


def test_no_inventa_columnas_que_no_conoce():
    assert _columna_canonica("Cantidad de cheques") is None
    assert _columna_canonica("Codigo de sucursal") is None
    assert _columna_canonica("") is None
    assert _columna_canonica(None) is None


def test_normalizar_columnas_no_pisa_dos_veces_la_misma():
    # "Fecha operacion" y "Fecha" mapean las dos a FECHA: gana la primera y la
    # segunda se deja como estaba, para no perder datos ni romper el rename.
    df = pd.DataFrame(columns=["Fecha operacion", "Fecha", "Debito", "Credito"])
    resultado = normalizar_columnas(df)
    assert list(resultado.columns).count("FECHA") == 1


# --------------------------------------------------------------------------
# Lectura de xlsx
# --------------------------------------------------------------------------


def test_xlsx_con_los_nombres_canonicos_entra_tal_cual(tmp_path):
    """El Excel que escriben los extractores ya usa FECHA/DETALLE/DEBE/HABER."""
    ruta = _xlsx(
        tmp_path / "bbva.xlsx",
        ["CUENTA", "FECHA", "DETALLE", "DEBE", "HABER", "SALDO"],
        [
            ["1", "INICIO", "SALDO INICIAL", 0, 0, 1000.0],
            ["1", "02/07/2026", "Pago luz", 400.0, 0, 0],
            ["1", "03/07/2026", "Cobro cliente", 0, 250.0, 0],
        ],
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    # La fila de saldo inicial siembra la cadena pero no sale como movimiento:
    # con DEBE y HABER en cero nunca cruzaria con Xubio. Lo que importa aca es
    # que la cadena de saldos cierre desde 1000 y que las fechas se lean bien.
    assert [m.concepto for m in movimientos] == [
        "Pago luz",
        "Cobro cliente",
    ]
    assert movimientos[0].fecha == date(2026, 7, 2)
    assert movimientos[0].saldo == pytest.approx(600.0)
    assert movimientos[1].saldo == pytest.approx(850.0)
    # El saldo de apertura se deduce del primer movimiento.
    primero = movimientos[0]
    assert primero.saldo + primero.debe - primero.haber == pytest.approx(1000.0)


def test_columnas_del_portal_bancario_se_normalizan(tmp_path):
    """Con los nombres crudos del portal la tabla se leia vacia."""
    ruta = _xlsx(
        tmp_path / "portal.xlsx",
        ["Fecha operacion", "Descripción", "Débito", "Crédito", "Nro. comprobante"],
        [
            ["02/07/2026", "Pago luz", "400,50", "", "12345"],
            ["03/07/2026", "Cobro cliente", "", "250,25", "12346"],
        ],
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert len(movimientos) == 2
    assert movimientos[0].debe == pytest.approx(400.50)
    assert movimientos[0].referencia == "12345"
    assert movimientos[1].haber == pytest.approx(250.25)


def test_titulos_antes_del_encabezado_no_rompen_la_lectura(tmp_path):
    """
    Los Excel del portal arrancan con titulo, cuenta y periodo antes de la tabla.
    Si pandas toma esa primera fila como encabezado, todas las columnas quedan
    con nombre numerico y la importacion devuelve cero movimientos.
    """
    ruta = _xlsx(
        tmp_path / "portal_con_titulo.xlsx",
        ["Fecha operacion", "Descripción", "Débito", "Crédito"],
        [
            ["02/07/2026", "Pago luz", "400,50", ""],
            ["03/07/2026", "Cobro cliente", "", "250,25"],
        ],
        con_titulo=True,
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert [m.concepto for m in movimientos] == ["Pago luz", "Cobro cliente"]
    assert movimientos[0].debe == pytest.approx(400.50)


def test_columna_importe_con_signo_sirve():
    """
    MP trae una sola columna IMPORTE con el signo puesto. Sin tomar ese signo no
    se puede saber si el movimiento entra o sale.
    """
    df = pd.DataFrame(
        [
            {"FECHA": "02/07/2026", "DETALLE": "Cobro", "IMPORTE": 1000.0},
            {"FECHA": "03/07/2026", "DETALLE": "Pago", "IMPORTE": -400.0},
        ]
    )

    movimientos = _df_to_movimientos(df, "MP")

    assert movimientos[0].haber == pytest.approx(1000.0)
    assert movimientos[1].debe == pytest.approx(400.0)


def test_tabla_sin_columnas_reconocibles_explica_que_falta(tmp_path):
    """El error tiene que decir que columnas se leyeron: es lo unico que le sirve para arreglar el archivo."""
    ruta = _xlsx(tmp_path / "raro.xlsx", ["Columna A", "Columna B"], [[1, 2]])

    with pytest.raises(ErrorDeExtraccion) as error:
        procesar_tabla("BBVA", str(ruta))

    assert "FECHA" in str(error.value)


def test_tabla_vacia_falla_con_mensaje():
    with pytest.raises(ErrorDeExtraccion):
        procesar_tabla("BBVA", "no-existe-nunca.xlsx")


def test_extension_no_soportada_en_tablas():
    with pytest.raises(ErrorDeExtraccion, match="no soportado"):
        procesar_tabla("BBVA", "extracto.txt")


def test_la_tabla_se_borra_siempre(tmp_path):
    ruta = _xlsx(
        tmp_path / "temporal.xlsx",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago", 100.0, 0]],
    )
    procesar_tabla("BBVA", str(ruta))
    assert not Path(ruta).exists()

    rota = _xlsx(tmp_path / "rota.xlsx", ["Importe"], [[1]])
    with pytest.raises(ErrorDeExtraccion):
        procesar_tabla("BBVA", str(rota))
    assert not Path(rota).exists()


# --------------------------------------------------------------------------
# Lectura de csv
# --------------------------------------------------------------------------


def test_csv_con_punto_y_coma_se_lee(tmp_path):
    """Los CSV argentinos vienen en cp1252 y separados por punto y coma."""
    ruta = _csv(
        tmp_path / "extracto.csv",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago luz", "400,50", ""], ["03/07/2026", "Cobro", "", "250,25"]],
        encoding="cp1252",
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert movimientos[0].debe == pytest.approx(400.50)
    assert movimientos[1].haber == pytest.approx(250.25)


def test_csv_con_encabezados_del_puerto(tmp_path):
    ruta = _csv(
        tmp_path / "portal.csv",
        ["Fecha operación", "Descripción", "Debito", "Credito"],
        [["02/07/2026", "Pago luz", "1000,00", ""]],
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert len(movimientos) == 1
    assert movimientos[0].debe == pytest.approx(1000.0)


def test_csv_en_formato_ingles_no_se_parte(tmp_path):
    """
    Con separador coma, un importe con separador de miles ("1,234.56") rompe el
    parseo si no se elige bien el separador de columnas. El valor va entre
    comillas, que es lo que exporta el banco en este formato.
    """
    ruta = _csv(
        tmp_path / "ingles.csv",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [['02/07/2026', "Cobro", "", '"1,234.56"']],
        separador=",",
    )

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert len(movimientos) == 1
    assert movimientos[0].haber == pytest.approx(1234.56)


def test_csv_con_titulo_arriba(tmp_path):
    ruta = tmp_path / "portal.csv"
    with open(ruta, "w", encoding="utf-8", newline="") as fh:
        fh.write("Extracto BBVA\n")
        fh.write("Cuenta 001-022603/4\n")
        fh.write("\n")
        fh.write("Fecha;Concepto;Debe;Haber\n")
        fh.write("02/07/2026;Pago luz;400,50;\n")

    movimientos = procesar_tabla("BBVA", str(ruta))

    assert [m.concepto for m in movimientos] == ["Pago luz"]
    assert movimientos[0].debe == pytest.approx(400.50)


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------


def test_la_ruta_declara_los_formatos():
    assert set(FORMATOS) >= {".pdf", ".xlsx", ".xls", ".csv"}
    assert FORMATOS[".pdf"] == "pdf"
    assert FORMATOS[".xlsx"] == "tabla"
    assert FORMATOS[".xls"] == "tabla"


def test_bancos_soportados_informan_los_formatos(client):
    respuesta = client.get("/api/extractos/bancos")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert "BBVA" in cuerpo["bancos"]
    assert set(cuerpo["formatos"]) >= {".pdf", ".xlsx", ".xls", ".csv"}


def test_el_frontend_acepta_los_cuatro_formatos():
    # Si el input no declara .xls, el usuario no puede seleccionar el archivo
    # aunque el backend lo sepa leer.
    #
    # Los accept ya no viven en conciliacion.ts: cuando el boton Importar se
    # abrio en dos vias, cada input quedo en la pantalla que lo usa (el de tabla
    # en el menu, el de PDF en /importar-pdf). Se buscan los atributos accept=
    # de los templates en vez de una declaracion "acepta: '...'" que ya no esta.
    # Tampoco se hace un "in" a secas sobre todo el texto: los nombres de los
    # formatos aparecen en los mensajes de error de la pantalla y el test daria
    # verde aunque ningun input los declarara.
    raiz = Path(__file__).resolve().parents[2]
    app_dir = raiz / "frontend" / "src" / "app"
    if not (app_dir / "pantallas" / "conciliacion" / "conciliacion.ts").exists():
        pytest.skip("el frontend no esta en este checkout")

    declarados: set[str] = set()
    for template in app_dir.rglob("*.html"):
        for accept in re.findall(r"accept=\"([^\"]+)\"", template.read_text(encoding="utf-8")):
            declarados.update(acepta.strip() for acepta in accept.split(","))

    assert declarados, "no se encontro ningun atributo accept= en el frontend"

    for extension in (".pdf", ".xlsx", ".xls", ".csv"):
        assert extension in declarados, (
            f"{extension} se lee en el backend pero el frontend no lo ofrece. "
            f"Declarados: {sorted(declarados)}"
        )


def test_extension_no_soportada_en_la_ruta(client):
    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "BBVA"},
        files={"archivo": ("extracto.txt", b"cualquier cosa", "text/plain")},
    )
    assert respuesta.status_code == 400
    assert ".txt" in respuesta.json()["detail"]


def test_extension_pdf_con_contenido_txt_se_rechaza(client):
    """La extension la manda el cliente: si el contenido no es PDF, no se procesa."""
    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "BBVA"},
        files={"archivo": ("falso.pdf", b"esto es texto", "application/pdf")},
    )
    assert respuesta.status_code == 400
    assert "%PDF" in respuesta.json()["detail"]


def test_extension_xlsx_sin_zip_se_rechaza(client):
    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "BBVA"},
        files={"archivo": ("falso.xlsx", b"no soy un zip", "application/vnd.ms-excel")},
    )
    assert respuesta.status_code == 400


def test_subir_xlsx_por_la_ruta_devuelve_movimientos(client, tmp_path):
    ruta = _xlsx(
        tmp_path / "portal.xlsx",
        ["Fecha operacion", "Descripción", "Débito", "Crédito"],
        [["02/07/2026", "Pago luz", "400,50", ""], ["03/07/2026", "Cobro", "", "250,25"]],
    )
    with open(ruta, "rb") as fh:
        contenido = fh.read()

    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "BBVA"},
        files={
            "archivo": (
                "portal.xlsx",
                contenido,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["origen"] == "tabla"
    assert cuerpo["cantidad_movimientos"] == 2
    assert cuerpo["datos"][0]["debe"] == pytest.approx(400.50)


def test_subir_csv_por_la_ruta_devuelve_movimientos(client, tmp_path):
    ruta = _csv(
        tmp_path / "extracto.csv",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago luz", "400,50", ""]],
    )
    with open(ruta, "rb") as fh:
        contenido = fh.read()

    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "BBVA"},
        files={"archivo": ("extracto.csv", contenido, "text/csv")},
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["datos"][0]["debe"] == pytest.approx(400.50)


def test_subir_xlsx_a_un_banco_no_soportado(client, tmp_path):
    ruta = _xlsx(
        tmp_path / "portal.xlsx",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago", 100.0, 0]],
    )
    with open(ruta, "rb") as fh:
        contenido = fh.read()

    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "NARANJA"},
        files={"archivo": ("portal.xlsx", contenido, "application/vnd.ms-excel")},
    )

    assert respuesta.status_code == 400
    assert "no esta soportado" in respuesta.json()["detail"]

# --------------------------------------------------------------------------
# .xls viejo (BIFF / OLE2)
# --------------------------------------------------------------------------
#
# Los portales viejos siguen entregando .xls, que no es un zip como el .xlsx:
# tiene una firma OLE2 y lo lee xlrd, no openpyxl.


def _xls(ruta, encabezados, filas):
    xlwt = pytest.importorskip("xlwt")

    libro = xlwt.Workbook()
    hoja = libro.add_sheet("Extracto")
    for columna, titulo in enumerate(encabezados):
        hoja.write(0, columna, titulo)
    for f, fila in enumerate(filas, start=1):
        for columna, valor in enumerate(fila):
            hoja.write(f, columna, valor)
    libro.save(str(ruta))
    return ruta


def test_el_xls_empieza_con_la_firma_ole2(tmp_path):
    ruta = _xls(
        tmp_path / "portal.xls",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago", 100.0, 0]],
    )

    with open(ruta, "rb") as fh:
        assert fh.read(8).hex() == "d0cf11e0a1b11ae1"


def test_subir_xls_por_la_ruta_devuelve_movimientos(client, tmp_path):
    ruta = _xls(
        tmp_path / "portal.xls",
        ["FECHA", "DETALLE", "DEBE", "HABER", "SALDO"],
        [
            ["01/07/2026", "MANTENIMIENTO DE CUENTA", 5500.0, 0, 744760.36],
            ["03/07/2026", "TRANSFERENCIA RECIBIDA", 0, 120000.0, 864760.36],
        ],
    )
    with open(ruta, "rb") as fh:
        contenido = fh.read()

    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "GENERICO"},
        files={"archivo": ("extracto.xls", contenido, "application/vnd.ms-excel")},
    )

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["origen"] == "tabla"
    assert cuerpo["cantidad_movimientos"] == 2
    assert cuerpo["datos"][0]["debe"] == pytest.approx(5500.0)
    assert cuerpo["datos"][0]["saldo"] == pytest.approx(744760.36)


def test_un_xlsx_renombrado_a_xls_se_rechaza(client, tmp_path):
    ruta = _xlsx(
        tmp_path / "trampa.xls",
        ["FECHA", "DETALLE", "DEBE", "HABER"],
        [["02/07/2026", "Pago", 100.0, 0]],
    )
    with open(ruta, "rb") as fh:
        contenido = fh.read()

    respuesta = client.post(
        "/api/extractos/procesar",
        data={"banco": "GENERICO"},
        files={"archivo": ("trampa.xls", contenido, "application/vnd.ms-excel")},
    )

    assert respuesta.status_code == 400
    assert "OLE2" in respuesta.json()["detail"] or "xls" in respuesta.json()["detail"]