from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# La raiz del backend, para encontrar el .env aunque uvicorn se levante de otro lado
RAIZ_BACKEND = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ_BACKEND / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    API_XUBIO_URL: str = "https://api.xubio.com"

    # Vienen del .env. Se dejan vacios para que la app levante igual, pero el
    # cliente de Xubio no hace ninguna llamada sin ellos.
    XUBIO_CLIENT_ID: str = ""
    XUBIO_CLIENT_SECRET: str = ""

    # API interna del frontend web de Xubio (core.xubio.com), para leer la
    # lista de afiliados. NO es la API oficial: no acepta Basic, autentica con
    # la cookie de sesion del navegador o con el token "Authorization: Bearer"
    # de las peticiones de esa web. Ambas van en el .env local, nunca
    # versionadas (xubio_web_client.py). Con cualquiera de las dos alcanza;
    # sin ninguna, los endpoints de afiliados responden 503 sin llamar a nadie.
    XUBIO_WEB_URL: str = "https://core.xubio.com"
    XUBIO_WEB_COOKIE: str = ""
    XUBIO_WEB_TOKEN: str = ""

    # Empresa y cuenta del reporte del Libro Mayor (el POST XML a webreport).
    # El bot de login las detecta de la sesion y las reescribe aca; si no las
    # detecta, el default queda VACIO a proposito: el webreport resuelve la
    # empresa de la sesion. Un codigo fijo de otra cuenta devolvia 0 filas sin
    # decir por que. La cuenta si tiene un valor util por defecto (el arbol
    # completo) para que el reporte no salga acotado a una sola cuenta.
    XUBIO_WEB_EMPRESA_REPORT_CODE: str = ""
    XUBIO_WEB_CUENTA_REPORT_CODE: str = "ARBOL_ID=1__SEPNO__0"

    # El estudio que el usuario eligio en el selector de la barra superior.
    # `clave` es la identidad del estudio dentro de la app ("empresa:tnt_123456"
    # si salio del selector superior, "cliente:123" si salio del catalogo de
    # clientes); `tenant` es el con el que se cambia de estudio en la web y
    # `organizacion_id` el codigo con el que el Libro Mayor filtra por empresa
    # (p_OrganizacionReportCode). Quedan vacios hasta que el usuario elige: no
    # se inventa un estudio por defecto porque el mayor de otro estudio cerraria
    # con cifras que parecen reales.
    XUBIO_ESTUDIO_CLAVE: str = ""
    XUBIO_ESTUDIO_NOMBRE: str = ""
    XUBIO_ESTUDIO_TENANT: str = ""
    XUBIO_ORGANIZACION_REPORT_CODE: str = ""

    # El bot de sesion (sesion_xubio_bot.py) abre el navegador de Playwright
    # visible por defecto, porque el login de Visma Connect puede pedir captcha
    # o verificacion que se completa a mano en esa ventana. En un server de
    # verdad conviene True (invisible), aunque ahi esos pasos no se pueden
    # completar y el intento falla con un aviso.
    XUBIO_BOT_HEADLESS: bool = False

    # El Angular corre en 4200. Hay que habilitar las dos formas de escribirlo:
    # si se abre http://localhost:4200 el origen es uno, y si se abre
    # http://127.0.0.1:4200 es otro, y el navegador los distingue.
    CORS_ORIGINS: list[str] = [
        "http://localhost:4200",
        "http://127.0.0.1:4200",
    ]

    # Puerto que espera el frontend. conciliacion.ts llama a http://127.0.0.1:8000
    # de forma directa, sin proxy, asi que el backend tiene que escuchar ahi.
    PUERTO: int = 8000

    # Logo de la empresa que va en el recuadro A1:B3 del membrete del papel de
    # trabajo FO 02-03. Por defecto el que viene con la app (assets/logos/logo.
    # png); se puede apuntar a otro archivo con LOGO_EMPRESA en el .env. Si el
    # archivo no existe, la exportacion sigue sin logo en vez de romperse.
    LOGO_EMPRESA: str = str(RAIZ_BACKEND / "app" / "assets" / "logos" / "logo.png")

    # Cuentas contables que usa el generador de asientos de ajuste
    # (asientos_ajuste.py) para las partidas que no encontraron coincidencia en
    # el cruce. Son solo nombres de cuenta: el asiento no se registra en Xubio,
    # se exporta en el papel de trabajo para que el contador lo cargue. Se
    # pueden reescribir desde el .env sin tocar el codigo porque el plan de
    # cuentas es de cada empresa.
    CUENTA_BANCO: str = "Banco"
    CUENTA_GASTOS_BANCARIOS: str = "Gastos bancarios"
    CUENTA_RETENCIONES: str = "Retenciones e impuestos a favor"
    CUENTA_CONCILIACION_BANCO: str = "Cuentas a conciliar - Banco"
    CUENTA_CONCILIACION_MAYOR: str = "Cuentas a conciliar - Libro Mayor"

    # Codigos del plan de cuentas de cada una de las anteriores. Van vacios por
    # defecto: la app funciona solo con nombres, pero la pantalla de revision y
    # el conector de Xubio prefieren el codigo para no depender del texto. Se
    # cargan desde el .env segun el plan de cuentas de la empresa.
    CUENTA_BANCO_CODIGO: str = ""
    CUENTA_GASTOS_BANCARIOS_CODIGO: str = ""
    CUENTA_RETENCIONES_CODIGO: str = ""
    CUENTA_CONCILIACION_BANCO_CODIGO: str = ""
    CUENTA_CONCILIACION_MAYOR_CODIGO: str = ""

    # Si es True, el endpoint de inyeccion de asientos no llama a Xubio: arma el
    # payload y devuelve el resultado simulado. Sirve para probar la pantalla de
    # revision sin credenciales ni riesgo de cargar asientos de verdad.
    XUBIO_INJECT_DRY_RUN: bool = True


# Instancia global para usar en toda la app
settings = Settings()