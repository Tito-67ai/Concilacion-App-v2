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
  debe: number;
  haber: number;
  /** Signo unificado del mayor: `debe - haber`, al reves que el banco. */
  importe?: number;
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

/** Un par yaconciliado: una fila del banco emparejada con una del mayor. */
export interface ParConciliado {
  fecha: string | null;
  concepto_banco: string;
  concepto_xubio: string;
  debe: number;
  haber: number;
  saldo: number;
  importe: number;
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
  encabezado: EncabezadoConciliacion;
}