/**
 * Las formas de la conciliacion, tipadas.
 *
 * Todo esto venia como `any` porque cada pantalla fue creciendo por partes y
 * nadie se quejo. El problema aparece cuando hay que armar el payload del
 * export: sin tipos, mandar `conciliados[].fecha` que puede ser un string ISO
 * en un automatico y no existe en un par manual se descubre cuando el backend
 * responde 422 y el archivo no baja.
 *
 * Las tres bandejas son exactamente lo que devuelve POST /xubio/cruzar-datos
 * (conciliador.py:167-181) mas lo que agrega la conciliacion manual.
 */

/** Una fila de la bandeja del banco, tal como la manda el cruce. */
export interface MovimientoBanco {
  origen?: string;
  fecha: string | null;
  concepto: string;
  referencia?: string | null;
  debe: number;
  haber: number;
  saldo: number;
  /** Signo unificado del lado del banco: `haber - debe`. */
  importe?: number;
  categoria?: string | null;
}

/**
 * Una fila de la bandeja de Xubio. No trae `saldo` ni `categoria`: el cruce
 * con el mayor no las manda, y el papel de trabajo las deja vacias en vez de
 * poner ceros que parecen un dato real.
 */
export interface MovimientoMayor {
  origen?: string;
  fecha: string | null;
  concepto: string;
  /**
   * Número de comprobante del mayor (FCA-0001-00000001, etc.) cuando el export
   * del contable trae la columna. La bandeja derecha lo muestra en su columna;
   * si no vino, '—'.
   */
  comprobante?: string | null;
  debe: number;
  haber: number;
  /** Signo unificado del mayor: `debe - haber`, al reves que el banco. */
  importe?: number;
  // Campos adicionales del webreport de Xubio
  documento?: string | null;
  cuenta?: string | null;
  organizacion?: string | null;
  descripcion?: string | null;
}

/** Lo que devuelve POST /conciliacion/mayor. */
export interface RespuestaMayor {
  exito: boolean;
  cantidad_movimientos: number;
  /**
   * 'contable' si el archivo era un Libro Mayor (Debe = entrada) o 'cuenta' si
   * era un extracto de Movimientos de CC (debito = salida). La pantalla lo
   * muestra para que nadie confunda una convencion con la otra.
   */
  convencion: string;
  datos: MovimientoMayor[];
}

/**
 * Lo que devuelve GET /xubio/libro-mayor: el mayor del período pedido, ya
 * parseado en el backend desde la grilla del webreport. `datos` (el JSON
 * crudo) no interesa acá: lo que se muestra es `movimientos`.
 */
export interface RespuestaMayorXubio {
  exito: boolean;
  desde: string | null;
  hasta: string | null;
  cantidad: number;
  convencion: string;
  movimientos: MovimientoMayor[];
}

/** Un par yaconciliado: una fila del banco emparejada con una del mayor. */
export interface ParConciliado {
  fecha: string | null;
  concepto_banco: string;
  concepto_xubio: string;
  debe: number;
  haber: number;
  saldo: number;
  /**
   * Opcional porque el cruce no siempre lo manda (el par manual lo arma desde
   * el banco): si falta, el exportador lo recalcula desde debe/haber.
   */
  importe?: number;
  /**
   * El cruce guarda estos dos del lado de Xubio, que es el que muestra la
   * bandeja derecha: el comprobante del mayor y su importe unificado
   * (`debe - haber`, al reves que el `importe` del banco que guarda el par).
   */
  comprobante_xubio?: string | null;
  importe_xubio?: number;
  categoria?: string | null;
  cuadra?: boolean;
  /** Solo lo mandan los pares armados a mano. El cruce automatico no lo trae. */
  manual?: boolean;
  /** Diferencia de importe, solo en los pares manuales. */
  diferencia?: number;
}

/** Los cuatro campos del membrete de FO 02-03. */
export interface EncabezadoConciliacion {
  empresa: string;
  banco: string;
  /**
   * Va en snake_case como el resto del payload (`concepto_banco`,
   * `pendientes_xubio`): el schema del backend es `numero_cuenta` y Pydantic
   * ignora las claves que no reconoce, asi que con `numeroCuenta` la cuenta se
   * perdia en el viaje y el papel de trabajo salia sin ese campo.
   */
  numero_cuenta: string;
  /** `YYYY-MM`, porque la celda del periodo tiene formato `mmmm yyyy`. */
  periodo: string | null;
}

