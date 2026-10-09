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
    """

    RUTA_CLIENTES = "/ar/sba/api/cliente/clientes/findAllPaginado"
    # El Libro Mayor se baja con el mismo POST XML que arma el frontend web.
    RUTA_LIBRO_MAYOR = "/NXV/webreport/data"
    # Empresa fija de este estudio en el payload del reporte. Si la app llega
    # a manejar varias cuentas de Xubio, esto tiene que pasar a ser un
    # parametro dinámico, igual que las fechas.
    EMPRESA_REPORT_CODE = "29774"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = settings.XUBIO_WEB_URL.rstrip("/")
        # Solo para los tests: los tests le inyectan un MockTransport y el
        # cliente nunca toca la red.
        self._transport = transport

    @property
    def _cookie(self) -> str:
        return (settings.XUBIO_WEB_COOKIE or "").strip()

    @property
    def _token(self) -> str:
        return (settings.XUBIO_WEB_TOKEN or "").strip()

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

    async def obtener_afiliados(self, tamano_pagina: int = 20) -> list[dict]:
        """Descarga la lista completa de afiliados, pagina tras pagina."""
        afiliados: list[dict] = []
        pagina = 0
        total_esperado: int | None = None

        while True:
            url = (
                f"{self.base_url}{self.RUTA_CLIENTES}"
                f"/{pagina}/{tamano_pagina}"
            )
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                respuesta = await client.get(url, headers=self.headers)
                respuesta.raise_for_status()
                cuerpo = respuesta.json()

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

    async def obtener_libro_mayor(
        self,
        desde: str | None = None,
        hasta: str | None = None,
        empresa_report_code: str = EMPRESA_REPORT_CODE,
    ) -> dict:
        """Baja el Libro Mayor por la misma via que el navegador (webreport).

        No es la API oficial: es el POST XML que arma el frontend de Xubio en
        /NXV/webreport/data con la sesion (cookie o Bearer), asi que sirve
        igual cuando la cuenta no tiene habilitada la API oficial. Las fechas
        van dentro del payload; si no se pasan, el rango es los ultimos 30
        dias. El JSON de la grilla se devuelve crudo: el parseo a movimientos
        vive en el backend, igual que con los afiliados.
        """
        desde = desde or (date.today() - timedelta(days=30)).isoformat()
        hasta = hasta or date.today().isoformat()

        payload_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<postData>
    <userData><![CDATA[]]></userData>
    <parameters>
        <parameter type="FafDate" name="p_FechaDesde" value="{desde}" />
        <parameter type="FafDate" name="p_FechaHasta" value="{hasta}" />
        <parameter type="" name="p_CuentaReportCode" value="ARBOL_ID=1__SEPNO__0" />
        <parameter type="FafBoolean" name="p_SoloConSaldo" value="false" />
        <parameter type="" name="p_OrganizacionReportCode" value="" />
        <parameter type="FafBoolean" name="p_IncluirClientes" value="true" />
        <parameter type="FafBoolean" name="p_IncluirProveedores" value="true" />
        <parameter type="" name="p_MonedaReportCode" value="" />
        <parameter type="" name="p_EmpresaReportCode" value="{empresa_report_code}" />
        <parameter type="FafInteger" name="p_VerPor" value="0" />
        <parameter type="FafBoolean" name="p_SoloCuentasDisponibilidad" value="false" />
        <parameter type="" name="p_circuitoContable" value="-2" />
        <parameter type="FafBoolean" name="p_excluirUltimoCierreResultados" value="false" />
        <parameter type="FafBoolean" name="p_excluirUltimoCierrePatrimonial" value="false" />
    </parameters>
</postData>"""

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
            try:
                return respuesta.json()
            except ValueError:
                return {"respuesta_texto": respuesta.text}