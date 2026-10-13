"""
Unit tests del bot de sesion de Xubio: clic en "Continuar Inicio".

La pieza nueva: cuando ya hay una sesion de Xubio activa, el login no pide
credenciales y el bot cliclea el boton de continuar del callback en vez de
quedarse esperando el campo de email. Se prueba con una pagina falsa (no se
abre Chromium ni hay red). El resto del bot (llenar email, contrasena, captura
del Bearer) se valida en el smoke en vivo, como se hace siempre con Playwright.

El boton real se llama exactamente "Continuar Inicio" (confirmado con el
usuario). El fake de abajo imita el filtrado por texto de Playwright
(filter(has_text=regex)), asi los tests verifican que el patron le pega al
nombre real del boton.
"""

import re

from app.services.sesion_xubio_bot import (
    clic_continuar_sesion_activa,
    escribir_env,
    extraer_codigos_reportes,
    leer_env,
)


class RegistroClicks:
    """Contador compartido entre todos los candidatos de una pagina."""

    def __init__(self):
        self.total = 0


class BotonFake:
    """Un candidato a boton: visible o no; cuenta los clicks en el registro."""

    def __init__(self, registro, visible):
        self._registro = registro
        self._visible = visible

    async def is_visible(self):
        return self._visible

    async def click(self, timeout=None):
        self._registro.total += 1


class LocatorFake:
    """Emula page.locator(...).filter(has_text=regex) filtrando de verdad.

    Playwright matchea el regex contra el innerText de cada elemento; aca se
    hace lo mismo contra los textos de los candidatos, para que los tests
    prueben el nombre real del boton y no un fake que devuelve siempre.
    """

    def __init__(self, textos, registro, visible=True):
        self._textos = list(textos)
        self._registro = registro
        self.visible = visible

    async def count(self):
        return len(self._textos)

    def nth(self, indice):
        return BotonFake(self._registro, self.visible)

    def filter(self, **kwargs):
        patron = kwargs.get("has_text")
        textos = [t for t in self._textos if patron and patron.search(t)]
        return LocatorFake(textos, self._registro, self.visible)


class PaginaFake:
    """Emula lo minimo de una Playwright Page que usa el bot."""

    def __init__(self, url="", cuerpo="", textos=("Continuar Inicio",), visible=True):
        self.url = url
        self._cuerpo = cuerpo
        self._registro = RegistroClicks()
        self._textos = list(textos)
        self.visible = visible

    async def evaluate(self, _js):
        return self._cuerpo

    async def wait_for_selector(self, _selector, timeout=None):
        return None

    def locator(self, _selector):
        return LocatorFake(self._textos, self._registro, self.visible)

    @property
    def clicks(self):
        return self._registro.total


async def test_login_normal_sin_aviso_no_toca_ningun_boton():
    # El form de Visma Connect no tiene aviso de sesion activa: el bot sigue
    # con email/contrasena sin cliclear nada.
    pagina = PaginaFake(
        url="https://connect.visma.com/connect/authorize?client_id=xubio",
        cuerpo="Ingresá tu correo electrónico",
    )

    assert await clic_continuar_sesion_activa(pagina) is False
    assert pagina.clicks == 0


async def test_callback_con_sesion_activa_cliclea_continuar():
    # En el callback Xubio avisa que ya hay una sesion y ofrece continuar.
    pagina = PaginaFake(
        url="https://xubio.com/NXV/vismaConnect/callback?code=abc123",
        cuerpo="Ya tenés una sesión activa. Continuá con esa sesión o iniciá con otra cuenta.",
    )

    assert await clic_continuar_sesion_activa(pagina) is True
    assert pagina.clicks == 1


async def test_aviso_de_sesion_activa_sin_url_de_callback_tambien_cliclea():
    # El aviso se detecta por el texto, no solo por la url: si Xubio redirige
    # con la sesion ya activa desde el login, tambien hay que cliclear.
    pagina = PaginaFake(
        url="https://xubio.com/NXV/vismaConnect/login",
        cuerpo="Existe una sesión activa iniciada",
    )

    assert await clic_continuar_sesion_activa(pagina) is True
    assert pagina.clicks == 1


async def test_el_boton_real_se_llama_continuar_inicio():
    # El nombre exacto del boton (confirmado con el usuario) tiene que
    # matchear el primer patron, aunque este escrito con mayusculas.
    pagina = PaginaFake(
        url="https://xubio.com/NXV/vismaConnect/callback",
        cuerpo="Ya tenés una sesión activa",
        textos=("Continuar Inicio",),
    )

    assert await clic_continuar_sesion_activa(pagina) is True
    assert pagina.clicks == 1


async def test_aviso_sin_boton_visible_no_inventa_un_click():
    # Si el aviso aparece pero el boton no esta visible (por ejemplo tapado por
    # el banner de cookies), el bot no cliclea a ciegas: avisa y vuelve, para
    # que el flujo normal (o un paso a mano en la ventana) siga igual.
    pagina = PaginaFake(
        url="https://xubio.com/NXV/vismaConnect/callback",
        cuerpo="Ya tenés una sesión activa",
        visible=False,
    )

    assert await clic_continuar_sesion_activa(pagina) is False
    assert pagina.clicks == 0


