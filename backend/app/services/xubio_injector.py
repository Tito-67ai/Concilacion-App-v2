"""Conector de inyeccion de asientos de ajuste en Xubio.

Por que esta detras de una interfaz
-----------------------------------
La API oficial de Xubio para CREAR asientos todavia no tiene un contrato
confirmado (el comentario de `xubio_client.py` lo dice: las rutas estan "sin
confirmar"). Para no bloquear la pantalla de revision ni arriesgarse a cargar
asientos de verdad, toda la inyeccion pasa por la interfaz `InyectorXubio`.
Hoy la implementacion concreta es un mock que, por defecto, no llama a nadie:
arma el payload que se mandaria y devuelve el resultado simulado (`dry_run`).

Cuando el contrato este confirmado se agrega un `InyectorXubioReal` que use el
mismo `mapear_payload` y el resto de la app no cambia: la pantalla ya aprueba y
el endpoint ya devuelve el resultado por asiento.

El mapeo del asiento a JSON de Xubio vive en `mapear_payload`, para que el dia
que se confirme el contrato haya un solo lugar que tocar.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.core.config import RAIZ_BACKEND, settings

logger = logging.getLogger(__name__)

# La clave del payload puede variar segun el contrato real; se deja en una
# constante para no repetir el literal.
CLAVE_CUENTA = "cuentaCodigo"

RUTA_AUDITORIA = Path(RAIZ_BACKEND) / "logs" / "auditoria_xubio.jsonl"


@dataclass
class ResultadoInyeccion:
    """Resultado de intentar inyectar UN asiento."""

    numero: int
    # "inyectado" | "dry_run" | "error".
    estado: str
    xubio_id: int | None = None
    error: str | None = None
    payload: dict = field(default_factory=dict)


def _codigo_cuenta(linea: Any) -> str:
    codigo = getattr(linea, "cuenta_codigo", "") or getattr(linea, "codigo", "")
    return (codigo or "").strip() or (getattr(linea, "cuenta", "") or "").strip()


def _fecha_iso(valor: Any) -> str | None:
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, str) and valor.strip():
        return valor.strip()[:10]
    return None


def mapear_payload(asiento: Any) -> dict:
    """Mapea un asiento de ajuste a la estructura JSON que pide la API de Xubio.

    `asiento` puede ser un `AsientoAjuste` (dataclass) o un `AsientoRespuesta`
    (pydantic): solo se leen `numero`/`fecha`/`concepto` y las lineas con
    `cuenta`, `debe`, `haber` y `detalle`.

    OJO: la forma exacta del payload tiene que confirmarse contra la
    documentacion real de Xubio antes de usarlo contra produccion.
    """
    concepto = (getattr(asiento, "concepto", "") or "").strip()
    detalle = [
        {
            CLAVE_CUENTA: _codigo_cuenta(linea),
            "debe": round(float(getattr(linea, "debe", 0.0) or 0.0), 2),
            "haber": round(float(getattr(linea, "haber", 0.0) or 0.0), 2),
            "detalle": (getattr(linea, "detalle", "") or "").strip(),
        }
        for linea in getattr(asiento, "lineas", [])
    ]
    return {
        "fecha": _fecha_iso(getattr(asiento, "fecha", None)),
        "descripcion": f"Ajuste conciliacion bancaria - {concepto}".strip(" -"),
        "detalle": detalle,
    }


class InyectorXubio(ABC):
    """Interfaz que desacopla la app del contrato real de Xubio."""

    @abstractmethod
    def inyectar(self, asiento: Any) -> ResultadoInyeccion:
        """Inyecta un asiento y devuelve el resultado."""

    def inyectar_lote(self, asientos: Iterable[Any]) -> list[ResultadoInyeccion]:
        return [self.inyectar(a) for a in asientos]


class InyectorXubioMock(InyectorXubio):
    """Implementacion de prueba: arma el payload y simula la respuesta.

    Con `dry_run=True` (default) no llama a ningun lado: devuelve el payload con
    estado "dry_run". Con `dry_run=False` simula una inyeccion exitosa con un id
    incremental, para probar el flujo completo de la pantalla.
    """

    def __init__(self, dry_run: bool | None = None) -> None:
        self.dry_run = settings.XUBIO_INJECT_DRY_RUN if dry_run is None else dry_run
        self._proximo_id = 1

    def inyectar(self, asiento: Any) -> ResultadoInyeccion:
        numero = int(getattr(asiento, "numero", 0) or 0)
        payload = mapear_payload(asiento)
        if self.dry_run:
            resultado = ResultadoInyeccion(numero, "dry_run", payload=payload)
        else:
            resultado = ResultadoInyeccion(
                numero, "inyectado", xubio_id=self._proximo_id, payload=payload
            )
            self._proximo_id += 1
        _registrar_auditoria(resultado)
        return resultado


def _registrar_auditoria(resultado: ResultadoInyeccion) -> None:
    """Una linea JSONL por intento. Best-effort: si falla, no rompe la corrida."""
    try:
        RUTA_AUDITORIA.parent.mkdir(parents=True, exist_ok=True)
        registro = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "asiento_numero": resultado.numero,
            "resultado": resultado.estado,
            "xubio_id": resultado.xubio_id,
            "error": resultado.error,
        }
        with RUTA_AUDITORIA.open("a", encoding="utf-8") as archivo:
            archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - la auditoria nunca rompe la inyeccion
        logger.exception("No se pudo registrar la auditoria de la inyeccion")


def obtener_inyector() -> InyectorXubio:
    """Devuelve la implementacion a usar.

    Hoy siempre el mock. El dia que exista el cliente real, esta funcion es el
    unico lugar que cambia.
    """
    return InyectorXubioMock()
