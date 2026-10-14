"""
Conciliación Bancaria Avanzada - Algoritmo completo según modelo FO 02-03.

Flujo:
1. MATCHING EXACTO: Debe Mayor ↔ Crédito Banco (centavo a centavo) + fecha ±3 días
                  Haber Mayor ↔ Débito Banco (valor absoluto) + fecha ±3 días
2. CLASIFICACIÓN:
   - CONCILIADOS: matching exacto por importe y fecha
   - AJUSTES CONTABLES: solo en banco (gastos bancarios, comisiones, impuestos, retenciones)
   - PARTIDAS PENDIENTES: solo en mayor (pagos/cheques emitidos no debitados)
3. ENRIQUECIMIENTO: busca CUIT/CBU/Nombre en extracto crudo para movimientos no identificados
4. CUADRO DE CONTROL: totales ingresos/egresos, diferencias netas, tabla dinámica gastos bancarios
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from typing import Any, Optional

from app.models.schemas import MovimientoBancario
from app.services.clasificacion import clasificar, es_gasto_bancario
from app.services.reporte_markdown import generar_reporte

logger = logging.getLogger(__name__)

TOLERANCIA_DIAS = 3
CENTAVO = Decimal("0.01")


def _dec(valor: Any) -> Decimal:
    """Convierte a Decimal con 2 decimales, redondeo bancario."""
    try:
        return Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def _a_fecha(valor: Any) -> Optional[date]:
    """Convierte a date aceptando date, datetime, string ISO o DD/MM/YYYY."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, str) and valor.strip():
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(valor.strip()[:10], fmt).date()
            except ValueError:
                continue
    return None


def _distancia_dias(f1: Optional[date], f2: Optional[date]) -> Optional[int]:
    if f1 is None or f2 is None:
        return None
    return abs((f1 - f2).days)


@dataclass
class MovimientoNormalizado:
    """Movimiento con importe unificado y metadata para matching."""
    origen: str  # "banco" | "mayor"
    idx_original: int
    fecha: Optional[date]
    concepto: str
    referencia: Optional[str]
    debe: Decimal
    haber: Decimal
    saldo: Decimal
    importe_unificado: Decimal  # banco: haber-debe (entrada+), mayor: debe-haber (entrada+)
    categoria: str
    # Enriquecimiento desde extracto crudo
    cuit: Optional[str] = None
    cbu: Optional[str] = None
    nombre_tercero: Optional[str] = None
    cod_concepto: Optional[str] = None
    canal: Optional[str] = None
    banco_emisor: Optional[str] = None


@dataclass
class ResultadoConciliacion:
    """Resultado completo de la conciliación."""
    conciliados: list[dict] = field(default_factory=list)
    ajustes_contables: list[dict] = field(default_factory=list)      # Solo en banco
    partidas_pendientes: list[dict] = field(default_factory=list)    # Solo en mayor
    cuadro_control: dict = field(default_factory=dict)
    tabla_dinamica_gastos: list[dict] = field(default_factory=list)
    estadisticas: dict = field(default_factory=dict)
    # Reporte ya formateado para pegar en el informe: el cuadro de gastos en
    # Markdown y el acta de conciliación (ver reporte_markdown.py).
    reporte_markdown: dict = field(default_factory=dict)


def _importe_banco(mov: MovimientoBancario) -> Decimal:
    """Importe banco: entrada positiva = haber - debe."""
    return _dec(mov.haber) - _dec(mov.debe)


def _importe_mayor(mov: dict) -> Decimal:
    """Importe mayor: entrada positiva = debe - haber (convención contable)."""
    return _dec(mov.get("debe")) - _dec(mov.get("haber"))


def _normalizar_banco(mov: MovimientoBancario, idx: int) -> MovimientoNormalizado:
    imp = _importe_banco(mov)
    cat = clasificar(mov.concepto)
    return MovimientoNormalizado(
        origen="banco",
        idx_original=idx,
        fecha=_a_fecha(mov.fecha),
        concepto=(mov.concepto or "").strip(),
        referencia=(mov.referencia or "").strip() or None,
        debe=_dec(mov.debe),
        haber=_dec(mov.haber),
        saldo=_dec(mov.saldo),
        importe_unificado=imp,
        categoria=cat,
    )