/** Lo que viaja a POST /exportar/conciliacion. */
export interface SolicitudExportacion {
  conciliados: ParConciliado[];
  pendientes_banco: MovimientoBanco[];
  pendientes_xubio: MovimientoMayor[];
  /**
   * El mayor y el extracto completos, para armar la Tabla 1 y la pestana de
   * "Movimientos Bancarios" del papel de trabajo. Las bandejas de arriba solo
   * traen lo que quedo sin cruzar: el spec pide volcar TODO, conciliado o no.
   */
  movimientos_mayor: MovimientoMayor[];
  movimientos_banco: MovimientoBanco[];
  encabezado: EncabezadoConciliacion;
}

/** Un cliente/afiliado de Xubio, tal como lo devuelve GET /xubio/afiliados. */
export interface Afiliado {
  id: number;
  organizacionId: number;
  organizacionNombre: string;
  cuit: string | null;
  categoriaFiscal: string | null;
  activo: number;
  esProveedor: number;
}

/**
 * Una entrada de /xubio/cruzar-afiliados o /xubio/clasificar-mayor.
 *
 * Llega una por movimiento, en el mismo orden, para poder superponerla a la
 * tabla sin buscar: `datos[i]` es el afiliado de `movimientos[i]`.
 */
export interface CruceAfiliadoMovimiento {
  indice: number;
  afiliado: Afiliado | null;
  metodo: string | null;
}

/** Una fila de la tabla de afiliados: el afiliado y cuantos movimientos son suyos. */
export interface AfiliadoConConciliaciones {
  afiliado: Afiliado;
  movimientos: number;
}

/** Lo que devuelve GET /extractos/bancos. */
export interface RespuestaBancos {
  bancos: string[];
  formatos: string[];
}

/** Lo que devuelve GET /xubio/afiliados. */
export interface RespuestaAfiliados {
  exito: boolean;
  cantidad: number;
  datos: Afiliado[];
}

/** Lo que devuelven /xubio/cruzar-afiliados y /xubio/clasificar-mayor. */
export interface RespuestaCruceAfiliados {
  exito: boolean;
  resumen: Record<string, unknown>;
  datos: CruceAfiliadoMovimiento[];
}

/** Las tres bandejas que devuelve el cruce. */
export interface TablasCruce {
  conciliados: ParConciliado[];
  pendientes_banco: MovimientoBanco[];
  pendientes_xubio: MovimientoMayor[];
}

/** Lo que devuelven POST /conciliacion/cruzar y POST /xubio/cruzar-datos. */
export interface RespuestaCruce {
  exito: boolean;
  resumen: Record<string, unknown>;
  tablas: TablasCruce;
}

/** Lo que devuelve POST /extractos/procesar. */
export interface RespuestaExtraccion {
  exito: boolean;
  banco: string;
  /** 'pdf' o 'tabla'. Opcional: un backend viejo no lo manda. */
  origen?: string | null;
  /** Que extractor leyo el archivo (queda 'GENERICO' si entro el de rescate). */
  motor?: string | null;
  cantidad_movimientos: number;
  datos: MovimientoBanco[];
}

// ---------------------------------------------------------------------------
// Conciliacion avanzada FO 02-03 (POST /conciliacion/cruzar-avanzado)
//
// El cruce simple devuelve las tres bandejas para emparejar. Este ademas
// clasifica lo que quedo sin par:
//
//   - ajustes contables: gastos que el banco cobro y la contabilidad todavia
//     no registro (comisiones, impuestos, retenciones). Se registran y cuadran.
//   - partidas pendientes: en transito, cuando el banco todavia no debito un
//     pago del mayor (origen 'pendiente_mayor'), o a investigar, cuando el
//     banco muestra un movimiento que no es gasto y no tiene par
//     (origen 'pendiente_banco').
//
// Con eso arma el cuadro de control que explica la diferencia banco/empresa.
// ---------------------------------------------------------------------------

