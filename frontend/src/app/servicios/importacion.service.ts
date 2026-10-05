import { Injectable, computed, signal } from '@angular/core';

/** Lo que el usuario eligió en /importar-pdf y se lleva a /procesando-pdf. */
export interface SeleccionImportacion {
  cuentaId: string;
  cuentaNombre: string;
  archivo: File;
}

/** Un movimiento de la tabla de verificación, editable en línea. */
export interface MovimientoImportacion {
  id: string;
  fecha: string; // yyyy-MM-dd
  concepto: string;
  /** null cuando el usuario vació el campo o puso algo no numérico. */
  credito: number | null;
  debito: number | null;
}

/** Errores o avisos por movimiento, indexados por campo (para pintarlos en la celda). */
export type ErroresMovimiento = Record<string, string>;

/**
 * Resultado del análisis de una fila:
 * - `errores` bloquean la importación (falta un dato obligatorio).
 * - `avisos` son sospechas de formato: se señalan en amarillo pero el usuario
 *   puede confirmar igual.
 */
export interface AnalisisMovimiento {
  errores: ErroresMovimiento;
  avisos: ErroresMovimiento;
}

@Injectable({ providedIn: 'root' })
export class ImportacionService {
  private readonly _seleccion = signal<SeleccionImportacion | null>(null);
  private readonly _movimientos = signal<MovimientoImportacion[]>([]);
  private readonly _movimientosConfirmados = signal<MovimientoImportacion[]>([]);
  private contadorId = 0;

  /** Selección actual (null si el usuario entró directo a /procesando-pdf). */
  readonly seleccion = this._seleccion.asReadonly();
  readonly tieneSeleccion = computed(() => this._seleccion() !== null);

  /** Atajos para las plantillas: nombre del archivo y cuenta elegida. */
  readonly archivoNombre = computed(
    () => this._seleccion()?.archivo.name ?? 'extracto-bancario.pdf',
  );
  readonly cuentaNombre = computed(() => this._seleccion()?.cuentaNombre ?? '');

  /** Movimientos que se están por confirmar en /verificar-importacion. */
  readonly movimientos = this._movimientos.asReadonly();
  readonly cantidadMovimientos = computed(() => this._movimientos().length);

  /** Los movimientos ya confirmados, listos para mandarse al backend. */
  readonly movimientosConfirmados = this._movimientosConfirmados.asReadonly();

  // --- Totales de las tarjetas de resumen -----------------------------------

  readonly totalCreditos = computed(() =>
    this._movimientos().reduce((total, mov) => total + (mov.credito ?? 0), 0),
  );

  readonly totalDebitos = computed(() =>
    this._movimientos().reduce((total, mov) => total + (mov.debito ?? 0), 0),
  );

  readonly diferencia = computed(() => this.totalCreditos() - this.totalDebitos());

  // --- Validación -----------------------------------------------------------

  /** Solo entran los movimientos con problemas, para no duplicar datos. */
  readonly erroresPorMovimiento = computed(() => this.relevar('errores'));

  /** Sospechas de formato (no bloquean la confirmación). */
  readonly avisosPorMovimiento = computed(() => this.relevar('avisos'));

  readonly hayErrores = computed(() => this.erroresPorMovimiento().size > 0);
  readonly hayAvisos = computed(() => this.avisosPorMovimiento().size > 0);

  /** Sin movimientos no se puede confirmar; con errores tampoco. */
  readonly puedeConfirmar = computed(() => this.cantidadMovimientos() > 0 && !this.hayErrores());

  // --- Selección inicial ----------------------------------------------------

  guardar(seleccion: SeleccionImportacion): void {
    this._seleccion.set(seleccion);
  }

  limpiar(): void {
    this._seleccion.set(null);
  }

  // --- Movimientos ----------------------------------------------------------

  /**
   * Carga los movimientos que devolvió el backend. Acepta objetos sin id
   * porque el extractor no los manda.
   */
  setMovimientos(
    movimientos: Array<Omit<MovimientoImportacion, 'id'> | MovimientoImportacion>,
  ): void {
    this._movimientos.set(movimientos.map((mov) => ({ ...mov, id: this.crearId() })));
  }

  agregarMovimiento(): MovimientoImportacion {
    const nuevo: MovimientoImportacion = {
      id: this.crearId(),
      fecha: '',
      concepto: '',
      credito: null,
      debito: null,
    };

    this._movimientos.update((movimientos) => [nuevo, ...movimientos]);
    return nuevo;
  }