def _normalizar_mayor(mov: dict, idx: int) -> MovimientoNormalizado:
    imp = _importe_mayor(mov)
    return MovimientoNormalizado(
        origen="mayor",
        idx_original=idx,
        fecha=_a_fecha(mov.get("fecha")),
        concepto=(mov.get("concepto") or "").strip(),
        referencia=(mov.get("comprobante") or mov.get("referencia") or "").strip() or None,
        debe=_dec(mov.get("debe")),
        haber=_dec(mov.get("haber")),
        saldo=_dec(mov.get("saldo")),
        importe_unificado=imp,
        categoria="operativo",  # El mayor no trae categoría
    )


def _enriquecer_desde_extracto_crudo(
    movimientos: list[MovimientoNormalizado],
    extracto_crudo: list[dict | Any],
) -> None:
    """Enriquece movimientos con CUIT/CBU/Nombre/Concepto del extracto crudo (17 cols)."""
    # Crear índice por (fecha, concepto, importe) para búsqueda rápida
    idx = {}
    for row in extracto_crudo:
        # Soporte tanto dict como Pydantic model
        if hasattr(row, "model_dump"):
            row = row.model_dump(by_alias=True)
        f = _a_fecha(row.get("Fecha contable"))
        c = (row.get("Concepto") or "").strip()
        d = _dec(row.get("Debito en $"))
        h = _dec(row.get("Credito en $"))
        imp = h - d  # mismo signo que banco
        key = (f, c, imp)
        if key not in idx:
            idx[key] = row

    for mov in movimientos:
        if mov.origen != "banco":
            continue
        key = (mov.fecha, mov.concepto, mov.importe_unificado)
        row = idx.get(key)
        if row:
            if hasattr(row, "model_dump"):
                row = row.model_dump(by_alias=True)
            mov.cuit = (row.get("Nro doc") or "").strip() or None
            mov.cbu = (row.get("CBU/Alias") or "").strip() or None
            mov.nombre_tercero = (row.get("Nombre") or "").strip() or None
            mov.cod_concepto = str(row.get("Cod de Concepto") or "").strip() or None
            mov.canal = (row.get("Canal") or "").strip() or None
            mov.banco_emisor = (row.get("Banco") or "").strip() or None


def _agrupar_por_importe(
    movimientos: list[MovimientoNormalizado],
) -> dict[Decimal, list[int]]:
    """Índice: importe -> lista de índices en la lista original."""
    idx = defaultdict(list)
    for i, m in enumerate(movimientos):
        idx[m.importe_unificado].append(i)
    return idx


def _matching_exacto(
    banco: list[MovimientoNormalizado],
    mayor: list[MovimientoNormalizado],
    tolerancia_dias: int = TOLERANCIA_DIAS,
) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    """
    Matching 1-a-1 por importe exacto (centavo) y fecha ±tolerancia.

    Returns:
        pares: lista de (idx_banco, idx_mayor)
        usados_banco: set de índices de banco ya emparejados
        usados_mayor: set de índices de mayor ya emparejados
    """
    idx_banco_por_importe = _agrupar_por_importe(banco)
    usados_banco = set()
    usados_mayor = set()
    pares = []

    for idx_m, mov_m in enumerate(mayor):
        if idx_m in usados_mayor:
            continue
        candidatos = [
            i for i in idx_banco_por_importe.get(mov_m.importe_unificado, [])
            if i not in usados_banco
        ]
        if not candidatos:
            continue

        # Prioridad: 1) mismo día, 2) dentro de tolerancia
        def dist(i):
            return _distancia_dias(banco[i].fecha, mov_m.fecha)

        con_fecha = [(dist(i), i) for i in candidatos]
        con_fecha = [(d, i) for d, i in con_fecha if d is not None]
        elegido = None

        if con_fecha:
            con_fecha.sort()
            if con_fecha[0][0] == 0:
                elegido = con_fecha[0][1]
            elif con_fecha[0][0] <= tolerancia_dias:
                elegido = con_fecha[0][1]

        if elegido is not None:
            pares.append((elegido, idx_m))
            usados_banco.add(elegido)
            usados_mayor.add(idx_m)

    return pares, usados_banco, usados_mayor


