"""Tests del selector de Estudio/Empresa de Xubio.

Todo con datos sinteticos: el repo es publico y la cuenta real de Xubio trae
nombres de clientes que no van en un fixture. El marcado del HTML replica el
real de la app NXV (verificado en vivo), pero los nombres y los tenants son
inventados.

Se prueban las dos mitades:

  * el parseo puro (extraer_estudios / extraer_empresa_en_sesion), que recibe
    el HTML y no toca ni red ni navegador;
  * el catalogo en disco y la eleccion del estudio, con las rutas apuntadas a
    archivos temporales (nunca al .env ni al catalogo real del backend).
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.main import app
from app.services import estudios_xubio
from app.services.sesion_xubio_bot import SesionCapturada, leer_selector_estudios

cliente_test = TestClient(app)


# --------------------------------------------------------------------------
# Fixture sintetico del selector: mismo marcado que la app NXV real
# --------------------------------------------------------------------------

# (nombre, tenant) en el orden en que los muestra Xubio (alfabetico).
EMPRESAS = [
    ("ALFA CONSULTORES S.A.", "tnt_100001"),
    ("BETA Y ASOCIADOS S.R.L.", "tnt_100002"),
    ("GAMMA HERMANOS", "tnt_100003"),
    ("DELTA S.A.S.", "tnt_100004"),
    ("EPSILON SCI", "tnt_100005"),
    ("ZETA E HIJOS", "tnt_100006"),
    ("ETA S.A.", "tnt_100007"),
    ("THETA HNOS", "tnt_100008"),
    ("IOTA S.R.L.", "tnt_100009"),
    ("KAPPA S.C.S.", "tnt_100010"),
    ("LAMBDA S.A.", "tnt_100011"),
    ("MU S.C.I.", "tnt_100012"),
    ("NU Y CIA", "tnt_100013"),
    ("XI SOCIEDAD", "tnt_100014"),
    ("OMICRON S.A.", "tnt_100015"),
]

ACTUAL = "ALFA CONSULTORES S.A."


def _html_selector(empresas=EMPRESAS, actual=ACTUAL, repetidos=False):
    """El HTML del selector de la barra superior, como lo sirve /NXV/home.

    `repetidos=True` pinta la lista dos veces: el parser tiene que deduplicar
    por tenant (el HTML de verdad a veces trae el bloque dos veces).
    """
    items = "\n".join(
        f'<li class="licomp"><a href="/NXV/Relogin?tenant={tenant}" class="">'
        f"{nombre}</a></li>"
        for nombre, tenant in empresas
    )
    if repetidos:
        items = f"{items}\n{items}"
    return (
        "<html><body>"
        '<li class="compania">'
        '<a id="resaltarCompania" href="#">'
        f'<span class="nombre-tenant">{actual}</span></a>'
        '<div class="dropdown">'
        '<input id="buscador-empresa">'
        f'<ul id="compania-lista">{items}</ul>'
        "</div></li>"
        "</body></html>"
    )


# Clientes del catalogo de la contabilidad (afiliados): los dos primeros
# matchean una empresa del selector por nombre (uno con sufijo distinto), el
# tercero no matchea ninguna.
CLIENTES = [
    {
        "id": 1,
        "organizacionNombre": "ALFA CONSULTORES",
        "organizacionId": 5001,
        "cuit": "30-11111111-1",
    },
    {
        "id": 2,
        "organizacionNombre": "BETA Y ASOCIADOS",
        "organizacionId": 5002,
        "cuit": "30-22222222-2",
    },
    {
        "id": 99,
        "organizacionNombre": "ZETA CLIENTE SUELTO",
        "organizacionId": 5099,
        "cuit": "30-99999999-9",
    },
]


class _PaginaFake:
    """Lo minimo de una Page de Playwright: solo el outerHTML."""

    def __init__(self, html: str):
        self._html = html

    async def evaluate(self, _script: str) -> str:
        return self._html


# --------------------------------------------------------------------------
# Parseo puro
# --------------------------------------------------------------------------


def test_extraer_estudios_del_marcado_real():
    estudios = estudios_xubio.extraer_estudios(_html_selector())

    assert len(estudios) == len(EMPRESAS)
    assert estudios[0] == {
        "clave": "empresa:tnt_100001",
        "nombre": "ALFA CONSULTORES S.A.",
        "tenant": "tnt_100001",
    }
    # Se respeta el orden en que los muestra Xubio.
    assert [e["nombre"] for e in estudios] == [n for n, _ in EMPRESAS]


def test_extraer_estudios_deduplica_tenants_repetidos():
    estudios = estudios_xubio.extraer_estudios(_html_selector(repetidos=True))

    assert len(estudios) == len(EMPRESAS)


def test_extraer_estudios_sin_selector_devuelve_vacio():
    assert estudios_xubio.extraer_estudios("<html><body>otra pantalla</body></html>") == []
    assert estudios_xubio.extraer_estudios("") == []


def test_extraer_empresa_en_sesion():
    assert estudios_xubio.extraer_empresa_en_sesion(_html_selector()) == ACTUAL
    assert estudios_xubio.extraer_empresa_en_sesion("<html></html>") is None


def test_leer_selector_estudios_de_la_pagina():
    empresa, estudios = asyncio.run(leer_selector_estudios(_PaginaFake(_html_selector())))

    assert empresa == ACTUAL
    assert len(estudios) == len(EMPRESAS)


def test_normalizar_nombre_y_coincidencias():
    assert estudios_xubio.normalizar_nombre("Peña  S.A.") == "PENA S A"
    # El sufijo societario no distingue a un estudio de otro.
    assert estudios_xubio.nombres_coinciden("GOMEZ S.A.", "GOMEZ")
    assert estudios_xubio.nombres_coinciden("PEREZ S.R.L.", "PEREZ")
    assert not estudios_xubio.nombres_coinciden("GOMEZ", "GOMERA")
    # Un nombre vacio nunca coincide (una fuente sin nombre no arrastra a otra).
    assert not estudios_xubio.nombres_coinciden("", "GOMEZ")
    assert not estudios_xubio.nombres_coinciden("", "")


# --------------------------------------------------------------------------
# Cruce de las dos fuentes
# --------------------------------------------------------------------------


def test_combinar_fuentes_pega_cliente_a_empresa_y_separa_el_resto():
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    combinados, solo_clientes = estudios_xubio.combinar_fuentes(empresas, CLIENTES)

    assert len(combinados) == len(EMPRESAS)
    # ALFA: el cliente "ALFA CONSULTORES" matchea la empresa "ALFA ... S.A.".
    alfa = combinados[0]
    assert alfa.clave == "empresa:tnt_100001"
    assert alfa.origen == "ambos"
    assert alfa.organizacion_id == 5001
    assert alfa.cuit == "30-11111111-1"
    # GAMMA no tiene cliente con ese nombre: queda como "empresa" sin organizacion.
    gamma = next(e for e in combinados if e.nombre == "GAMMA HERMANOS")
    assert gamma.origen == "empresa"
    assert gamma.organizacion_id is None
    # El cliente que no matchea ninguna empresa se devuelve aparte, con su
    # organizacionId (para poder filtrar el mayor igual).
    assert len(solo_clientes) == 1
    assert solo_clientes[0].clave == "cliente:99"
    assert solo_clientes[0].origen == "cliente"
    assert solo_clientes[0].organizacion_id == 5099


def test_combinar_fuentes_sin_selector_deja_todos_los_clientes():
    combinados, solo_clientes = estudios_xubio.combinar_fuentes([], CLIENTES)

    assert combinados == []
    assert len(solo_clientes) == len(CLIENTES)


# --------------------------------------------------------------------------
# Catalogo en disco y eleccion
# --------------------------------------------------------------------------


@pytest.fixture
def rutas_temporales(tmp_path, monkeypatch):
    """Apunta el catalogo y el .env a archivos de prueba, y resetea settings."""
    monkeypatch.setattr(estudios_xubio, "RUTA_CATALOGO", tmp_path / ".xubio_estudios.json")
    monkeypatch.setattr(estudios_xubio, "RUTA_ENV", tmp_path / ".env")
    for campo in (
        "XUBIO_ESTUDIO_CLAVE",
        "XUBIO_ESTUDIO_NOMBRE",
        "XUBIO_ESTUDIO_TENANT",
        "XUBIO_ORGANIZACION_REPORT_CODE",
    ):
        monkeypatch.setattr(config.settings, campo, "")
    return tmp_path


def test_cargar_catalogo_vacio_si_no_existe(rutas_temporales):
    catalogo = estudios_xubio.cargar_catalogo()

    assert catalogo["estudios"] == []
    assert catalogo["solo_clientes"] == []
    assert catalogo["empresa_en_sesion"] is None


def test_guardar_y_cargar_catalogo(rutas_temporales):
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    guardado = estudios_xubio.guardar_catalogo(empresas, CLIENTES, empresa_en_sesion=ACTUAL)

    assert len(guardado["estudios"]) == len(EMPRESAS)
    # Se escribio en disco como JSON legible.
    en_disco = json.loads(estudios_xubio.RUTA_CATALOGO.read_text(encoding="utf-8"))
    assert en_disco["empresa_en_sesion"] == ACTUAL

    recargado = estudios_xubio.cargar_catalogo()
    assert recargado["empresa_en_sesion"] == ACTUAL
    assert len(recargado["estudios"]) == len(EMPRESAS)
    assert len(recargado["solo_clientes"]) == 1


def test_guardar_catalogo_ignora_json_ilegible(rutas_temporales):
    estudios_xubio.RUTA_CATALOGO.write_text("{esto no es json", encoding="utf-8")

    catalogo = estudios_xubio.cargar_catalogo()

    assert catalogo["estudios"] == []


def test_seleccionar_estudio_persiste_y_filtra_el_mayor(rutas_temporales):
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, CLIENTES)

    elegido = estudios_xubio.seleccionar_estudio("empresa:tnt_100002")

    assert elegido.nombre == "BETA Y ASOCIADOS S.R.L."
    # El organizacionId del cliente matcheado es lo que filtra el Libro Mayor.
    assert estudios_xubio.organizacion_report_code_actual() == "5002"
    # Y quedo en el .env (para que sobreviva un reinicio del backend).
    guardado = estudios_xubio.RUTA_ENV.read_text(encoding="utf-8")
    assert "XUBIO_ESTUDIO_CLAVE=empresa:tnt_100002" in guardado
    assert "XUBIO_ORGANIZACION_REPORT_CODE=5002" in guardado


def test_seleccionar_estudio_inexistente_levanta_keyerror(rutas_temporales):
    estudios_xubio.guardar_catalogo([], CLIENTES)

    with pytest.raises(KeyError):
        estudios_xubio.seleccionar_estudio("empresa:tnt_000000")


def test_estudio_sin_cliente_matcheado_no_filtra(rutas_temporales):
    """Un estudio del selector sin organizacionId: el mayor sale de la sesion."""
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, [])

    estudios_xubio.seleccionar_estudio("empresa:tnt_100003")

    assert estudios_xubio.organizacion_report_code_actual() == ""
    assert estudios_xubio.estudio_actual().nombre == "GAMMA HERMANOS"


def test_limpiar_estudio(rutas_temporales):
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, CLIENTES)
    estudios_xubio.seleccionar_estudio("empresa:tnt_100001")

    estudios_xubio.limpiar_estudio()

    assert estudios_xubio.estudio_actual() is None
    assert estudios_xubio.organizacion_report_code_actual() == ""


# --------------------------------------------------------------------------
# Endpoints del selector
# --------------------------------------------------------------------------


def test_get_estudios_vacio_sin_sesion(rutas_temporales, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")

    respuesta = cliente_test.get("/api/xubio/estudios")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["exito"] is True
    assert cuerpo["configurada"] is False
    assert cuerpo["catalogo_cargado"] is False
    assert cuerpo["estudios"] == []
    assert cuerpo["actual"] is None
    assert "iniciá sesión" in cuerpo["aviso"]


def test_get_estudios_lista_el_catalogo_guardado(rutas_temporales, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    monkeypatch.setattr(config.settings, "XUBIO_WEB_COOKIE", "")
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, CLIENTES, empresa_en_sesion=ACTUAL)

    respuesta = cliente_test.get("/api/xubio/estudios")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["configurada"] is True
    assert cuerpo["catalogo_cargado"] is True
    assert len(cuerpo["estudios"]) == len(EMPRESAS) + 1  # + el cliente suelto
    assert cuerpo["empresa_en_sesion"] == ACTUAL
    assert cuerpo["aviso"] is None


def test_put_estudio_elige_y_marca_el_actual(rutas_temporales, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, CLIENTES)

    respuesta = cliente_test.put(
        "/api/xubio/estudio", json={"clave": "empresa:tnt_100001"}
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["clave"] == "empresa:tnt_100001"
    assert respuesta.json()["es_actual"] is True

    listado = cliente_test.get("/api/xubio/estudios").json()
    actuales = [e["clave"] for e in listado["estudios"] if e["es_actual"]]
    assert actuales == ["empresa:tnt_100001"]


def test_put_estudio_inexistente_devuelve_404(rutas_temporales):
    estudios_xubio.guardar_catalogo([], CLIENTES)

    respuesta = cliente_test.put(
        "/api/xubio/estudio", json={"clave": "empresa:tnt_000000"}
    )

    assert respuesta.status_code == 404


def test_delete_estudio_olvida_la_eleccion(rutas_temporales, monkeypatch):
    monkeypatch.setattr(config.settings, "XUBIO_WEB_TOKEN", "309-token")
    empresas = estudios_xubio.extraer_estudios(_html_selector())
    estudios_xubio.guardar_catalogo(empresas, CLIENTES)
    estudios_xubio.seleccionar_estudio("empresa:tnt_100001")

    respuesta = cliente_test.delete("/api/xubio/estudio")

    assert respuesta.status_code == 200
    assert respuesta.json()["estudio"] is None
    assert estudios_xubio.estudio_actual() is None


# --------------------------------------------------------------------------
# El paso del bot que lee el selector
# --------------------------------------------------------------------------


def test_sesion_capturada_lleva_los_estudios():
    capturada = SesionCapturada(
        token="309-token",
        empresa_en_sesion=ACTUAL,
        estudios=estudios_xubio.extraer_estudios(_html_selector()),
    )

    assert capturada.empresa_en_sesion == ACTUAL
    assert len(capturada.estudios) == len(EMPRESAS)


def test_guardar_catalogo_de_estudios_usa_empresas_y_clientes(
    rutas_temporales, monkeypatch
):
    """El paso post-login del bot: baja clientes y guarda el catalogo cruzado."""
    from app.services import sesion_xubio

    class _ClienteWebFake:
        async def obtener_afiliados(self):
            return CLIENTES

    monkeypatch.setattr(
        "app.services.xubio_web_client.XubioWebClient", _ClienteWebFake
    )
    capturada = SesionCapturada(
        token="309-token",
        estudios=estudios_xubio.extraer_estudios(_html_selector()),
        empresa_en_sesion=ACTUAL,
    )

    resumen = asyncio.run(
        sesion_xubio._guardar_catalogo_de_estudios(capturada)
    )

    assert resumen["empresa_en_sesion"] == ACTUAL
    assert resumen["estudios"] == len(EMPRESAS)
    assert resumen["solo_clientes"] == 1
    assert resumen["aviso"] is None
    assert len(estudios_xubio.cargar_catalogo()["estudios"]) == len(EMPRESAS)
