"""Bot de sesion de la web de Xubio: login en el SSO de Visma y captura del Bearer.

El frontend web de Xubio no usa la API oficial: autentica contra
core.xubio.com/ar/sba/api con la cookie de sesion del navegador o con un token
Authorization Bearer. Este modulo abre el login real (que vive en el SSO de
Visma: xubio.com/NXV/vismaConnect/login -> connect.visma.com), se loguea con
email y contrasena, y devuelve la sesion capturada (token + cookie). Lo usan
dos entradas:

  * scripts/obtener_sesion_xubio.py, la CLI que renueva la sesion a mano.
  * app/services/sesion_xubio.py, el login de la pantalla de conciliacion
    (POST /api/xubio/login), que guarda credenciales y renueva con el
    navegador visible.

El login es en DOS pasos: primero el email (#Username) y despues la
contrasena. Si el selector del segundo paso cambia, el script intenta varias
alternativas y, si no encuentra ninguna, imprime los inputs visibles para
corregir el selector.

A veces Xubio no pide credenciales: si ya hay una sesion activa, el login
redirige a xubio.com/NXV/vismaConnect/callback con un aviso y un boton para
continuar con esa sesion ("Continuar inicio"). El bot lo cliclea en lugar de
quedarse esperando el campo de email (ver clic_continuar_sesion_activa).

Primera vez (instala el navegador de Playwright):
    uv run playwright install chromium
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

URL_LOGIN = "https://xubio.com/NXV/vismaConnect/login"

# La app web (la que responde 200 en /ar/sba/api con el Bearer del navegador).
# Un solo dominio para no mandar cookies de marketing en la peticion.
DOMINIOS_SESION = {"core.xubio.com", "app.xubio.com"}

# Selectores investigados en connect.visma.com (login de Visma Connect).
SELECTOR_EMAIL = "#Username"
SELECTORES_PASSWORD = [
    'input[type="password"]',
    "#Password",
    'input[name="Password"]',
    "#password",
]


def leer_env(path: Path) -> dict[str, str]:
    """Parsea un .env a diccionario sin evaluar nada."""
    valores: dict[str, str] = {}
    if not path.exists():
        return valores
    for linea in path.read_text(encoding="utf-8").splitlines():
        linea_sin_comentario = linea.split("#", 1)[0].strip()
        if not linea_sin_comentario or "=" not in linea_sin_comentario:
            continue
        clave, _, valor = linea_sin_comentario.partition("=")
        valores[clave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def escribir_env(actualizar: dict[str, str], path: Path) -> None:
    """Actualiza claves del .env conservando el resto y el orden.

    Los archivos locales de Xubio pueden tener nombres de cuenta con acentos;
    siempre se lee y escribe con encoding utf-8 explicito.
    """
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Copialo desde .env.example.")

    lineas = path.read_text(encoding="utf-8").splitlines()
    claves_vistas: set[str] = set()
    resultado: list[str] = []
    for linea in lineas:
        clave = linea.split("=", 1)[0].strip() if "=" in linea else ""
        if clave in actualizar and clave not in claves_vistas:
            resultado.append(f"{clave}={actualizar[clave]}")
            claves_vistas.add(clave)
        else:
            resultado.append(linea)
    for clave, valor in actualizar.items():
        if clave not in claves_vistas:
            resultado.append(f"{clave}={valor}")

    # Si el archivo terminaba en newline, respetarlo (si no, no agregar).
    original = path.read_text(encoding="utf-8")
    termina = "\n" if original.endswith("\n") else ""
    path.write_text("\n".join(resultado) + termina, encoding="utf-8")


async def descartar_banner_cookies(page) -> None:
    """Cierra el banner de cookies (OneTrust) que tapa el login de Visma.

    1) API de OneTrust (cierra tambien el centro de preferencias si se abrio).
    2) Si no hay API, clic en el boton de aceptar todo.
    3) Ultimo recurso: sacar el nodo del DOM.
    """
    try:
        aceptado = await page.evaluate(
            """() => {
                try {
                    if (window.OneTrust) {
                        if (typeof OneTrust.AcceptAll === 'function') {
                            OneTrust.AcceptAll();
                            return true;
                        }
                        if (typeof OneTrust.AcceptAllCookies === 'function') {
                            OneTrust.AcceptAllCookies();
                            return true;
                        }
                    }
                } catch (e) {}
                return false;
            }"""
        )
        if aceptado:
            try:
                await page.wait_for_selector(
                    "#onetrust-banner-sdk", state="hidden", timeout=4000
                )
            except Exception:
                pass
            return
    except Exception:
        pass
    for selector in (
        "#onetrust-accept-btn-handler",
        "#accept-recommended-btn-handler",
    ):
        locator = page.locator(selector)
        if await locator.count() > 0 and await locator.is_visible():
            await locator.first.click(timeout=5000)
            return
    await page.evaluate(
        """() => {
            const sdk = document.getElementById('onetrust-consent-sdk');
            if (sdk) sdk.remove();
        }"""
    )


async def click_continuar(page, anclaje: str) -> bool:
    """Clic en el boton de continuar del form que contiene `anclaje`.

    El form se busca con XPath (ancestor::form), que funciona en todas las
    versiones de Playwright y no se rompe con comillas como :has(). Si el
    anclaje no esta dentro de un form, se busca el boton en toda la pagina.
    """
    form = page.locator(anclaje).locator("xpath=ancestor::form[1]")
    if await form.count() == 0:
        ambitos: list = [page.locator("body")]
    else:
        ambitos = [form]
    for selector in (
        'input[type="submit"]',
        'button[type="submit"]',
        "button",
        'input[type="button"]',
    ):
        for ambito in ambitos:
            locator = ambito.locator(selector)
            if await locator.count() > 0:
                boton = locator.first
                if await boton.is_visible():
                    await boton.click()
                    return True
    return False


async def clic_continuar_sesion_activa(page) -> bool:
    """Clic en el boton de sesion activa de Xubio ("Continuar inicio").

    Cuando ya hay una sesion de Xubio iniciada, el login de Visma Connect no
    pide email ni contrasena: redirige a xubio.com/NXV/vismaConnect/callback
    con un aviso y un boton para continuar con esa sesion. Sin el clic el bot
    se quedaria esperando el campo de email que nunca aparece. Devuelve True
    si clicleo el boton; False si no habia aviso y el flujo normal sigue.
    """
    url = page.url or ""
    cuerpo = await page.evaluate("() => document.body ? document.body.innerText : ''")
    en_callback = "vismaConnect/callback" in url
    hay_aviso = re.search(
        r"sesi[oó]n\s+(ya\s+)?(activa|iniciada|abierta|existente)", cuerpo, re.I
    )
    if not (en_callback or hay_aviso):
        return False

    # Al aviso le puede tomar un momento renderizarse.
    if en_callback:
        try:
            await page.wait_for_selector("button, a", timeout=5000)
        except Exception:
            pass

    # Se busca el nombre mas especifico primero para no cliclear cualquier
    # boton de "continuar" que pueda haber en la pagina. El boton real se
    # llama exactamente "Continuar Inicio" (el primer patron le pega, con
    # mayusculas o minusculas).
    for patron in (
        r"continuar\s+(con\s+)?inicio",
        r"continuar\s+con\s+la\s+sesi[oó]n",
        r"continuar",
        r"usar\s+(mi\s+)?sesi[oó]n",
        r"ingresar\s+con\s+esa\s+cuenta",
    ):
        candidatos = page.locator(
            "button, a, input[type='submit'], input[type='button']"
        ).filter(has_text=re.compile(patron, re.I))
        cantidad = await candidatos.count()
        for i in range(cantidad):
            candidato = candidatos.nth(i)
            if await candidato.is_visible():
                print(
                    f"   Cliqueando '{patron}' para seguir con la sesion activa..."
                )
                await candidato.click(timeout=5000)
                return True

    # Quedamos en el aviso sin encontrar el boton: no inventar un click, pero
    # tampoco colgar el bot esperando el email.
    print(
        "   Hay un aviso de sesion activa pero no se encontro el boton de "
        "continuar; puede quedar un paso a mano en la ventana."
    )
    return False


async def llenar_primero(page, selectores: list[str], valor: str) -> bool:
    """Llena el primer input de la lista que exista en la pagina."""
    for selector in selectores:
        locator = page.locator(selector)
        if await locator.count() > 0:
            await locator.first.fill(valor)
            return True
    return False


async def buscar_token_en_storage(page) -> str | None:
    """Ultimo recurso: token guardado por el SPA en localStorage/sessionStorage."""
    candidatas = await page.evaluate(
        """() => {
            const todas = {};
            const guardar = (storage) => {
                for (let i = 0; i < storage.length; i++) {
                    const k = storage.key(i);
                    const v = storage.getItem(k);
                    todas[k] = v;
                }
            };
            try { guardar(localStorage); } catch (e) {}
            try { guardar(sessionStorage); } catch (e) {}
            return todas;
        }"""
    )
    mejor: str | None = None
    for clave, valor in (candidatas or {}).items():
        if not isinstance(valor, str) or len(valor) < 16:
            continue
        if not re.search(r"token|auth|sesion|session|jwt|bearer", clave, re.I):
            continue
        # El token de la web de Xubio es un numero largo (o un JWT).
        if re.fullmatch(r"\d{20,}", valor):
            return valor
        mejor = mejor or valor
    return mejor


async def obtener_sesion_xubio(
    email: str,
    password: str,
    headless: bool,
    slow_mo: int,
) -> tuple[str | None, str | None]:
    """
    Abre el navegador, se loguea en Xubio y captura la sesion.

    Devuelve (token_bearer | None, cookie_cruda | None). Si el login falla
    levanta RuntimeError con un mensaje que ayuda a corregir selectores.
    """
    # Import perezoso: la CLI debe poder dar --help o avisar que faltan
    # credenciales aunque playwright no este instalado todavia.
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Falta playwright. Instalalo con:\n"
            "    cd backend && uv sync\n"
            "    uv run playwright install chromium"
        )
    try:
        # playwright >= 1.63 exporta TimeoutError; las versiones viejas (hasta
        # ~1.38) usaban PlaywrightTimeoutError.
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except ImportError:
        try:
            from playwright.async_api import PlaywrightTimeoutError
        except ImportError:
            raise RuntimeError(
                "Falta playwright. Instalalo con:\n"
                "    cd backend && uv sync\n"
                "    uv run playwright install chromium"
            )

    captura = {"token": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(locale="es-AR")
        page = await context.new_page()

        def en_request(request) -> None:
            # El SPA de Xubio manda el Bearer en sus llamadas: capturar el
            # Authorization de cualquier request a la app (core/app.xubio.com),
            # no solo de /sba/api.
            if captura["token"]:
                return
            if any(d in request.url for d in DOMINIOS_SESION):
                auth = (request.headers.get("authorization") or "").strip()
                if auth.lower().startswith("bearer "):
                    captura["token"] = auth[7:].strip()

        # Escuchar en todo el contexto: la app puede abrirse en otra pestana.
        context.on("request", en_request)

        def url_aplicacion() -> bool:
            # La app nueva de Xubio queda en xubio.com/NXV y llama a la API en
            # core.xubio.com; "haber llegado a la app" puede ser cualquiera de
            # esos dos.
            return any(
                "xubio.com/NXV" in (p.url or "")
                or any(d in (p.url or "") for d in DOMINIOS_SESION)
                for p in context.pages
            )

        try:
            print("1. Abriendo el login de Xubio (redirige al SSO de Visma)...")
            # Esta pagina hace un window.location a connect.visma.com/connect/
            # authorize?client_id=xubio: Playwright sigue el redirect solo.
            await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)

            # Xubio a veces no pide credenciales: si ya hay una sesion activa,
            # el callback muestra "Continuar inicio" y el bot lo cliclea.
            await descartar_banner_cookies(page)
            sesion_activa = await clic_continuar_sesion_activa(page)

            if not sesion_activa:
                print("2. Esperando el campo de email...")
                await page.wait_for_selector(SELECTOR_EMAIL, timeout=30000)
                await descartar_banner_cookies(page)

                print("3. Ingresando email y continuando...")
                await page.fill(SELECTOR_EMAIL, email)
                if not await click_continuar(page, SELECTOR_EMAIL):
                    raise RuntimeError(
                        "No se encontro el boton de continuar del primer paso. "
                        "Inspecciona la pagina y ajusta click_continuar()."
                    )

                print("4. Esperando el campo de contrasena...")
                try:
                    await page.wait_for_selector(
                        ", ".join(SELECTORES_PASSWORD), timeout=20000
                    )
                except PlaywrightTimeoutError:
                    cuerpo = await page.content()
                    if re.search(r"passwordless|magic|enviamos|enviamos un|correo", cuerpo, re.I):
                        raise RuntimeError(
                            "El login pidio un link por email (passwordless) en vez de "
                            "contrasena. Completa el ingreso a mano en el navegador "
                            "que se abre (headless=False) o revisa la casilla."
                        )
                    inputs = await page.evaluate(
                        """() => Array.from(document.querySelectorAll('input'))
                            .map(i => ({ tag: i.tagName, type: i.type,
                                          name: i.name, id: i.id,
                                          visible: !!i.offsetParent }))"""
                    )
                    raise RuntimeError(
                        "No aparecio el campo de contrasena tras el email. "
                        f"Inputs visibles en la pagina: {inputs}"
                    )

                print("5. Ingresando contrasena...")
                # El banner puede reaparecer en el segundo paso: descartarlo otra vez.
                await descartar_banner_cookies(page)
                if not await llenar_primero(page, SELECTORES_PASSWORD, password):
                    raise RuntimeError("No se pudo llenar el campo de contrasena.")
                if not await click_continuar(page, 'input[type="password"]'):
                    raise RuntimeError(
                        "No se encontro el boton para enviar la contrasena."
                    )
            else:
                print("   Sesion de Xubio ya activa: continuando con esa sesion...")

            print("6. Esperando que cargue la app de Xubio...")
            # Esperar a que la app aparezca (en cualquier pestana) o a que se
            # capture el Bearer. La espera da tiempo para completar a mano los
            # pasos que no se pueden automatizar (captcha, codigo por correo,
            # elegir empresa).
            esperados = 0
            while esperados < 150 and not captura["token"] and not url_aplicacion():
                await asyncio.sleep(2)
                esperados += 2
                if esperados % 10 == 0:
                    print(
                        "   ... siguen cargando "
                        + str([p.url for p in context.pages])
                    )

            # La app ya cargo pero el Bearer todavia no: darle unos segundos mas.
            if url_aplicacion() and not captura["token"]:
                print("   La app cargo; esperando que dispare sus llamadas...")
                for _ in range(15):
                    if captura["token"]:
                        break
                    await asyncio.sleep(1.5)

            if not captura["token"]:
                for pestana in context.pages:
                    captura["token"] = await buscar_token_en_storage(pestana)
                    if captura["token"]:
                        break

            # Si no llegamos a la app, diagnosticar en vez de escribir basura.
            if not captura["token"] and not url_aplicacion():
                estado = []
                for pestana in context.pages:
                    estado.append(
                        {
                            "url": pestana.url,
                            "titulo": await pestana.title(),
                            "inputs": await pestana.evaluate(
                                """() => Array.from(document.querySelectorAll('input'))
                                    .map(i => ({ type: i.type, name: i.name,
                                                 id: i.id, visible: !!i.offsetParent }))"""
                            ),
                        }
                    )
                raise RuntimeError(
                    "No se llego a la app de Xubio ni se capturo el Bearer. "
                    "Si en la ventana quedo un paso a mano (verificacion, "
                    "elegir empresa, captcha), completalo y reintenta. Estado "
                    f"de las pestanas: {estado}"
                )

            print("7. Extrayendo sesion...")
            cookies = await context.cookies()
            # Solo cookies de sesion reales: del dominio de la app y con nombre
            # de sesion/autenticacion. Se descartan cookies de balanceador
            # (AWSALB), marketing y analytics, que no forman la sesion de Xubio
            # y solo ensuciarian el header Cookie.
            nombres_sesion = (
                "session", "token", "auth", "asp.net",
                "jsessionid", "sba", "xubio", "sid",
            )
            pares = [
                f"{c['name']}={c['value']}"
                for c in cookies
                if any(d in (c.get("domain") or "") for d in DOMINIOS_SESION)
                and any(n in c["name"].lower() for n in nombres_sesion)
            ]
            cookie_cruda = "; ".join(pares)
            print("   url final:", [(p.url) for p in context.pages])

            return captura["token"], (cookie_cruda or None)

        finally:
            print("8. Cerrando el navegador...")
            await browser.close()