def _clasificar_ajustes_y_pendientes(
    banco: list[MovimientoNormalizado],
    mayor: list[MovimientoNormalizado],
    usados_banco: set[int],
    usados_mayor: set[int],
) -> tuple[list[dict], list[dict]]:
    """
    Clasifica los no emparejados:
    - AJUSTES CONTABLES: movimientos de banco sin par, que son gastos bancarios
      (comisiones, impuestos, retenciones, intereses, sellados, percepciones)
    - PARTIDAS PENDIENTES: movimientos de mayor sin par (pagos/cheques no debitados)
      + movimientos de banco que NO son gastos bancarios (ej. transferencias no identificadas)
    """
    ajustes = []
    pendientes = []

    # Ajustes contables: solo banco, gasto bancario, no emparejado
    for i, mov in enumerate(banco):
        if i in usados_banco:
            continue
        if es_gasto_bancario(mov.concepto):
            ajustes.append(_mov_a_dict_ajuste(mov))
        else:
            # Movimiento de banco no gasto y sin par -> podría ser transferencia no identificada
            # Lo tratamos como "pendiente de identificación" en el banco
            pendientes.append(_mov_a_dict_pendiente_banco(mov))

    # Partidas pendientes del mayor: no emparejadas
    for i, mov in enumerate(mayor):
        if i in usados_mayor:
            continue
        pendientes.append(_mov_a_dict_pendiente_mayor(mov))

    return ajustes, pendientes


def _mov_a_dict_ajuste(mov: MovimientoNormalizado) -> dict:
    return {
        "origen": "ajuste_contable",
        "fecha": mov.fecha.isoformat() if mov.fecha else None,
        "concepto": mov.concepto,
        "referencia": mov.referencia,
        "debito": float(mov.debe),
        "credito": float(mov.haber),
        "importe": float(mov.importe_unificado),  # negativo = egreso
        "saldo": float(mov.saldo),
        "categoria": mov.categoria,
        "cuit": mov.cuit,
        "cbu": mov.cbu,
        "nombre_tercero": mov.nombre_tercero,
        "cod_concepto": mov.cod_concepto,
        "canal": mov.canal,
        "banco_emisor": mov.banco_emisor,
    }


def _mov_a_dict_pendiente_banco(mov: MovimientoNormalizado) -> dict:
    return {
        "origen": "pendiente_banco",
        "fecha": mov.fecha.isoformat() if mov.fecha else None,
        "concepto": mov.concepto,
        "referencia": mov.referencia,
        "debito": float(mov.debe),
        "credito": float(mov.haber),
        "importe": float(mov.importe_unificado),
        "saldo": float(mov.saldo),
        "categoria": mov.categoria,
        "cuit": mov.cuit,
        "cbu": mov.cbu,
        "nombre_tercero": mov.nombre_tercero,
        "cod_concepto": mov.cod_concepto,
        "canal": mov.canal,
        "banco_emisor": mov.banco_emisor,
    }


def _mov_a_dict_pendiente_mayor(mov: MovimientoNormalizado) -> dict:
    return {
        "origen": "pendiente_mayor",
        "fecha": mov.fecha.isoformat() if mov.fecha else None,
        "concepto": mov.concepto,
        "referencia": mov.referencia,
        "comprobante": mov.referencia,  # en mayor el comprobante es la referencia
        "debe": float(mov.debe),
        "haber": float(mov.haber),
        "importe": float(mov.importe_unificado),
        "saldo": float(mov.saldo),
        "categoria": mov.categoria,
        "documento": mov.referencia,
        "cuenta": None,
        "organizacion": None,
        "descripcion": mov.concepto,
    }


def _mov_a_dict_conciliado(
    mov_b: MovimientoNormalizado,
    mov_m: MovimientoNormalizado,
) -> dict:
    return {
        "fecha": mov_b.fecha.isoformat() if mov_b.fecha else None,
        "concepto_banco": mov_b.concepto,
        "concepto_mayor": mov_m.concepto,
        "referencia_banco": mov_b.referencia,
        "comprobante_mayor": mov_m.referencia,
        "importe_banco": float(mov_b.importe_unificado),
        "importe_mayor": float(mov_m.importe_unificado),
        "debe_banco": float(mov_b.debe),
        "haber_banco": float(mov_b.haber),
        "debe_mayor": float(mov_m.debe),
        "haber_mayor": float(mov_m.haber),
        "saldo_banco": float(mov_b.saldo),
        "saldo_mayor": float(mov_m.saldo),
        "categoria": mov_b.categoria,
        "cuadra": True,
        "diferencia_dias": _distancia_dias(mov_b.fecha, mov_m.fecha) or 0,
        "cuit": mov_b.cuit,
        "cbu": mov_b.cbu,
        "nombre_tercero": mov_b.nombre_tercero,
    }