  /**
   * Actualiza una fila en el lugar, sin reemplazarla por un objeto nuevo.
   *
   * Importante para la tabla: el `*ngFor` de /verificar-importacion trackea por
   * identidad, así que si la fila fuera un objeto distinto en cada pulsación
   * Angular destruiría y recrearía el <tr> completo en cada tecla, el input
   * enfocado se perdería y el usuario solo podría escribir un carácter.
   * Devolvemos un array nuevo para que los `computed` se recalculen igual.
   */
  actualizarMovimiento(id: string, cambios: Partial<MovimientoImportacion>): void {
    this._movimientos.update((movimientos) => {
      const fila = movimientos.find((mov) => mov.id === id);

      if (fila) {
        Object.assign(fila, cambios);
      }

      return [...movimientos];
    });
  }

  eliminarMovimiento(id: string): void {
    this._movimientos.update((movimientos) => movimientos.filter((mov) => mov.id !== id));
  }

  limpiarMovimientos(): void {
    this._movimientos.set([]);
  }

  /** Cierra el flujo: lo confirmado pasa a la lista definitivas. */
  confirmarMovimientos(): MovimientoImportacion[] {
    const confirmados = [...this._movimientos()];
    this._movimientosConfirmados.set(confirmados);
    this._movimientos.set([]);
    this.limpiar();

    return confirmados;
  }

  /** "1.234,56" en formato argentino. */
  formatearImporte(valor: number): string {
    return new Intl.NumberFormat('es-AR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number.isFinite(valor) ? valor : 0);
  }

  /** "2026-09-30" -> "30/09/2026". */
  formatearFecha(iso: string): string {
    if (!iso) {
      return '';
    }

    const partes = iso.split('-');
    return partes.length === 3 ? `${partes[2]}/${partes[1]}/${partes[0]}` : iso;
  }

  /** Interpreta lo que escribe el usuario en un input numérico ("1.234,5"). */
  parsearImporte(valor: string): number | null {
    const limpio = valor.trim().replace(/\./g, '').replace(',', '.');
    if (limpio === '' || limpio === '-') {
      return null;
    }

    const numero = Number(limpio);
    return Number.isFinite(numero) ? numero : null;
  }

  /**
   * Analiza una fila y separa lo que bloquea de lo que solo se "-- avisa".
   * Se llama una vez por movimiento desde los `computed` de arriba.
   */
  private analizar(mov: MovimientoImportacion): AnalisisMovimiento {
    const errores: ErroresMovimiento = {};
    const avisos: ErroresMovimiento = {};

    if (!mov.fecha) {
      errores['fecha'] = 'Cargá la fecha';
    }

    if (!mov.concepto.trim()) {
      errores['concepto'] = 'Cargá el concepto';
    }

    if ((mov.credito ?? 0) < 0) {
      errores['credito'] = 'No puede ser negativo';
    }

    if ((mov.debito ?? 0) < 0) {
      errores['debito'] = 'No puede ser negativo';
    }

    if (mov.credito !== null && mov.debito !== null) {
      errores['importe'] = 'No puede tener crédito y débito a la vez';
    } else if (mov.credito === null && mov.debito === null) {
      errores['importe'] = 'Cargá un importe';
    }

    // Sospechas típicas de una lectura de PDF: no impiden confirmar, pero el
    // usuario debería mirarlas.
    this.revisarImporte(mov.credito, 'credito', avisos);
    this.revisarImporte(mov.debito, 'debito', avisos);

    return { errores, avisos };
  }

  private revisarImporte(
    valor: number | null,
    campo: 'credito' | 'debito',
    avisos: ErroresMovimiento,
  ): void {
    if (valor === null) {
      return;
    }

    if (valor === 0) {
      avisos[campo] = 'El importe es cero, revisá el PDF';
      return;
    }

    if (Math.abs(Math.round(valor * 100) - valor * 100) > 1e-6) {
      avisos[campo] = 'Tiene más de 2 decimales';
    }
  }

  /** Arma el mapa de movimientos con problemas de un tipo determinado. */
  private relevar(tipo: 'errores' | 'avisos'): Map<string, ErroresMovimiento> {
    const mapa = new Map<string, ErroresMovimiento>();

    for (const mov of this._movimientos()) {
      const analisis = this.analizar(mov);
      const problemas = analisis[tipo];

      if (Object.keys(problemas).length > 0) {
        mapa.set(mov.id, problemas);
      }
    }

    return mapa;
  }

  private crearId(): string {
    this.contadorId += 1;
    return `mov-${Date.now()}-${this.contadorId}`;
  }
}
