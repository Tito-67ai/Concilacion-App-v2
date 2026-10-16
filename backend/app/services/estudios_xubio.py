"""Selector de Estudio/Empresa de la cuenta de Xubio.

La cuenta de un estudio contable habilita decenas de empresas (un cliente por
estudio). El selector de la barra superior de la web de Xubio (la app NXV) las
lista todas, y cambiar de estudio ahi es un /NXV/Relogin?tenant=tnt_XXXX.

Esa lista NO tiene endpoint: vive en el HTML servido por /NXV/home, dentro de
un <ul id="compania-lista"> con un <li class="licomp"> por estudio y un
<a href="/NXV/Relogin?tenant=tnt_XXXX"> con el id de tenant y el nombre.

Por eso el catalogo de estudios se junta de DOS fuentes y las dos se guardan:

  * el selector superior (bot de Playwright, al loguearse): da el nombre y el
    tenant de cada estudio, en el orden en que los muestra Xubio.
  * el catalogo de clientes de la contabilidad (por HTTP, el mismo de
    /api/xubio/afiliados): da el CUIT y el organizacionId, que es el codigo
    con el que el Libro Mayor filtra por empresa (p_OrganizacionReportCode).

`extraer_estudios` y `extraer_empresa_en_sesion` son puros: reciben el HTML y
devuelven la lista, sin navegador ni red, asi que se prueban con el marcado
real.

Lo que el usuario elige en el selector se persiste en el .env
(XUBIO_ESTUDIO_CLAVE/NOMBRE/TENANT y XUBIO_ORGANIZACION_REPORT_CODE) y tambien
vive en `settings`, igual que la sesion: el cliente de la web lee la config en
cada request y sin eso la eleccion no serviria hasta reiniciar uvicorn.
"""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from app.core.config import RAIZ_BACKEND, settings
from app.models.schemas import Estudio

logger = logging.getLogger(__name__)

RUTA_ENV = RAIZ_BACKEND / ".env"
# El catalogo puede ser grande (un estudio contable tiene cientos de clientes)
# y el .env es un archivo de configuracion, no un deposito de datos: la lista
# va en un JSON de trabajo al lado, que no se versiona.
RUTA_CATALOGO = RAIZ_BACKEND / ".xubio_estudios.json"

# Cada entrada guarda su origen en la clave, asi la misma clave no puede
# designar dos cosas distintas si una fuente y la otra traen ids numericos
# que se pisan.
PREFIJO = {"empresa": "empresa", "cliente": "cliente"}


# --------------------------------------------------------------------------
# Lectura del selector superior (pura: recibe el HTML de /NXV/home)
# --------------------------------------------------------------------------

# Marcado real del selector (app NXV). El <a> de cada estudio trae el tenant
# en la query y el nombre como texto.
_PATRON_ESTUDIO = re.compile(
    r'<li\s+class="licomp">\s*<a\s+href="/NXV/Relogin\?tenant=(tnt_\d+)"[^>]*>(.*?)</a>',
    re.I | re.S,
)

# La empresa que tiene abierta la sesion aparece en la cabecera del selector,
# no en la lista: es el <span class="nombre-tenant"> del <a id=resaltarCompania>.
_PATRON_EMPRESA_ACTUAL = re.compile(
    r'class="nombre-tenant"[^>]*>\s*(.*?)\s*</span>',
    re.I | re.S,
)


def _limpiar(texto: str) -> str:
    """Saca etiquetas y decodifica entidades del texto de un nodo del DOM."""
    sin_etiquetas = re.sub(r"<[^>]+>", "", texto or "")
    return " ".join(html.unescape(sin_etiquetas).split())


def extraer_estudios(html_pagina: str) -> list[dict]:
    """Las empresas del selector superior, a partir del HTML de /NXV/home.

    Devuelve [{"clave", "nombre", "tenant"}] en el orden que las muestra
    Xubio (el selector ya viene ordenado alfabeticamente). Los tenants repetidos
    se descartan: si el HTML trae la lista pintada dos veces, dos veces no son
    dos estudios.
    """
    vistos: set[str] = set()
    estudios: list[dict] = []
    for tenant, nombre_crudo in _PATRON_ESTUDIO.findall(html_pagina or ""):
        if tenant in vistos:
            continue
        nombre = _limpiar(nombre_crudo)
        if not nombre:
            continue
        vistos.add(tenant)
        estudios.append(
            {
                "clave": f"{PREFIJO['empresa']}:{tenant}",
                "nombre": nombre,
                "tenant": tenant,
            }
        )
    return estudios


