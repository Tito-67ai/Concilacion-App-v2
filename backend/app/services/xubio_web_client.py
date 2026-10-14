import logging
from datetime import date, timedelta

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class XubioWebNoConfigurado(RuntimeError):
    """Faltan las credenciales de la web de Xubio en el .env (cookie o token)."""


class XubioWebClient:
    """
    Cliente de la API interna que usa el frontend web de Xubio
    (core.xubio.com).

    No es la API oficial: esa se autentica con Basic (xubio_client.py) y esta
    reservada a planes superiores. Esta ruta es la misma que llama el
    navegador de Xubio con la sesion abierta, y por eso solo sirve para LEER
    (afiliados/clientes y el Libro Mayor via webreport). Se autentica con la
    cookie de sesion (XUBIO_WEB_COOKIE) o con el token Authorization Bearer
    (XUBIO_WEB_TOKEN) copiado del .env: alcanza con cualquiera de las dos, y
    si hay ambas se mandan las dos.

    El endpoint de clientes pagina de a 20 (clientes/findAllPaginado/{pagina}/
    {tamano}), asi que descargar la lista completa exige pegarle a todas las
    paginas hasta que la respuesta diga last=true. El Libro Mayor, en cambio,
    es un POST XML a /NXV/webreport/data con el rango de fechas en el payload,
    igual que lo arma el frontend web.

    Resiliencia: si Xubio responde 401/403 (token vencido) y se le pasa un
    callback `renovar_sesion` (el login del bot, fase 1), el cliente renueva la
    sesion y reintenta la misma llamada hasta `max_reintentos` veces. Los
    headers se arman dentro de cada intento, asi el reintento manda el token
    nuevo y no el vencido.
    """

    RUTA_CLIENTES = "/ar/sba/api/cliente/clientes/findAllPaginado"
    # El Libro Mayor se baja con el mismo POST XML que arma el frontend web.
    RUTA_LIBRO_MAYOR = "/NXV/webreport/data"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        renovar_sesion=None,
        max_reintentos: int = 2,
    ):
        self.base_url = settings.XUBIO_WEB_URL.rstrip("/")
        # Solo para los tests: los tests le inyectan un MockTransport y el
        # cliente nunca toca la red.
        self._transport = transport
        # Callback async para rehacer el login (fase 1) cuando la sesion en
        # cache quedo vencida. Si es None, un 401/403 se propaga sin reintentar
        # (comportamiento historico).
        self._renovar_sesion = renovar_sesion
        self._max_reintentos = max_reintentos

    @property
    def _cookie(self) -> str:
        return (settings.XUBIO_WEB_COOKIE or "").strip()

    @property
    def _token(self) -> str:
        return (settings.XUBIO_WEB_TOKEN or "").strip()

    @property
    def _empresa_report_code(self) -> str:
        return (settings.XUBIO_WEB_EMPRESA_REPORT_CODE or "").strip()

    @property
    def _cuenta_report_code(self) -> str:
        return (settings.XUBIO_WEB_CUENTA_REPORT_CODE or "").strip()

    @property
    def headers(self) -> dict:
        headers = {"Accept": "application/json"}
        cookie = self._cookie
        token = self._token
        if cookie:
            headers["Cookie"] = cookie
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if not cookie and not token:
            raise XubioWebNoConfigurado(
                "Faltan XUBIO_WEB_COOKIE y XUBIO_WEB_TOKEN en el .env. "
                "Son las credenciales de la web de Xubio: la cookie de sesion "
                "o el token Authorization (Bearer) de una peticion a "
                "clientes/findAllPaginado (pestana Network -> Copy as cURL)."
            )
        return headers

    async def _con_reintento(self, operacion, contexto: str = ""):
        """Corre `operacion` y, ante un 401/403, renueva la sesion y reintenta.

        La operacion tiene que armar los headers adentro (`self.headers` es una
        property) para que el reintento mande el token/la cookie recien
        capturados y no los vencidos. Sin callback de renovacion, el error se
        propaga tal cual.
        """
        intentos = 0
        while True:
            try:
                return await operacion()
            except httpx.HTTPStatusError as e:
                codigo = e.response.status_code
                puede_renovar = (
                    codigo in (401, 403)
                    and self._renovar_sesion is not None
                    and intentos < self._max_reintentos
                )
                if not puede_renovar:
                    raise
                intentos += 1
                logger.warning(
                    "Xubio respondio %s%s: renuevo la sesion y reintento (%d/%d)",
                    codigo,
                    f" ({contexto})" if contexto else "",
                    intentos,
                    self._max_reintentos,
                )
                try:
                    await self._renovar_sesion()
                except Exception as e:  # noqa: BLE001
                    # Sin sesion renovable no hay reintento posible: se trata
                    # como "no configurado" para que el pipeline ofrezca la
                    # carga manual en vez de un error crudo.
                    raise XubioWebNoConfigurado(
                        f"No se pudo renovar la sesion de Xubio: {e}"
                    ) from e

    async def _bajar_pagina(self, pagina: int, tamano_pagina: int) -> dict:
        """Baja una sola pagina de clientes. Los headers se arman aca adentro."""
        url = f"{self.base_url}{self.RUTA_CLIENTES}/{pagina}/{tamano_pagina}"
        async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
            respuesta = await client.get(url, headers=self.headers)
            respuesta.raise_for_status()
            return respuesta.json()

    async def obtener_afiliados(self, tamano_pagina: int = 20) -> list[dict]:
        """Descarga la lista completa de afiliados, pagina tras pagina."""
        afiliados: list[dict] = []
        pagina = 0
        total_esperado: int | None = None

        while True:
            cuerpo = await self._con_reintento(
                lambda p=pagina: self._bajar_pagina(p, tamano_pagina),
                contexto=f"afiliados pagina {pagina}",
            )

            if total_esperado is None:
                total_esperado = cuerpo.get("totalElements")

            afiliados.extend(cuerpo.get("content") or [])

            if cuerpo.get("last") or not cuerpo.get("content"):
                break
            pagina += 1
            if total_esperado is not None and len(afiliados) >= total_esperado:
                break

        unicos: dict = {}
        for afiliado in afiliados:
            unicos[afiliado.get("id")] = afiliado
        return list(unicos.values())

    async def _post_webreport(self, payload_xml: str) -> httpx.Response:
        """POST XML al webreport. Los headers se arman aca adentro (retry)."""
        url = (
            f"{self.base_url}{self.RUTA_LIBRO_MAYOR}"
            "?layout=LibroMayorNXVWebReportGridLayout&fafViewID=50526&view=null"
        )
        # self.headers levanta XubioWebNoConfigurado si no hay cookie ni token:
        # sin credenciales de sesion no se arma ninguna llamada.
        headers = {"Content-Type": "application/xml", **self.headers}
        async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as client:
            respuesta = await client.post(url, headers=headers, content=payload_xml)
            respuesta.raise_for_status()
            return respuesta

    async def obtener_libro_mayor(
        self,
        desde: str | None = None,
        hasta: str | None = None,
        empresa_report_code: str | None = None,
        organizacion_report_code: str | None = None,
    ) -> dict:
        """Baja el Libro Mayor por la misma via que el navegador (webreport).

        No es la API oficial: es el POST XML que arma el frontend de Xubio en
        /NXV/webreport/data con la sesion (cookie o Bearer), asi que sirve
        igual cuando la cuenta no tiene habilitada la API oficial. Las fechas
        van dentro del payload; si no se pasan, el rango es los ultimos 30
        dias. El JSON de la grilla se devuelve crudo: el parseo a movimientos
        vive en el backend, igual que con los afiliados.

        La empresa sale de XUBIO_WEB_EMPRESA_REPORT_CODE (la detecta el bot al
        loguearse) o del parametro. Si no hay ninguna configurada se manda
        VACIA y el webreport resuelve la empresa de la sesion: un codigo
        guardado de otra cuenta devolvia 0 filas sin decir por que, y la sesion
        (que es la del usuario logueado) es la fuente de verdad.

        `organizacion_report_code` filtra el reporte a un cliente/proveedor
        puntual (campo p_OrganizacionReportCode). Va vacio por defecto: es el
        mismo caso que la empresa, el webreport resuelve la organizacion de la
        sesion y mandar un codigo equivocado devolvia 0 filas sin decir por que.
        """
        desde = desde or (date.today() - timedelta(days=30)).isoformat()
        hasta = hasta or date.today().isoformat()

        empresa = (empresa_report_code or self._empresa_report_code).strip()
        organizacion = (organizacion_report_code or "").strip()
        cuenta = self._cuenta_report_code

        payload_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<postData>
    <userData><![CDATA[]]></userData>
    <parameters>
        <parameter type="FafDate" name="p_FechaDesde" value="{desde}" />
        <parameter type="FafDate" name="p_FechaHasta" value="{hasta}" />
        <parameter type="" name="p_CuentaReportCode" value="{cuenta}" />
        <parameter type="FafBoolean" name="p_SoloConSaldo" value="false" />
        <parameter type="" name="p_OrganizacionReportCode" value="{organizacion}" />
        <parameter type="FafBoolean" name="p_IncluirClientes" value="true" />
        <parameter type="FafBoolean" name="p_IncluirProveedores" value="true" />
        <parameter type="" name="p_MonedaReportCode" value="" />
        <parameter type="" name="p_EmpresaReportCode" value="{empresa}" />
        <parameter type="FafInteger" name="p_VerPor" value="0" />
        <parameter type="FafBoolean" name="p_SoloCuentasDisponibilidad" value="false" />
        <parameter type="" name="p_circuitoContable" value="-2" />
        <parameter type="FafBoolean" name="p_excluirUltimoCierreResultados" value="false" />
        <parameter type="FafBoolean" name="p_excluirUltimoCierrePatrimonial" value="false" />
    </parameters>
</postData>"""

        respuesta = await self._con_reintento(
            lambda: self._post_webreport(payload_xml),
            contexto="libro mayor",
        )
        ctype = (respuesta.headers.get("content-type") or "").lower()
        # El webreport real devuelve XML (application/xml o text/xml). Si trae
        # JSON (tests o fallback), lo parseamos; si no, devolvemos el texto
        # crudo para que leer_mayor_desde_json lo detecte por <?xml.
        if "xml" in ctype:
            return respuesta.text
        try:
            return respuesta.json()
        except ValueError:
            return respuesta.text