def _cuadro_control(
    banco: list[MovimientoNormalizado],
    mayor: list[MovimientoNormalizado],
    conciliados: list[tuple[int, int]],
    ajustes: list[dict],
    pendientes_banco: list[dict],
    pendientes_mayor: list[dict],
) -> dict:
    """Calcula el cuadro de control FO 02-03."""

    # Totales banco
    total_credito_banco = sum(m.haber for m in banco)
    total_debito_banco = sum(m.debe for m in banco)

    # Totales mayor
    total_debe_mayor = sum(m.debe for m in mayor)
    total_haber_mayor = sum(m.haber for m in mayor)

    # Conciliados
    cred_conc = sum(banco[i].haber for i, _ in conciliados)
    deb_conc = sum(banco[i].debe for i, _ in conciliados)
    debe_conc_m = sum(mayor[j].debe for _, j in conciliados)
    hab_conc_m = sum(mayor[j].haber for _, j in conciliados)

    return {
        "ingresos": {
            "empresa_total": float(total_debe_mayor),
            "banco_total": float(total_credito_banco),
            "conciliados": float(cred_conc),
            "diferencia_neta": float(total_debe_mayor - total_credito_banco),
        },
        "egresos": {
            "empresa_total": float(total_haber_mayor),
            "banco_total": float(total_debito_banco),
            "conciliados": float(deb_conc),
            "diferencia_neta": float(total_haber_mayor - total_debito_banco),
        },
        "ajustes_contables": {
            "total": float(sum(Decimal(str(a["importe"])) for a in ajustes)),
            "cantidad": len(ajustes),
        },
        "partidas_pendientes": {
            "banco_cantidad": len([p for p in pendientes_banco if p["origen"] == "pendiente_banco"]),
            "mayor_cantidad": len(pendientes_mayor),
            "total_mayor": float(sum(Decimal(str(p["importe"])) for p in pendientes_mayor)),
        },
        "conciliados": {
            "cantidad": len(conciliados),
            "total_ingresos": float(cred_conc),
            "total_egresos": float(deb_conc),
        },
    }


def _tabla_dinamica_gastos(ajustes: list[dict]) -> list[dict]:
    """Cuadro de gastos bancarios: suma de Crédito y de Débito por concepto.

    Es la tabla dinámica que pide el analista: agrupa por el concepto original
    del extracto (normalizado) y no por categorías hardcodeadas, así el cuadro
    refleja exactamente lo que dice el banco: "COM MANT CT", "IVA",
    "IMP S/DEB CT", "ING BRUTOS PERCEP", etc.

    Por cada concepto devuelve:
      - suma_credito: total de créditos (positivo).
      - suma_debito:  total de débitos (negativo: es una salida de dinero).
      - suma:         total en valor absoluto; solo ordena y mantiene la forma
                      anterior de la respuesta.
    """
    creditos: dict[str, Decimal] = defaultdict(Decimal)
    debitos: dict[str, Decimal] = defaultdict(Decimal)
    conteos: dict[str, int] = defaultdict(int)

    for a in ajustes:
        concepto_original = (a.get("concepto", "") or "").strip()
        # Normalizar: quitar espacios múltiples y pasar a mayúsculas.
        concepto_norm = " ".join(concepto_original.upper().split())
        if not concepto_norm:
            concepto_norm = "SIN CONCEPTO"

        # `importe` viene en convención banco: positivo = crédito (entrada),
        # negativo = débito (salida). Si el movimiento trae los campos
        # separados se usan esos; si no, se deduce del importe.
        debito = _dec(a.get("debito"))
        credito = _dec(a.get("credito"))
        if not debito and not credito:
            importe = _dec(a.get("importe"))
            if importe < 0:
                debito = -importe
            elif importe > 0:
                credito = importe

        creditos[concepto_norm] += credito
        debitos[concepto_norm] += debito
        conteos[concepto_norm] += 1

    # Un concepto puede tener solo crédito, solo débito o ambos. Se ordena por
    # magnitud (mayor primero), como la tabla del banco.
    conceptos = set(creditos) | set(debitos)
    absolutos = {c: creditos[c] + debitos[c] for c in conceptos}
    items = sorted(conceptos, key=lambda c: absolutos[c], reverse=True)

    total = sum(absolutos.values())
    acum = Decimal("0")
    resultado = []
    for concepto in items:
        acum += absolutos[concepto]
        resultado.append({
            "concepto": concepto,
            "suma_credito": float(creditos[concepto].quantize(CENTAVO)),
            "suma_debito": float((-debitos[concepto]).quantize(CENTAVO)),
            "suma": float(absolutos[concepto].quantize(CENTAVO)),
            "cantidad": conteos[concepto],
            "porcentaje": float((absolutos[concepto] / total * 100).quantize(CENTAVO)) if total else 0,
            "porcentaje_acumulado": float((acum / total * 100).quantize(CENTAVO)) if total else 0,
        })
    return resultado


