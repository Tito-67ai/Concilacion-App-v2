"""CLI: renueva la sesion de la web de Xubio (Bearer token + cookie).

El flujo real vive en app/services/sesion_xubio_bot.py (lo reutiliza el login
de la pantalla de conciliacion); este script queda como la via manual que deja
en backend/.env las variables que consume XubioWebClient:

    XUBIO_WEB_TOKEN=...   # Authorization: Bearer <token>
    XUBIO_WEB_COOKIE=...  # header Cookie crudo, formato nombre=valor; ...

Uso:
    uv run python scripts/obtener_sesion_xubio.py
    uv run python scripts/obtener_sesion_xubio.py --email a@b.com --password '...'
    uv run python scripts/obtener_sesion_xubio.py --headless --write

Los datos salen de XUBIO_EMAIL / XUBIO_PASSWORD del .env (o de --email /
--password si se pasan por consola). --write actualiza el .env de backend con
lo capturado; sin el flag solo imprime las lineas para pegar a mano.

Primera vez (instala el navegador de Playwright):
    uv run playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# El script vive en backend/scripts y se corre con `uv run python
# scripts/obtener_sesion_xubio.py` desde backend: ahi Python pone en sys.path
# el directorio del script (scripts/), no el cwd, asi que hay que sumar la raiz
# del backend para poder importar la app.
_RAIZ_BACKEND = Path(__file__).resolve().parent.parent
if str(_RAIZ_BACKEND) not in sys.path:
    sys.path.insert(0, str(_RAIZ_BACKEND))

from app.services.sesion_xubio_bot import (  # noqa: E402
    escribir_env,
    leer_env,
    obtener_sesion_xubio,
)

RUTA_ENV = _RAIZ_BACKEND / ".env"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Saca el token/cookie de la web de Xubio para backend/.env"
    )
    parser.add_argument("--email", default=None, help="Email de Xubio (si no, XUBIO_EMAIL del .env)")
    parser.add_argument("--password", default=None, help="Contrasena de Xubio (si no, XUBIO_PASSWORD del .env)")
    parser.add_argument("--headless", action="store_true", help="Navegador invisible (para un server)")
    parser.add_argument("--slow-mo", type=int, default=50, help="ms entre acciones de Playwright")
    parser.add_argument("--write", action="store_true", help="Actualizar backend/.env con lo capturado")
    args = parser.parse_args(argv)

    env = leer_env(RUTA_ENV)
    email = args.email or env.get("XUBIO_EMAIL", "")
    password = args.password or env.get("XUBIO_PASSWORD", "")

    if not email or not password:
        print(
            "Faltan las credenciales. Pasalas con --email / --password o "
            "defini XUBIO_EMAIL / XUBIO_PASSWORD en backend/.env.",
            file=sys.stderr,
        )
        return 2

    try:
        token, cookie = asyncio.run(
            obtener_sesion_xubio(
                email=email,
                password=password,
                headless=args.headless,
                slow_mo=args.slow_mo,
            )
        )
    except Exception as e:  # PlaywrightTimeoutError, RuntimeError, ...
        print(f"\nFallo la obtencion de la sesion: {e}", file=sys.stderr)
        return 1

    print("\n--- Sesion capturada ---")
    if token:
        print(f"XUBIO_WEB_TOKEN={token}")
    else:
        print("# (no se capturo token Bearer)")
    if cookie:
        print(f"XUBIO_WEB_COOKIE={cookie}")
    else:
        print("# (no se capturaron cookies de sesion)")

    if args.write:
        actualizar = {}
        if token:
            actualizar["XUBIO_WEB_TOKEN"] = token
        if cookie:
            actualizar["XUBIO_WEB_COOKIE"] = cookie
        if actualizar:
            escribir_env(actualizar, RUTA_ENV)
            print(f"\nActualizado {RUTA_ENV}.")
        else:
            print("\nNada que escribir en el .env.")
    else:
        print(
            "\nPara guardarlas: vuelve a correr con --write, o pega las lineas "
            "en backend/.env."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())