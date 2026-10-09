import { Injectable, computed, signal } from '@angular/core';

/** Lo que el usuario elige en /importar-pdf y se lleva a /procesando-pdf. */
export interface SeleccionImportacion {
  cuentaId: string;
  cuentaNombre: string;
  banco: string;
  archivo: File;
}

/** Un movimiento del extracto, tal como lo devuelve POST /extractos/procesar. */
export interface MovimientoImportado {
  id: string;
  fecha: string;
  concepto: string;
  referencia: string | null;
  debe: number;
  haber: number;
  saldo: number;
  categoria: string | null;
}

/**
 * Estado compartido del flujo de importacion.
 *
 * Antes el importador vivia entero dentro de conciliacion y no hacia falta
 * ningun servicio. Ahora el flujo son tres pantallas con rutas propias, asi que
 * los datos que se eligen en una tienen que llegar a la siguiente: Angular
 * destruye el componente al navegar, asi que el estado no puede quedar en el
 * componente.
 *
 * Ojo con el nombre: esto guarda una seleccion EN MEMORIA, no una importacion
 * guardada. Si recargas la pantalla /procesando-pdf a mano se pierde, y por eso
 * esa pantalla manda al usuario de vuelta a /importar-pdf cuando no encuentra
 * nada. No hay persistencia todavia porque tampoco la hay del cruce automatico.
 */
@Injectable({ providedIn: 'root' })
export class ImportacionService {
  private readonly _seleccion = signal<SeleccionImportacion | null>(null);
  private readonly _movimientos = signal<MovimientoImportado[]>([]);

  /**
   * Copia de los movimientos tal como los devolvio el extractor. Es la foto del
   * PDF: el deshacer vuelve a estos valores y no a la ultima edicion, porque lo
   * que el usuario quiere salvar cuando se equivoca es el estado de origen.
   */
  private readonly _originales = signal<MovimientoImportado[]>([]);

  readonly seleccion = this._seleccion.asReadonly();

  /** Nombre del archivo elegido, para el titulo de /procesando-pdf. */
  readonly archivoNombre = computed(() => this._seleccion()?.archivo.name ?? '');
  readonly cuentaNombre = computed(() => this._seleccion()?.cuentaNombre ?? '');
  readonly banco = computed(() => this._seleccion()?.banco ?? '');

  readonly movimientos = this._movimientos.asReadonly();
  readonly cantidadMovimientos = computed(() => this._movimientos().length);

  /**
   * Totales de las tarjetas de resumen de /verificar-importacion.
   *
   * Son computeds y no metodos: se recalculan solos en cuanto se edita una
   * celda, asi que el numero que muestra la tarjeta y el de la tabla no pueden
   * quedar desincronizados.
   *
   * Un importe no numerico (NaN, por una celda a medio completar) cuenta como
   * cero en vez de arruinar la suma: Number(NaN) || 0 es 0. Un total que no
   * muestra ningun numero es peor que uno que muestra un numero incompleto, y
   * el error se avisa igual en la fila.
   */
  readonly totalCreditos = computed(() =>
    this._movimientos().reduce((total, mov) => total + (Number(mov.haber) || 0), 0),
  );

  readonly totalDebitos = computed(() =>
    this._movimientos().reduce((total, mov) => total + (Number(mov.debe) || 0), 0),
  );

  readonly diferencia = computed(() => this.totalCreditos() - this.totalDebitos());

  /**
   * Saldo con el que arranca el periodo y con el que termina.
   *
   * El PDF no manda el saldo de apertura como campo aparte: la fila de
   * "SALDO INICIAL/ANTERIOR" siembra la cadena en el backend y no llega aca
   * como movimiento. Se deduce de la primera fila igual que hace el backend
   * cuando el banco no imprime esa fila: apertura = saldo - haber + debe. Y el
   * saldo final es el de la ultima fila. Ambos salen de los movimientos de la
   * tabla, asi que se recalculan solos si se edita un importe y siempre cierran
   * con los totales: final = inicial + creditos - debitos.
   */
  readonly saldoInicial = computed(() => {
    const filas = this._movimientos();
    if (filas.length === 0) return 0;
    const primera = filas[0];
    return (
      Math.round(
        ((Number(primera.saldo) || 0) - (Number(primera.haber) || 0) + (Number(primera.debe) || 0)) * 100,
      ) / 100
    );
  });

  readonly saldoFinal = computed(() => {
    const filas = this._movimientos();
    if (filas.length === 0) return 0;
    return filas[filas.length - 1].saldo;
  });

  /**
   * Donde van a caer los movimientos: extractor del banco mas la cuenta elegida
   * en /importar-pdf. Va en el badge del encabezado de la pantalla de
   * verificacion, que es donde el usuario necesita ver a que cuenta esta
   * importando antes de confirmar.
   */
  readonly destino = computed(() => {
    const cuenta = this.cuentaNombre();
    const banco = this.banco();
    return [banco, cuenta].filter(Boolean).join(' · ');
  });

  /**
   * El backend devuelve filas sin id, y el *ngFor de la tabla trackea por
   * identidad. Sin un id estable Angular destruiria y recrearia el <tr> entero
   * en cada cambio.
   */
  private contadorId = 0;

  guardar(seleccion: SeleccionImportacion): void {
    this._seleccion.set(seleccion);
    this._movimientos.set([]);
    this._originales.set([]);
  }

