import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class XubioNoConfigurado(RuntimeError):
    """Faltan credenciales de Xubio, o la API no esta accessible."""


class XubioClient:
    """
    Cliente de la API de Xubio.

    OJO: la URL y las rutas (/movimientos, /asientos) estan sin confirmar contra
    la documentacion de Xubio. Lo que si esta resuelto y verificado es la
    autenticacion: Basic exige base64(id:secretor), no el secreto suelto.
    """

    def __init__(self):
        self.base_url = settings.API_XUBIO_URL.rstrip("/")

    @property
    def _credenciales(self) -> str:
        identificador = (settings.XUBIO_CLIENT_ID or "").strip()
        secreto = (settings.XUBIO_CLIENT_SECRET or "").strip()
        if not identificador or not secreto:
            raise XubioNoConfigurado(
                "Faltan XUBIO_CLIENT_ID / XUBIO_CLIENT_SECRET en el .env. "
                "Sin eso no se puede llamar a la API de Xubio."
            )
        crudo = f"{identificador}:{secreto}".encode("utf-8")
        return base64.b64encode(crudo).decode("ascii")

    @property
    def headers(self) -> dict:
        return {
            "Accept": "application/json",
            "Authorization": f"Basic {self._credenciales}",
        }

    async def obtener_mayor(self, fecha_desde: str, fecha_hasta: str) -> list[dict]:
        """Descarga los movimientos contables de Xubio en un rango de fechas."""
        url = f"{self.base_url}/movimientos"
        params = {"fechaDesde": fecha_desde, "fechaHasta": fecha_hasta}

        async with httpx.AsyncClient(timeout=30.0) as client:
            respuesta = await client.get(url, headers=self.headers, params=params)
            respuesta.raise_for_status()
            return respuesta.json()

    async def enviar_asiento(self, datos_asiento: dict) -> dict:
        """Inyecta un asiento de ajuste directamente en Xubio."""
        url = f"{self.base_url}/asientos"
        async with httpx.AsyncClient(timeout=30.0) as client:
            respuesta = await client.post(
                url, headers=self.headers, json=datos_asiento
            )
            respuesta.raise_for_status()
            return respuesta.json()