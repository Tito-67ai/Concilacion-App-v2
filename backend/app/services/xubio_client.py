import httpx
from app.core.config import settings

class XubioClient:
    def __init__(self):
        self.base_url = settings.API_XUBIO_URL
        # TODO: Adaptar según el método de autenticación exacto de la API de Xubio
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {settings.XUBIO_CLIENT_SECRET}" 
        }

    async def obtener_mayor(self, fecha_desde: str, fecha_hasta: str) -> list[dict]:
        """Descarga los movimientos contables de Xubio en un rango de fechas."""
        url = f"{self.base_url}/movimientos"
        params = {"fechaDesde": fecha_desde, "fechaHasta": fecha_hasta}
        
        async with httpx.AsyncClient() as client:
            # Descomentar en producción:
            # response = await client.get(url, headers=self.headers, params=params)
            # response.raise_for_status()
            # return response.json()
            
            # Datos simulados para que puedas probar el cruce ahora mismo
            return [
                {"fecha": "2026-10-15", "concepto": "Pago a Proveedor", "debe": 0.0, "haber": 50000.0},
                {"fecha": "2026-10-18", "concepto": "Cobro Factura", "debe": 15000.0, "haber": 0.0}
            ]

    async def enviar_asiento(self, datos_asiento: dict) -> dict:
        """Inyecta un asiento de ajuste directamente en Xubio."""
        url = f"{self.base_url}/asientos"
        async with httpx.AsyncClient() as client:
            # response = await client.post(url, headers=self.headers, json=datos_asiento)
            # return response.json()
            return {"exito": True, "mensaje": "Asiento inyectado correctamente"}