def extraer_empresa_en_sesion(html_pagina: str) -> str | None:
    """El nombre de la empresa que tiene abierta la sesion de Xubio."""
    coincidencia = _PATRON_EMPRESA_ACTUAL.search(html_pagina or "")
    if not coincidencia:
        return None
    nombre = _limpiar(coincidencia.group(1))
    return nombre or None


# --------------------------------------------------------------------------
# Emparejar las dos fuentes
# --------------------------------------------------------------------------

# Sufijos societarios argentinos que no distinguen a un estudio de otro: una
# misma empresa puede figurar como "GOMEZ S.A." en el selector y como "GOMEZ"
# en el catalogo de clientes, o al reves.
_SUFIJOS_SOCIETARIOS = (
    " SA",
    " S A",
    " SRL",
    " S R L",
    " SCS",
    " S C S",
    " SAS",
    " S A S",
    " SCI",
    " S C I",
    " E HIJOS",
    " E HIJO",
    " HNOS",
    " HERMANOS",
)


def normalizar_nombre(nombre: str) -> str:
    """Deja un nombre comparable: mayusculas, sin acentos ni puntuacion."""
    base = unicodedata.normalize("NFKD", nombre or "")
    sin_acentos = "".join(c for c in base if not unicodedata.combining(c))
    limpio = re.sub(r"[^A-Za-z0-9]+", " ", sin_acentos)
    return " ".join(limpio.split()).upper()


def _sin_sufijo(nombre_normalizado: str) -> str:
    """Quita el sufijo societario del final, si lo tiene."""
    for sufijo in _SUFIJOS_SOCIETARIOS:
        if nombre_normalizado.endswith(sufijo):
            return nombre_normalizado[: -len(sufijo)].strip()
    return nombre_normalizado


