"""Explora la web de Xubio con el navegador visible para descubrir selectores.

No modifica nada en Xubio: solo se loguea, mira la barra superior, intenta abrir
el selector de Empresa/Estudio y vuelca a disco el DOM y las respuestas de red.
Sirve para escribir el scraping del selector de estudio con datos reales en vez
de suposiciones.

Uso (desde backend/):

    uv run python scripts/explorar_xubio.py

Deja todo en %LOCALAPPDATA%/Temp/opencode/xubio_exploracion/.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# El script vive en backend/scripts y se corre con
# `uv run python scripts/explorar_xubio.py` desde backend: ahi Python pone en
# sys.path el directorio del script (scripts/), no el cwd, asi que hay que
# sumar la raiz del backend para poder importar la app.
_RAIZ_BACKEND = Path(__file__).resolve().parent.parent
if str(_RAIZ_BACKEND) not in sys.path:
    sys.path.insert(0, str(_RAIZ_BACKEND))

from app.services.sesion_xubio_bot import (  # noqa: E402
    SELECTOR_EMAIL,
    SELECTORES_PASSWORD,
    URL_LOGIN,
    clic_continuar_sesion_activa,
    descartar_banner_cookies,
    leer_env,
)

SALIDA = (
    Path.home()
    / "AppData"
    / "Local"
    / "Temp"
    / "opencode"
    / "xubio_exploracion"
)

CLAVES_RED = (
    "empresa",
    "afiliado",
    "organizacion",
    "cliente",
    "estudio",
    "cuentas",
    "reportcode",
)

RUTA_ENV = Path(__file__).resolve().parent.parent / ".env"

_contador = [0]


def guardar(nombre: str, contenido: str) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / nombre).write_text(contenido, encoding="utf-8")
    print(f"   [dump] {nombre} ({len(contenido)} bytes)")


def volcar_descripcion(page, tag: str) -> None:
    """Guarda HTML, inputs y botones de la pagina actual. Nunca lanza."""
    asyncio.create_task(_volcar(page, tag))


async def _volcar(page, tag: str) -> None:
    try:
        html = await page.evaluate("() => document.documentElement.outerHTML")
        guardar(f"{tag}.html", html[:400000])
        estado = await page.evaluate(
            """() => ({
                url: location.href,
                titulo: document.title,
                texto: (document.body ? document.body.innerText : '').slice(0, 4000),
                inputs: Array.from(document.querySelectorAll('input, textarea, select'))
                    .map(i => ({
                        tag: i.tagName.toLowerCase(), type: i.type, id: i.id,
                        name: i.name, placeholder: i.placeholder,
                        visible: !!i.offsetParent,
                        display: getComputedStyle(i).display,
                        visibility: getComputedStyle(i).visibility,
                        opacity: getComputedStyle(i).opacity,
                        valor: (i.value || '').slice(0, 80),
                    })),
                botones: Array.from(document.querySelectorAll(
                        'button, input[type="submit"], input[type="button"], a'))
                    .map(b => ({
                        tag: b.tagName.toLowerCase(), type: b.type || '',
                        id: b.id || '', clase:
                            (typeof b.className === 'string' ? b.className : '').slice(0, 120),
                        texto: (b.innerText || b.value || '').trim().slice(0, 120),
                        visible: !!b.offsetParent,
                    }))
                    .filter(b => b.visible && b.texto),
            })"""
        )
        guardar(f"{tag}.json", json.dumps(estado, ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001 - diagnostico, jamas corta el flujo
        print(f"   [dump] fallo al volcar {tag}: {e}")


async def pagina_activa(context):
    """La pestana viva de Xubio (el login a veces reemplaza la pagina)."""
    for p in context.pages:
        if "xubio.com" in (p.url or "") or "visma" in (p.url or ""):
            if not p.is_closed():
                return p
    vivas = [p for p in context.pages if not p.is_closed()]
    return vivas[-1] if vivas else None


async def click_por_texto(page, patrones: tuple[str, ...]) -> bool:
    """Clic en el boton visible cuyo texto matchea algun patron, por texto."""
    import re

    for patron in patrones:
        candidatos = page.locator(
            'button, input[type="submit"], input[type="button"], a'
        ).filter(has_text=re.compile(patron, re.I))
        cantidad = await candidatos.count()
        for i in range(cantidad):
            c = candidatos.nth(i)
            try:
                if await c.is_visible():
                    texto = (await c.inner_text(timeout=1000) or "").strip()
                    print(f"   clic por texto {patron!r} -> {texto!r}")
                    await c.click(timeout=4000)
                    return True
            except Exception:
                continue
    return False


async def main() -> int:
    env = leer_env(RUTA_ENV)
    email = (env.get("XUBIO_EMAIL") or "").strip()
    password = env.get("XUBIO_PASSWORD") or ""
    if not email or not password:
        print("Faltan XUBIO_EMAIL / XUBIO_PASSWORD en backend/.env", file=sys.stderr)
        return 2

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Falta playwright", file=sys.stderr)
        return 2

    respuestas: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            slow_mo=80,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = await browser.new_context(locale="es-AR")
        page = await context.new_page()

        async def en_respuesta(response) -> None:
            url = response.url
            if "xubio.com" not in url:
                return
            tipo = (response.headers.get("content-type") or "").lower()
            registro = {"url": url, "status": response.status, "tipo": tipo}
            respuestas.append(registro)
            if not any(c in url.lower() for c in CLAVES_RED):
                return
            if "json" not in tipo and "text" not in tipo:
                return
            try:
                cuerpo = await response.text()
            except Exception:
                return
            registro["bytes"] = len(cuerpo)
            n = len([r for r in respuestas if "guardado" in r])
            guardar(f"red-{n:03d}.txt", f"URL: {url}\nSTATUS: {response.status}\n\n{cuerpo[:20000]}")
            registro["guardado"] = True

        context.on("response", lambda r: asyncio.create_task(en_respuesta(r)))

        try:
            print("1. Login...")
            await page.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
            await descartar_banner_cookies(page)
            volcar_descripcion(page, "paso-00-arranque")

            sesion_activa = await clic_continuar_sesion_activa(page)
            print(f"   sesion activa? {sesion_activa}")

            if not sesion_activa:
                await page.wait_for_selector(SELECTOR_EMAIL, timeout=45000)
                await descartar_banner_cookies(page)
                await page.fill(SELECTOR_EMAIL, email)
                volcar_descripcion(page, "paso-01-email-lleno")
                await page.wait_for_timeout(1500)

                # El form de Visma tiene un boton "Continuar"; si el generico del
                # form no es ese, lo buscamos por texto.
                avanzo = await click_por_texto(
                    page, (r"continuar", r"siguiente", r"next", r"aceptar")
                )
                if not avanzo:
                    from app.services.sesion_xubio_bot import click_continuar

                    avanzo = await click_continuar(page, SELECTOR_EMAIL)
                print(f"   avanzo al segundo paso? {avanzo}")
                await page.wait_for_timeout(3000)

                activa = await pagina_activa(context)
                if activa is not None:
                    volcar_descripcion(activa, "paso-02-tras-continuar")

                # Esperar el password ATTACHED (puede estar en un step oculto).
                try:
                    await activa.wait_for_selector(
                        ", ".join(SELECTORES_PASSWORD),
                        state="attached",
                        timeout=25000,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"   no aparecio el campo password: {e}")

                activa = await pagina_activa(context) or activa
                await descartar_banner_cookies(activa)
                volcar_descripcion(activa, "paso-03-password")

                # Si esta oculto, puede ser que el step no se haya abierto: probar
                # a mostrarlo a mano para ver si el form sigue vivo.
                oculto = await activa.evaluate(
                    """() => {
                        const el = document.querySelector(
                            'input[type="password"], #Password');
                        if (!el) return 'ausente';
                        return !!el.offsetParent ? 'visible' : 'oculto';
                    }"""
                )
                print(f"   estado del campo password: {oculto}")

                lleno = False
                if oculto == "visible":
                    lleno = await activa.evaluate(
                        """([mail, pass]) => {
                            const el = document.querySelector(
                                'input[type="password"], #Password');
                            if (!el) return false;
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            setter.call(el, pass);
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            return true;
                        }""",
                        [email, password],
                    )
                else:
                    from app.services.sesion_xubio_bot import llenar_primero

                    lleno = await llenar_primero(activa, SELECTORES_PASSWORD, password)
                print(f"   lleno el password? {lleno}")
                volcar_descripcion(activa, "paso-04-password-lleno")

                enviado = await click_por_texto(
                    activa, (r"continuar", r"ingresar", r"iniciar", r"entrar", r"next")
                )
                if not enviado:
                    from app.services.sesion_xubio_bot import click_continuar

                    enviado = await click_continuar(
                        activa, 'input[type="password"], #Password'
                    )
                print(f"   envio la contrasena? {enviado}")

            print("2. Esperando la app...")
            esperado = 0
            while esperado < 240:
                activa = await pagina_activa(context)
                if activa and "xubio.com/NXV" in (activa.url or ""):
                    break
                await asyncio.sleep(3)
                esperado += 3
                if esperado % 15 == 0:
                    print(
                        "   ...",
                        [pg.url[:90] for pg in context.pages if not pg.is_closed()],
                    )

            activa = await pagina_activa(context)
            if activa is None:
                print("   no quedo ninguna pestana viva", file=sys.stderr)
                return 1
            print("   url final:", activa.url)
            await activa.wait_for_timeout(6000)
            volcar_descripcion(activa, "paso-05-app")

            print("3. Barra superior...")
            superior = await activa.evaluate(
                """() => {
                    const sel = ['header', '[class*="header"]', '[class*="Header"]',
                                 '[id*="header"]', '[class*="topbar"]',
                                 '[class*="navbar"]', '[class*="empresa"]',
                                 '[class*="empresaSelector"]', '[class*="cuenta"]'];
                    const vistos = [];
                    for (const s of sel) {
                        document.querySelectorAll(s).forEach(el => {
                            if (vistos.includes(el)) return;
                            vistos.push(el);
                        });
                    }
                    return vistos.slice(0, 15).map(el => ({
                        selector: el.tagName.toLowerCase() +
                                  (el.id ? '#'+el.id : '') +
                                  (typeof el.className === 'string' && el.className.trim()
                                      ? '.' + el.className.trim().split(/\\s+/).join('.')
                                      : ''),
                        texto: (el.innerText || '').slice(0, 800),
                        html: el.outerHTML.slice(0, 6000),
                    }));
                }"""
            )
            guardar("barra-superior.json", json.dumps(superior, ensure_ascii=False, indent=2))

            print("4. Candidatos al conmutador de empresa...")
            candidatos = await activa.evaluate(
                """() => {
                    const p = /empresa|estudio|organizacion|compania|company|cuenta|cuentas/i;
                    const salir = [];
                    document.querySelectorAll(
                        'a, button, div, span, li, [role="button"], [role="menuitem"], [id]'
                    ).forEach(el => {
                        const id = el.id || '';
                        const cls = (typeof el.className === 'string') ? el.className : '';
                        const t = (el.innerText || '').trim();
                        if (!p.test(id + ' ' + cls)) return;
                        if (!t || t.length > 200) return;
                        salir.push({ id, clase: cls.slice(0, 200), texto: t.slice(0, 200),
                                     visible: !!el.offsetParent,
                                     html: el.outerHTML.slice(0, 1500) });
                    });
                    return salir.slice(0, 40);
                }"""
            )
            guardar(
                "candidatos-empresa.json",
                json.dumps(candidatos, ensure_ascii=False, indent=2),
            )

            print("5. Abriendo el selector de empresa...")
            selectores = [
                '[class*="empresaSelector"]',
                '[id*="empresa"]',
                '[class*="empresa"]',
                '[class*="Empresa"]',
                '[class*="dropdown"]',
                '[aria-haspopup]',
                '[class*="cuenta"]',
            ]
            abierto = False
            for sel in selectores:
                loc = activa.locator(sel)
                try:
                    cantidad = await loc.count()
                except Exception:
                    continue
                for i in range(min(cantidad, 8)):
                    el = loc.nth(i)
                    try:
                        if not await el.is_visible():
                            continue
                        texto = (await el.inner_text(timeout=1500) or "").strip()
                        if not texto or len(texto) > 150:
                            continue
                        print(f"   clic en {sel}[{i}] = {texto!r}")
                        await el.click(timeout=3000)
                        await activa.wait_for_timeout(2500)
                        abierto = True
                        break
                    except Exception:
                        continue
                if abierto:
                    break

            if abierto:
                print("6. Volcando el desplegable...")
                await activa.wait_for_timeout(1500)
                volcar_descripcion(activa, "paso-06-desplegable")
                opciones = await activa.evaluate(
                    """() => {
                        const salir = [];
                        document.querySelectorAll(
                            '[role="menuitem"], [role="option"], li, tr, a, div'
                        ).forEach(el => {
                            const t = (el.innerText || '').trim();
                            if (!t || t.length > 300 || !el.offsetParent) return;
                            salir.push({ tag: el.tagName.toLowerCase(),
                                         clase: (typeof el.className === 'string'
                                                 ? el.className : '').slice(0, 150),
                                         texto: t.slice(0, 300) });
                        });
                        return salir.slice(0, 150);
                    }"""
                )
                guardar(
                    "opciones-empresa.json",
                    json.dumps(opciones, ensure_ascii=False, indent=2),
                )
            else:
                print("6. No se pudo abrir ningun selector candidato.")

            print("7. Cuerpo y almacenamiento...")
            cuerpo = await activa.evaluate("() => document.body.innerText")
            guardar("cuerpo.txt", cuerpo[:120000])
            almacen = await activa.evaluate(
                """() => {
                    const todas = {};
                    const volcar = (s, pref) => {
                        for (let i = 0; i < s.length; i++) {
                            todas[pref + s.key(i)] = s.getItem(s.key(i));
                        }
                    };
                    try { volcar(localStorage, 'L:'); } catch (e) {}
                    try { volcar(sessionStorage, 'S:'); } catch (e) {}
                    return todas;
                }"""
            )
            guardar("almacenamiento.json", json.dumps(almacen, ensure_ascii=False, indent=2))
            guardar("red-todas.json", json.dumps(respuestas, ensure_ascii=False, indent=2))

        except Exception as e:  # noqa: BLE001 - diagnosticar y salir limpio
            print(f"\nFALLO: {type(e).__name__}: {e}", file=sys.stderr)
            activa = await pagina_activa(context)
            if activa is not None:
                volcar_descripcion(activa, "paso-99-fallo")
                await asyncio.sleep(2)
            guardar("red-todas.json", json.dumps(respuestas, ensure_ascii=False, indent=2))
            return 1
        finally:
            await browser.close()

    print(f"\nListo. Archivos en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