/** Los totales del cuadro de control: la conciliacion en unos pocos numeros. */
export interface CuadroControl {
  ingresos: {
    empresa_total: number;
    banco_total: number;
    conciliados: number;
    diferencia_neta: number;
  };
  egresos: {
    empresa_total: number;
    banco_total: number;
    conciliados: number;
    diferencia_neta: number;
  };
  ajustes_contables: { total: number; cantidad: number };
  partidas_pendientes: {
    banco_cantidad: number;
    mayor_cantidad: number;
    total_mayor: number;
  };
  conciliados: {
    cantidad: number;
    total_ingresos: number;
    total_egresos: number;
  };
}

/** Un gasto del banco sin asiento contable: hay que registrarlo en Xubio. */
export interface AjusteContable {
  origen?: string;
  fecha: string | null;
  concepto: string;
  referencia?: string | null;
  debito: number;
  credito: number;
  importe: number;
  saldo: number;
  categoria?: string | null;
  cuit?: string | null;
  cbu?: string | null;
  nombre_tercero?: string | null;
}

/**
 * Un movimiento sin par. `origen` distingue el lado: 'pendiente_mayor' es del
 * Libro Mayor (tipico cheque emitido que el banco todavia no debito) y
 * 'pendiente_banco' es del extracto (a investigar). Los campos del otro lado
 * quedan vacios segun de donde venga.
 */
export interface PartidaPendiente {
  origen: string;
  fecha: string | null;
  concepto: string;
  referencia?: string | null;
  comprobante?: string | null;
  debe?: number;
  haber?: number;
  importe: number;
  saldo: number;
  categoria?: string | null;
  documento?: string | null;
  cuenta?: string | null;
  organizacion?: string | null;
  descripcion?: string | null;
  cuit?: string | null;
  cbu?: string | null;
  nombre_tercero?: string | null;
}

/** Una fila del cuadro de gastos bancarios (mismo concepto sumado). */
export interface GastoBancarioResumen {
  concepto: string;
  /** Total de créditos del concepto (positivo). */
  suma_credito: number;
  /** Total de débitos del concepto (negativo: es una salida). */
  suma_debito: number;
  /** Valor absoluto, solo para ordenar. */
  suma: number;
  cantidad: number;
  porcentaje: number;
  porcentaje_acumulado: number;
}

export interface EstadisticasConciliacion {
  total_movimientos_banco: number;
  total_movimientos_mayor: number;
  conciliados: number;
  ajustes_contables: number;
  pendientes_banco: number;
  pendientes_mayor: number;
  porcentaje_conciliado: number;
}

/**
 * Valores del acta de conciliación (puente mayor -> banco). Los egresos y las
 * transferencias ya vienen en negativo, como se muestran en el informe.
 */
export interface ActaConciliacion {
  saldo_libro_mayor: number;
  ingresos_no_registrados: number;
  egresos_no_registrados: number;
  cheques_no_cobrados: number;
  transferencias_transito: number;
  saldo_banco: number;
  diferencia: number;
}

/** Reporte listo para copiar: cuadro de gastos y acta, ambos en Markdown. */
export interface ReporteMarkdown {
  cuadro_gastos: string;
  acta_conciliacion: string;
  acta: ActaConciliacion;
}

export interface RespuestaConciliacionAvanzada {
  exito: boolean;
  conciliados: Record<string, unknown>[];
  ajustes_contables: AjusteContable[];
  partidas_pendientes: PartidaPendiente[];
  cuadro_control: CuadroControl;
  tabla_dinamica_gastos: GastoBancarioResumen[];
  estadisticas: EstadisticasConciliacion;
  reporte_markdown?: ReporteMarkdown;
}

/** Un renglón de un asiento de ajuste: una cuenta con su Debe o su Haber. */
export interface LineaAsiento {
  cuenta: string;
  detalle: string;
  debe: number;
  haber: number;
}

/** Un asiento de ajuste de partida doble de una partida sin coincidencia. */
export interface AsientoAjuste {
  numero: number;
  fecha: string | null;
  origen: 'banco' | 'mayor' | string;
  concepto: string;
  referencia: string;
  debe: number;
  haber: number;
  lineas: LineaAsiento[];
}

/** Respuesta de POST /exportar/asientos: la vista previa de los asientos. */
export interface RespuestaAsientos {
  asientos: AsientoAjuste[];
  total_debe: number;
  total_haber: number;
}