  tieneSeleccion(): boolean {
    return this._seleccion() !== null;
  }

  limpiar(): void {
    this._seleccion.set(null);
    this._movimientos.set([]);
    this._originales.set([]);
  }

  /**
   * Guarda los movimientos que devolvio el extractor.
   *
   * El extractor no manda la columna `categoria` si el concepto no caia en
   * ninguna categoria, y en los movimientos importados puede venir ausente: se
   * deja tal cual y la pantalla lo lee con optional chaining.
   */
  setMovimientos(movimientos: MovimientoImportado[]): void {
    const conId = this.recalcularSaldos(
      movimientos.map((mov) => ({ ...mov, id: `mov-${this.contadorId++}` })),
    );
    this._movimientos.set(conId);
    // Foto del extracto recien leido: es lo que restaura el deshacer. Los
    // movimientos nunca se mutan (editar/agregar/quitar reemplazan objetos),
    // asi que la snapshot se puede guardar por referencia y compartir filas.
    this._originales.set(conId);
  }

  /**
   * True cuando la tabla se alejo de lo que trajo el extracto: se edito un
   * campo, se agrego una fila o se quito una. Mientras no haya cambios el
   * boton de deshacer no tiene sentido y se muestra deshabilitado.
   */
  readonly hayCambios = computed(() => {
    const actual = this._movimientos();
    const original = this._originales();
    if (actual.length !== original.length) return true;
    return actual.some(
      (mov, i) =>
        mov.fecha !== original[i].fecha ||
        mov.concepto !== original[i].concepto ||
        mov.referencia !== original[i].referencia ||
        mov.debe !== original[i].debe ||
        mov.haber !== original[i].haber ||
        mov.saldo !== original[i].saldo ||
        mov.categoria !== original[i].categoria,
    );
  });

  /**
   * Vuelve a los valores que devolvio el extractor, descartando ediciones,
   * filas agregadas a mano y bajas. Es el "ctrl z" grueso: no deshace paso a
   * paso, restaura el estado del PDF, que es contra lo que se revisa.
   */
  deshacerCambios(): void {
    this._movimientos.set(this._originales().slice());
  }

  /**
   * Agrega un movimiento en blanco al final, para el caso de que al PDF le
   * falte una operacion. Se devuelve el id recien creado para que la pantalla
   * pueda abrir directo la celda del concepto.
   */
  agregarMovimiento(): string {
    const id = `mov-${this.contadorId++}`;
    const hoy = new Date();
    const nuevo: MovimientoImportado = {
      id,
      fecha: `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-${String(
        hoy.getDate(),
      ).padStart(2, '0')}`,
      concepto: '',
      referencia: null,
      debe: 0,
      haber: 0,
      saldo: 0,
      // null y no 'operativo': un movimiento agregado a mano todavia no fue
      // clasificado, y la conciliacion lo muestra igual con el filtro en false.
      categoria: null,
    };

    this._movimientos.update((filas) => this.recalcularSaldos([...filas, nuevo]));
    return id;
  }

  /** Cambia un movimiento por id. Es lo que escribe la edicion en linea. */
  editarMovimiento(id: string, cambios: Partial<MovimientoImportado>): void {
    this._movimientos.update((filas) => {
      const indice = filas.findIndex((mov) => mov.id === id);
      // Un id que no existe se ignora en vez de romper la tabla: el click puede
      // caer en una fila que todavia no se habia pintado.
      if (indice < 0) return filas;

      const copia = [...filas];
      copia[indice] = { ...copia[indice], ...cambios, id };
      return this.recalcularSaldos(copia);
    });
  }

  /** Saca un movimiento. Sirve para los que se leyeron de mas. */
  quitarMovimiento(id: string): void {
    this._movimientos.update((filas) => this.recalcularSaldos(filas.filter((mov) => mov.id !== id)));
  }

  /**
   * Rehace la cadena de saldos.
   *
   * El extractor calcula saldo = saldo anterior + haber - debe (concurrente.py
   * normaliza esa cadena). Si alguien edita un importe desde la pantalla de
   * verificacion y el saldo queda como estaba, la conciliacion despues muestra
   * una cadena que no cierra ni con los numeros de esta misma pantalla.
   *
   * El saldo inicial no viene en ningun lado del movimiento, asi que se deduce
   * de la primera fila: apertura = saldo - (haber - debe). Con eso la cadena se
   * vuelve a armar entera y el saldo final sigue siendo el del banco salvo que
   * se toquen los importes, que es justo cuando tiene que cambiar.
   */
  private recalcularSaldos(filas: MovimientoImportado[]): MovimientoImportado[] {
    if (filas.length === 0) return filas;

    const primera = filas[0];
    let saldo =
      (Number(primera.saldo) || 0) - ((Number(primera.haber) || 0) - (Number(primera.debe) || 0));

    return filas.map((mov) => {
      saldo += (Number(mov.haber) || 0) - (Number(mov.debe) || 0);
      // Sin redondear, 0.1 + 0.2 deja 0.30000000000000004 en pantalla y el
      // usuario Cree que el extractor calculo mal.
      return { ...mov, saldo: Math.round(saldo * 100) / 100 };
    });
  }

  formatearImporte(valor: number | null | undefined): string {
    const numero = Number(valor ?? 0);
    if (!numero) {
      return '';
    }

    const signo = numero < 0 ? '-' : '';
    return (
      signo +
      Math.abs(numero).toLocaleString('es-AR', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }
}
