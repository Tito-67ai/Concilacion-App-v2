import { CommonModule } from '@angular/common';
import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';

import { ImportacionService, MovimientoImportado } from '../../servicios/importacion.service';

/**
 * Destino del enlace de ayuda.
 *
 * A proposito va sin destinatario: mandar el reporte a una direccion inventada
 * es peor que abrir el cliente de correo con el asunto ya puesto. Cuando exista
 * el canal de soporte se completa el CORREO y el reporte llega solo.
 */
const CORREO_SOPORTE = '';

/** Columnas de la tabla. El orden es el de la pantalla. */
type ClaveColumna = 'fecha' | 'concepto' | 'credito' | 'debito';

interface Columna {
  clave: ClaveColumna;
  titulo: string;
  /** Como se ordena de menor a mayor: 'texto' o 'numero'. */
  orden: 'texto' | 'numero';
}

/** Campo que se esta editando y con que valor crudo, antes de validarlo. */
interface Borrador {
  id: string;
  campo: ClaveColumna;
  valor: string;
}

const COLUMNAS: Columna[] = [
  { clave: 'fecha', titulo: 'Fecha', orden: 'texto' },
  { clave: 'concepto', titulo: 'Concepto', orden: 'texto' },
  { clave: 'credito', titulo: 'Crédito', orden: 'numero' },
  { clave: 'debito', titulo: 'Débito', orden: 'numero' },
];

/**
 * Parte 4 del flujo: la pantalla de verificacion (/verificar-importacion).
 *
 * Es la unica pantalla donde el usuario puede corregir el extracto antes de que
 * exista: de este lado todavia no se guardo nada, asi que un importe mal leido
 * se corrige escribiendo el numero. Despues de confirmar, la conciliacion
 * recibe los movimientos ya revisados.
 *
 * La edicion es en linea y en vivo: cada celda es un input que escribe en el
 * servicio al confirmar con Enter o al salir con Tab o clic. No hay un boton de
 * "guardar" por fila porque un boton por fila es un boton que alguien va a
 * olvidar, y lo que se guardaria es la mitad de la correccion.
 */
@Component({
  selector: 'app-verificar-importacion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './verificar-importacion.html',
})
export class VerificarImportacionComponent {
  // El servicio va primero a proposito: los signals de abajo leen de el, y en
  // JavaScript una referencia a un campo que todavia no se inicializo es
  // undefined, no un error visible.
  private readonly router = inject(Router);
  private readonly importacion = inject(ImportacionService);

  readonly columnas = COLUMNAS;
  readonly totalCreditos = this.importacion.totalCreditos;
  readonly totalDebitos = this.importacion.totalDebitos;
  readonly diferencia = this.importacion.diferencia;
  readonly destino = this.importacion.destino;

  /** Menu de opciones abierto de una columna, por clave. */
  readonly menuAbierto = signal<ClaveColumna | null>(null);

  /** Menu de columnas ocultas. */
  readonly menuColumnasAbierto = signal(false);

  /** Columnas que el usuario escondio con los tres puntitos. */
  private readonly ocultas = signal<ClaveColumna[]>([]);

  /** Orden activo de la tabla, si el usuario ordeno por alguna columna. */
  private readonly orden = signal<{ clave: ClaveColumna; descendente: boolean } | null>(null);

  /** Celda en edicion: id del movimiento, columna y valor crudo tipeado. */
  readonly borrador = signal<Borrador | null>(null);

  /** Error de la ultima celda confirmada, para mostrarlo en la fila. */
  readonly errorCelda = signal('');

  readonly movimientos = this.importacion.movimientos;

  /** La celda en edicion, para enfocarla y seleccionar el valor a reemplazar. */
  private readonly celdaEnEdicion = viewChild<ElementRef<HTMLInputElement>>('celdaEnEdicion');

  constructor() {
    // Si se entra por la URL no hay nada que verificar: la seleccion vive en
    // memoria y se pierde al recargar.
    if (!this.importacion.tieneSeleccion()) {
      this.router.navigate(['/importar-pdf']);
    }

    // Recien aparece el input cuando hay borrador, asi que el autofocus del
    // markup no alcanza: hay que enfocarlo despues de que se creo. Y se
    // selecciona el contenido para que escribir pise el valor viejo en vez de
    // agregarse al final.
    effect(() => {
      const celda = this.celdaEnEdicion();
      if (!celda) return;
      queueMicrotask(() => {
        celda.nativeElement.focus();
        celda.nativeElement.select();
      });
    });
  }

  /** Que columnas se pintan: todas menos las que el usuario escondio. */
  readonly columnasVisibles = computed(() => {
    const fuera = this.ocultas();
    return COLUMNAS.filter((columna) => !fuera.includes(columna.clave));
  });

  /** Si una columna esta escondida, su celda tampoco se pinta. */
  visible(clave: ClaveColumna): boolean {
    return !this.ocultas().includes(clave);
  }