async def test_aviso_con_otro_nombre_de_boton_no_lo_confunde():
    # Si el aviso esta pero el boton se llama distinto a "Continuar Inicio",
    # el bot no cliclea cualquier cosa: avisa y vuelve.
    pagina = PaginaFake(
        url="https://xubio.com/NXV/vismaConnect/callback",
        cuerpo="Ya tenés una sesión activa",
        textos=("Iniciar sesión",),
    )

    assert await clic_continuar_sesion_activa(pagina) is False
    assert pagina.clicks == 0


# --------------------------------------------------------------------------
# Deteccion de la cuenta (empresa/cuenta) del Libro Mayor
#
# Los patrones se prueban contra los formatos en que la app puede mandarlos:
# el cuerpo XML del webreport, un JSON y la query. En vivo solo queda
# confirmar cual usa la cuenta real.
# --------------------------------------------------------------------------


def test_extrae_empresa_y_cuenta_del_xml_del_webreport():
    cuerpo = (
        '<?xml version="1.0" encoding="UTF-8"?><postData><parameters>'
        '<parameter name="p_CuentaReportCode" value="ARBOL_ID=1__SEPNO__0" />'
        '<parameter name="p_EmpresaReportCode" value="29774" />'
        "</parameters></postData>"
    )

    assert extraer_codigos_reportes(cuerpo) == ("29774", "ARBOL_ID=1__SEPNO__0")


def test_extrae_los_codigos_de_un_json():
    cuerpo = (
        '{"p_EmpresaReportCode": 29774, '
        '"p_CuentaReportCode": "ARBOL_ID=1__SEPNO__0"}'
    )

    assert extraer_codigos_reportes(cuerpo) == ("29774", "ARBOL_ID=1__SEPNO__0")


def test_extrae_los_codigos_de_la_query():
    url = (
        "https://core.xubio.com/NXV/webreport/data"
        "?empresaReportCode=29774&cuentaReportCode=ARBOL_ID=1__SEPNO__0"
    )

    assert extraer_codigos_reportes(url) == ("29774", "ARBOL_ID=1__SEPNO__0")


def test_sin_codigos_devuelve_none_sin_inventar():
    texto = "GET /ar/sba/api/cliente/clientes/findAllPaginado/0/20"

    assert extraer_codigos_reportes(texto) == (None, None)


def test_no_toma_cualquier_numero_como_empresa():
    # Un id de cliente suelto no es el codigo de empresa del reporte.
    assert extraer_codigos_reportes('{"id": 5261262}') == (None, None)


# --------------------------------------------------------------------------
# Escritura del .env
#
# En un clon nuevo el .env no existe (esta en .gitignore): el login del panel
# tiene que poder crearlo solo, y arrancar del .env.example para no perder los
# defaults ni los comentarios. Antes cortaba con "No existe ... .env".
# --------------------------------------------------------------------------


def test_escribir_env_crea_el_archivo_desde_el_ejemplo(tmp_path):
    ejemplo = tmp_path / ".env.example"
    ejemplo.write_text(
        "# comentario\nXUBIO_WEB_URL=https://core.xubio.com\nXUBIO_WEB_TOKEN=\n",
        encoding="utf-8",
    )
    env = tmp_path / ".env"

    escribir_env({"XUBIO_WEB_TOKEN": "309-token"}, env)

    assert env.exists()
    contenido = env.read_text(encoding="utf-8")
    # Conserva el default y el comentario del ejemplo...
    assert "# comentario" in contenido
    assert "XUBIO_WEB_URL=https://core.xubio.com" in contenido
    # ...y reemplaza la clave pedida.
    assert "XUBIO_WEB_TOKEN=309-token" in contenido
    assert leer_env(env)["XUBIO_WEB_TOKEN"] == "309-token"


def test_escribir_env_crea_de_cero_sin_ejemplo(tmp_path):
    env = tmp_path / ".env"

    escribir_env({"XUBIO_EMAIL": "a@b.com"}, env)

    assert leer_env(env) == {"XUBIO_EMAIL": "a@b.com"}
    assert env.read_text(encoding="utf-8").endswith("\n")


def test_escribir_env_agrega_claves_nuevas_sin_tocar_lo_demas(tmp_path):
    env = tmp_path / ".env"
    env.write_text("XUBIO_WEB_URL=https://core.xubio.com\n", encoding="utf-8")

    escribir_env({"XUBIO_WEB_TOKEN": "309", "XUBIO_WEB_COOKIE": "s=1"}, env)

    contenido = env.read_text(encoding="utf-8")
    assert contenido.startswith("XUBIO_WEB_URL=https://core.xubio.com\n")
    assert "XUBIO_WEB_TOKEN=309" in contenido
    assert "XUBIO_WEB_COOKIE=s=1" in contenido