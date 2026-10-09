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

from app.services.sesion_xubio_bot import clic_continuar_sesion_activa


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