  /**
   * Filas de la tabla, ordenadas si el usuario ordeno alguna columna.
   *
   * Las columnas ocultas no borran datos: el total de la tarjeta y el pie
   * "Movimientos a importar" siguen contando todas las filas.
   */
  readonly filasVisibles = computed(() => {
    const orden = this.orden();
    const filas = [...this.movimientos()];
    if (!orden) return filas;

    return filas.sort((a, b) => this.comparar(this.valorDe(a, orden.clave), this.valorDe(b, orden.clave), orden.clave) * (orden.descendente ? -1 : 1));
  });

  /**
   * Errores por movimiento, para pintar la fila en rojo y bloquear el boton de
   * confirmar. Son datos, no texto: el mensaje concreto se arma en el template.
   */
  readonly errores = computed(() => {
    const mapa = new Map<string, string[]>();
    for (const mov of this.movimientos()) {
      const problemas: string[] = [];

      if (!this.fechaValida(mov.fecha)) problemas.push('La fecha no es válida.');
      if (!String(mov.concepto ?? '').trim()) problemas.push('El concepto está vacío.');

      for (const campo of ['debe', 'haber'] as const) {
        const valor = mov[campo];
        if (!Number.isFinite(Number(valor))) problemas.push('Hay un importe que no es un número.');
        else if (Number(valor) < 0) problemas.push('Un importe no puede ser negativo.');
      }

      if (problemas.length) mapa.set(mov.id, problemas);
    }
    return mapa;
  });

  readonly hayErrores = computed(() => this.errores().size > 0);

  /** Sin filas no hay nada que importar, y con errores no se debe importar. */
  readonly puedeConfirmar = computed(() => this.movimientos().length > 0 && !this.hayErrores());

  // ------------------------------------------------------------------
  // Lectura de valores
  // ------------------------------------------------------------------

  valorDe(mov: MovimientoImportado, columna: ClaveColumna): string | number {
    if (columna === 'credito') return Number(mov.haber) || 0;
    if (columna === 'debito') return Number(mov.debe) || 0;
    return mov[columna] ?? '';
  }

  /** El importe se muestra en formato argentino, con el signo adelante. */
  formatear(valor: string | number): string {
    return this.importacion.formatearImporte(Number(valor));
  }

  /**
   * La fecha se muestra como se lee acá (dd/mm/aaaa), no como la entrega el
   * extractor (AAAA-MM-DD). Se arma con las partes del string y no con Date a
   * proposito: parsear "2026-09-01" como UTC y mostrarlo en hora argentina
   * retrocede un dia.
   */
  fechaLegible(fecha: string | null | undefined): string {
    if (!fecha) return '—';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return fecha;
    const [anio, mes, dia] = fecha.split('-');
    return `${dia}/${mes}/${anio}`;
  }

  /**
   * Lo que se ve mientras se edita un importe: el numero plano, sin separador
   * de miles. Editar "1.234,56" es mas comodo que editar "1234,56" y el input
   * type text con inputMode numeric acepta punto y coma.
   */
  valorEditable(valor: string | number): string {
    const numero = Number(valor);
    return Number.isFinite(numero) ? String(numero) : '';
  }

  fechaValida(fecha: string | null | undefined): boolean {
    if (!fecha) return false;
    // El extractor entrega ISO (YYYY-MM-DD). Se valida el formato y que la fecha
    // exista de verdad: 2026-02-31 no es una fecha.
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return false;
    const [anio, mes, dia] = fecha.split('-').map(Number);
    const fechaReal = new Date(anio, mes - 1, dia);
    return (
      fechaReal.getFullYear() === anio &&
      fechaReal.getMonth() === mes - 1 &&
      fechaReal.getDate() === dia
    );
  }

  // ------------------------------------------------------------------
  // Edicion en linea
  // ------------------------------------------------------------------

  /** La celda tiene el foco: se muestra el valor crudo para editarlo. */
  editar(mov: MovimientoImportado, columna: ClaveColumna, valor: string): void {
    this.errorCelda.set('');
    this.borrador.set({ id: mov.id, campo: columna, valor });
  }

  /**
   * Confirma la celda (Enter, Tab o clic afuera).
   *
   * Se parsea segun como escribe un usuario argentino: "1.234,56" son mil
   * doscientos treinta y cuatro con cincuenta y seis, no 1.234. Un input
   * type=number no acepta esa coma y obliga a tipear el numero a la inversa.
   */
  confirmarBorrador(): void {
    const borrador = this.borrador();
    if (!borrador) return;

    const { id, campo, valor } = borrador;
    const limpio = valor.trim();

    if (campo === 'credito' || campo === 'debito') {
      const numero = this.parsearImporte(limpio);
      if (limpio !== '' && !Number.isFinite(numero)) {
        this.errorCelda.set(`"${limpio}" no es un importe válido.`);
        return;
      }
      this.importacion.editarMovimiento(id, campo === 'credito' ? { haber: numero } : { debe: numero });
    } else if (campo === 'fecha') {
      if (!this.fechaValida(limpio)) {
        this.errorCelda.set('La fecha tiene que ser válida (AAAA-MM-DD).');
        return;
      }
      this.importacion.editarMovimiento(id, { fecha: limpio });
    } else {
      this.importacion.editarMovimiento(id, { concepto: limpio });
    }

    this.borrador.set(null);
    this.errorCelda.set('');
  }