def nombres_coinciden(a: str, b: str) -> bool:
    """True si los dos nombres nombran al mismo estudio.

    Compara normalizado (sin acentos ni puntuacion) y ademas sin el sufijo
    societario: "GOMEZ S.A." y "GOMEZ" son el mismo. Un nombre vacio nunca
    coincide, asi que una fuente sin nombre no arrastra a la otra.
    """
    na, nb = normalizar_nombre(a), normalizar_nombre(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return _sin_sufijo(na) == _sin_sufijo(nb)


def _estudio_de_cliente(cliente: dict) -> dict:
    """Un afiliado del catalogo de clientes como entrada de estudio."""
    cliente_id = cliente.get("id")
    organizacion = cliente.get("organizacionId")
    return {
        "clave": f"{PREFIJO['cliente']}:{cliente_id}",
        "nombre": (cliente.get("organizacionNombre") or "").strip(),
        "origen": "cliente",
        "cuit": (cliente.get("cuit") or None),
        # El organizacionId es el codigo con el que el Libro Mayor filtra la
        # empresa (p_OrganizacionReportCode); sin el, el webreport resuelve la
        # empresa de la sesion.
        "organizacion_id": int(organizacion) if organizacion else None,
        "activo": bool(cliente.get("activo", 1)),
    }


def combinar_fuentes(
    empresas: list[dict], clientes: list[dict]
) -> tuple[list[Estudio], list[Estudio]]:
    """Junta las dos fuentes y devuelve (estudios, solo_clientes).

    `estudios` es el selector superior, con el CUIT y el organizacionId del
    catalogo de clientes pegados cuando hay un cliente con el mismo nombre: son
    los estudios que se muestran en el selector. `solo_clientes` es el catalogo
    que no matcheo ninguna empresa del selector: se devuelve aparte para no
    perderlo, porque un cliente puede existir en la contabilidad sin estar
    habilitado como empresa de la entrada.
    """
    por_nombre: dict[str, dict] = {}
    for cliente in clientes:
        clave_nombre = normalizar_nombre(cliente.get("organizacionNombre") or "")
        if clave_nombre:
            por_nombre.setdefault(clave_nombre, cliente)

    combinados: list[Estudio] = []
    # Los clientes que ya quedaron pegados a una empresa del selector: lo que
    # sobra de ese lado se devuelve aparte.
    matcheados: set[str] = set()
    for empresa in empresas:
        nombre = empresa.get("nombre") or ""
        cliente = _buscar_cliente(nombre, por_nombre)
        if cliente is not None:
            matcheados.add(f"{PREFIJO['cliente']}:{cliente.get('id')}")
        combinados.append(
            Estudio(
                clave=empresa["clave"],
                nombre=nombre,
                origen="ambos" if cliente else "empresa",
                tenant=empresa.get("tenant"),
                # El organizacionId del cliente matcheado: con eso el Libro
                # Mayor sale filtrado por este estudio y no por el de la sesion.
                organizacion_id=(_organizacion_de(cliente) if cliente else None),
                cuit=(cliente or {}).get("cuit") or None,
            )
        )

    solo_clientes = [
        Estudio(**_estudio_de_cliente(c))
        for c in clientes
        if f"{PREFIJO['cliente']}:{c.get('id')}" not in matcheados
    ]
    return combinados, solo_clientes


def _organizacion_de(cliente: dict | None) -> int | None:
    if not cliente:
        return None
    valor = cliente.get("organizacionId")
    try:
        return int(valor) if valor else None
    except (TypeError, ValueError):
        return None


def _buscar_cliente(nombre: str, por_nombre: dict[str, dict]) -> dict | None:
    """El cliente del catalogo que tiene ese nombre (normalizado o sin sufijo)."""
    normalizado = normalizar_nombre(nombre)
    if not normalizado:
        return None
    if normalizado in por_nombre:
        return por_nombre[normalizado]
    objetivo = _sin_sufijo(normalizado)
    for clave, cliente in por_nombre.items():
        if _sin_sufijo(clave) == objetivo:
            return cliente
    return None


# --------------------------------------------------------------------------
# Catalogo en disco
# --------------------------------------------------------------------------


def cargar_catalogo() -> dict:
    """El catalogo guardado. Vacio si todavia no se bajo ninguna vez."""
    if not RUTA_CATALOGO.exists():
        return {"estudios": [], "solo_clientes": [], "empresa_en_sesion": None}
    try:
        datos = json.loads(RUTA_CATALOGO.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # Un catalogo ilegible no es motivo para romper el arranque: se trata
        # como "todavia no se bajo" y el proximo login lo vuelve a escribir.
        logger.warning("No se pudo leer el catalogo de estudios: %s", e)
        return {"estudios": [], "solo_clientes": [], "empresa_en_sesion": None}
    return {
        "estudios": datos.get("estudios", []),
        "solo_clientes": datos.get("solo_clientes", []),
        "empresa_en_sesion": datos.get("empresa_en_sesion"),
        "actualizado": datos.get("actualizado"),
    }


def guardar_catalogo(
    empresas: list[dict],
    clientes: list[dict],
    empresa_en_sesion: str | None = None,
) -> dict:
    """Combina las dos fuentes, las guarda y devuelve el catalogo.

    Es lo que llama el bot de login despues de capturar la sesion: el mismo
    paso que baja el token tambien baja el catalogo, para que el selector tenga
    datos sin un viaje extra a la web de Xubio.
    """
    estudios, solo_clientes = combinar_fuentes(empresas, clientes)
    catalogo = {
        "actualizado": datetime.now().isoformat(timespec="seconds"),
        "empresa_en_sesion": empresa_en_sesion,
        "estudios": [e.model_dump() for e in estudios],
        "solo_clientes": [e.model_dump() for e in solo_clientes],
    }
    RUTA_CATALOGO.write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "Catalogo de estudios guardado: %d del selector + %d solo clientes",
        len(estudios),
        len(solo_clientes),
    )
    return catalogo


# --------------------------------------------------------------------------
# Estudio elegido en la app
# --------------------------------------------------------------------------


def estudio_actual() -> Estudio | None:
    """El estudio elegido en el selector, o None si todavia no se elige ninguno."""
    clave = (settings.XUBIO_ESTUDIO_CLAVE or "").strip()
    if not clave:
        return None
    nombre = (settings.XUBIO_ESTUDIO_NOMBRE or "").strip()
    if not nombre:
        # La clave sin nombre seria un selector que no se puede pintar: mejor
        # tratarlo como "no hay estudio" que mostrar una clave cruda.
        return None
    tenant = (settings.XUBIO_ESTUDIO_TENANT or "").strip() or None
    organizacion = (settings.XUBIO_ORGANIZACION_REPORT_CODE or "").strip() or None
    origen = clave.split(":", 1)[0] if ":" in clave else "empresa"
    return Estudio(
        clave=clave,
        nombre=nombre,
        origen=origen if origen in ("empresa", "cliente") else "empresa",
        tenant=tenant,
        organizacion_id=int(organizacion) if organizacion else None,
        # Es, por definicion, el estudio elegido.
        es_actual=True,
    )


def organizacion_report_code_actual() -> str | None:
    """El codigo de organizacion con el que el Libro Mayor filtra el estudio.

    Es lo que va en p_OrganizacionReportCode. Vacio (no None) si no hay estudio
    elegido o si el estudio salio del selector superior y no tiene
    organizacionId: el webreport entonces resuelve la empresa de la sesion,
    que es el comportamiento viejo de la app.
    """
    actual = estudio_actual()
    if actual is None or actual.organizacion_id is None:
        return ""
    return str(actual.organizacion_id)


def seleccionar_estudio(clave: str) -> Estudio:
    """Elige un estudio del catalogo y lo persiste en el .env y en `settings`.

    Levanta KeyError si la clave no esta en el catalogo: elegir un estudio que
    no existe cerraria el Libro Mayor contra una empresa equivocada y nadie
    tendria como adivinar el motivo.
    """
    catalogo = cargar_catalogo()
    candidatos = catalogo["estudios"] + catalogo["solo_clientes"]
    elegido = next((e for e in candidatos if e.get("clave") == clave), None)
    if elegido is None:
        raise KeyError(clave)

    # Si el estudio salio del selector superior no tiene organizacionId: el
    # filtro del Libro Mayor queda vacio y manda el de la sesion.
    organizacion = elegido.get("organizacion_id")
    valores = {
        "XUBIO_ESTUDIO_CLAVE": clave,
        "XUBIO_ESTUDIO_NOMBRE": elegido.get("nombre") or "",
        "XUBIO_ESTUDIO_TENANT": elegido.get("tenant") or "",
        "XUBIO_ORGANIZACION_REPORT_CODE": str(organizacion) if organizacion else "",
    }
    from app.services.sesion_xubio_bot import escribir_env

    escribir_env(valores, RUTA_ENV)
    settings.XUBIO_ESTUDIO_CLAVE = valores["XUBIO_ESTUDIO_CLAVE"]
    settings.XUBIO_ESTUDIO_NOMBRE = valores["XUBIO_ESTUDIO_NOMBRE"]
    settings.XUBIO_ESTUDIO_TENANT = valores["XUBIO_ESTUDIO_TENANT"]
    settings.XUBIO_ORGANIZACION_REPORT_CODE = valores["XUBIO_ORGANIZACION_REPORT_CODE"]

    logger.info("Estudio seleccionado: %s (%s)", clave, valores["XUBIO_ESTUDIO_NOMBRE"])
    return estudio_actual()  # type: ignore[return-value]


def limpiar_estudio() -> None:
    """Quita el estudio elegido: el selector vuelve a "elegi un estudio"."""
    from app.services.sesion_xubio_bot import escribir_env

    escribir_env(
        {
            "XUBIO_ESTUDIO_CLAVE": "",
            "XUBIO_ESTUDIO_NOMBRE": "",
            "XUBIO_ESTUDIO_TENANT": "",
            "XUBIO_ORGANIZACION_REPORT_CODE": "",
        },
        RUTA_ENV,
    )
    settings.XUBIO_ESTUDIO_CLAVE = ""
    settings.XUBIO_ESTUDIO_NOMBRE = ""
    settings.XUBIO_ESTUDIO_TENANT = ""
    settings.XUBIO_ORGANIZACION_REPORT_CODE = ""