def _estadisticas(
    banco: list[MovimientoNormalizado],
    mayor: list[MovimientoNormalizado],
    pares: list[tuple[int, int]],
    ajustes: list[dict],
    pendientes: list[dict],
) -> dict:
    return {
        "total_movimientos_banco": len(banco),
        "total_movimientos_mayor": len(mayor),
        "conciliados": len(pares),
        "ajustes_contables": len(ajustes),
        "pendientes_banco": len([p for p in pendientes if p.get("origen") == "pendiente_banco"]),
        "pendientes_mayor": len([p for p in pendientes if p.get("origen") == "pendiente_mayor"]),
        "porcentaje_conciliado": round(len(pares) / max(len(banco), 1) * 100, 2),
    }


def conciliar_avanzado(
    movimientos_banco: list[MovimientoBancario],
    movimientos_mayor: list[dict],
    extracto_crudo: Optional[list[dict]] = None,
    tolerancia_dias: int = TOLERANCIA_DIAS,
) -> ResultadoConciliacion:
    """
    Punto de entrada principal: conciliación avanzada FO 02-03.

    Args:
        movimientos_banco: lista de MovimientoBancario (extraídos del PDF)
        movimientos_mayor: lista de dicts (desde archivo o webreport)
        extracto_crudo: lista de dicts con 17 columnas (opcional, para enriquecer)
        tolerancia_dias: ventana de fecha para matching (± días)

    Returns:
        ResultadoConciliacion con todas las bandejas y cuadros de control
    """
    logger.info(
        "Iniciando conciliación avanzada: %d banco, %d mayor",
        len(movimientos_banco), len(movimientos_mayor)
    )

    # 1. Normalizar
    banco = [_normalizar_banco(m, i) for i, m in enumerate(movimientos_banco)]
    mayor = [_normalizar_mayor(m, i) for i, m in enumerate(movimientos_mayor)]

    # 2. Enriquecer con extracto crudo
    if extracto_crudo:
        _enriquecer_desde_extracto_crudo(banco, extracto_crudo)

    # 3. Matching exacto
    pares, usados_banco, usados_mayor = _matching_exacto(banco, mayor, tolerancia_dias)

    # 4. Clasificar no emparejados
    ajustes, pendientes = _clasificar_ajustes_y_pendientes(
        banco, mayor, usados_banco, usados_mayor
    )

    # Separar pendientes por origen
    pendientes_banco = [p for p in pendientes if p.get("origen") == "pendiente_banco"]
    pendientes_mayor = [p for p in pendientes if p.get("origen") == "pendiente_mayor"]

    # 5. Construir conciliados
    conciliados = [
        _mov_a_dict_conciliado(banco[i], mayor[j])
        for i, j in pares
    ]

    # 6. Cuadro de control
    control = _cuadro_control(banco, mayor, pares, ajustes, pendientes_banco, pendientes_mayor)

    # 7. Tabla dinámica de gastos
    tabla_gastos = _tabla_dinamica_gastos(ajustes)

    # 8. Reporte Markdown (cuadro de gastos + acta de conciliación)
    reporte = generar_reporte(
        total_debe_mayor=sum((m.debe for m in mayor), Decimal("0.00")),
        total_haber_mayor=sum((m.haber for m in mayor), Decimal("0.00")),
        total_credito_banco=sum((m.haber for m in banco), Decimal("0.00")),
        total_debito_banco=sum((m.debe for m in banco), Decimal("0.00")),
        pendientes_banco=pendientes_banco,
        pendientes_mayor=pendientes_mayor,
        tabla_gastos=tabla_gastos,
    )

    # 9. Estadísticas
    stats = _estadisticas(banco, mayor, pares, ajustes, pendientes)

    logger.info(
        "Conciliación completada: %d conciliados, %d ajustes, %d pendientes banco, %d pendientes mayor",
        len(conciliados), len(ajustes), len([p for p in pendientes if p.get("origen") == "pendiente_banco"]), len([p for p in pendientes if p.get("origen") == "pendiente_mayor"])
    )

    return ResultadoConciliacion(
        conciliados=conciliados,
        ajustes_contables=ajustes,
        partidas_pendientes=pendientes_banco + pendientes_mayor,
        cuadro_control=control,
        tabla_dinamica_gastos=tabla_gastos,
        estadisticas=stats,
        reporte_markdown=reporte,
    )