  /** Escape: la celda vuelve a lo que estaba. */
  cancelarBorrador(): void {
    this.borrador.set(null);
    this.errorCelda.set('');
  }

  /**
   * Interpreta un importe tipeado.
   *
   * Con coma, los puntos son separadores de miles ("1.234,56" -> 1234.56). Sin
   * coma, el punto es decimal ("1234.56" -> 1234.56). Es la lectura que espera
   * alguien que escribe en es-AR; el caso "1.234" queriendo decir 1234 queda
   * ambiguo y se interpreta como 1.234.
   */
  parsearImporte(texto: string): number {
    const limpio = texto.replace(/\s/g, '');
    if (limpio === '') return 0;
    const normalizado = limpio.includes(',') ? limpio.replace(/\./g, '').replace(',', '.') : limpio;
    return Number(normalizado);
  }

  // ------------------------------------------------------------------
  // Filas y columnas
  // ------------------------------------------------------------------

  agregarMovimiento(): void {
    const id = this.importacion.agregarMovimiento();
    // Se deja la celda de concepto lista para escribir: agregar la fila es
    // siempre para escribir algo.
    this.borrador.set({ id, campo: 'concepto', valor: '' });
  }

  quitarMovimiento(id: string): void {
    this.importacion.quitarMovimiento(id);
  }

  alternarMenu(columna: ClaveColumna, event: MouseEvent): void {
    event.stopPropagation();
    this.errorCelda.set('');
    this.menuAbierto.update((abierta) => (abierta === columna ? null : columna));
  }

  alternarMenuColumnas(event: MouseEvent): void {
    event.stopPropagation();
    this.menuAbierto.set(null);
    this.menuColumnasAbierto.update((abierto) => !abierto);
  }

  ordenarPor(columna: ClaveColumna): void {
    this.orden.update((orden) =>
      orden?.clave === columna ? { clave: columna, descendente: !orden.descendente } : { clave: columna, descendente: false },
    );
    this.menuAbierto.set(null);
  }

  /** La flechita del encabezado dice en que sentido esta ordenado. */
  sentidoOrden(columna: ClaveColumna): 'asc' | 'desc' | null {
    const orden = this.orden();
    if (orden?.clave !== columna) return null;
    return orden.descendente ? 'desc' : 'asc';
  }

  /**
   * Oculta una columna.
   *
   * No se deja ocultar la ultima: una tabla sin columnas niHeaders ni filas
   * deja de ser una tabla y el usuario no tiene como volver sin adivinar.
   */
  ocultarColumna(columna: ClaveColumna): void {
    this.menuAbierto.set(null);
    if (this.columnasVisibles().length <= 1) return;
    this.ocultas.update((ocultas) => [...ocultas, columna]);
  }

  mostrarColumna(columna: ClaveColumna): void {
    this.ocultas.update((ocultas) => ocultas.filter((clave) => clave !== columna));
  }

  estaOculta(columna: ClaveColumna): boolean {
    return this.ocultas().includes(columna);
  }

  private comparar(a: string | number, b: string | number, columna: ClaveColumna): number {
    const tipo = COLUMNAS.find((col) => col.clave === columna)?.orden;
    if (tipo === 'numero') return Number(a) - Number(b);
    // es-AR para que "á" y "a" no queden separadas por el acento.
    return String(a).localeCompare(String(b), 'es');
  }

  // ------------------------------------------------------------------
  // Cierre del flujo
  // ------------------------------------------------------------------

  /**
   * Confirma: los movimientos quedan en el servicio y la conciliacion los toma
   * al arrancar. No se limpia acá porque ese limpiar es justamente el gesto que
   * los entrega.
   */
  confirmar(): void {
    if (!this.puedeConfirmar()) return;
    this.router.navigate(['/']);
  }

  /** Cancela: se descarta todo lo leido y no se importa nada. */
  cancelar(): void {
    this.importacion.limpiar();
    this.router.navigate(['/']);
  }

  /** Enlace de ayuda. Con el destino vacio abre el cliente de correo sin receptor. */
  get correoSoporte(): string {
    const asunto = encodeURIComponent('No se leyó bien un extracto en la conciliación');
    return `mailto:${CORREO_SOPORTE}?subject=${asunto}`;
  }
}
