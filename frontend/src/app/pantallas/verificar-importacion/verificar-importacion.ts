import { CommonModule } from '@angular/common';
import { Component, HostListener, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { ImportacionService, MovimientoImportacion } from '../../servicios/importacion.service';

type ColumnaOrden = 'fecha' | 'concepto' | 'credito' | 'debito';

/**
 * Cuarto paso del flujo: verificación de los movimientos extraídos del PDF.
 * Los movimientos viven en ImportacionService como signal, así que las tarjetas
 * de resumen se recalculan solas con cada edición en línea.
 *
 * TODO: hoy la tabla arranca vacía porque el extractor todavía no está
 * conectado (ver ImportacionService.setMovimientos). Cuando /procesando-pdf
 * reciba los movimientos del backend, alcanza con llamar a ese método y la
 * pantalla queda poblada sin tocar la vista.
 */
@Component({
  selector: 'app-verificar-importacion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './verificar-importacion.html',
})
export class VerificarImportacionComponent {
  private readonly router = inject(Router);
  readonly importacion = inject(ImportacionService);

  /** Atajos de las tarjetas de resumen. */
  readonly totalCreditos = this.importacion.totalCreditos;
  readonly totalDebitos = this.importacion.totalDebitos;
  readonly diferencia = this.importacion.diferencia;
  readonly cantidadMovimientos = this.importacion.cantidadMovimientos;
  readonly hayErrores = this.importacion.hayErrores;
  readonly hayAvisos = this.importacion.hayAvisos;
  readonly puedeConfirmar = this.importacion.puedeConfirmar;
  readonly cuentaNombre = this.importacion.cuentaNombre;

  /** Fila que está en modo edición (null = todas en modo lectura). */
  readonly editandoId = signal<string | null>(null);

  /**
   * Copia de la fila al entrar en edición: como los cambios se aplican en vivo
   * (para que las tarjetas se actualicen al vuelo), "Cancelar" revierte contra
   * este borrador.
   */
  private readonly borrador = signal<MovimientoImportacion | null>(null);

  /** Columna del menú de opciones que está abierto. */
  readonly menuColumna = signal<ColumnaOrden | null>(null);

  /** Posición del popover, calculada a partir del botón que se clicó. */
  readonly menuPos = signal<{ left: number; top: number } | null>(null);

  private readonly columnaOrden = signal<ColumnaOrden | null>(null);
  private readonly direccionOrden = signal<'asc' | 'desc'>('asc');

  /** Movimientos con el orden aplicado (los nulos de importes van al final). */
  readonly movimientosOrdenados = computed(() => {
    const movimientos = this.importacion.movimientos();
    const columna = this.columnaOrden();
    const signo = this.direccionOrden() === 'asc' ? 1 : -1;

    if (!columna) {
      return movimientos;
    }

    return [...movimientos].sort((a, b) => {
      const va = this.valorOrdenable(a, columna);
      const vb = this.valorOrdenable(b, columna);

      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;

      return (va < vb ? -1 : va > vb ? 1 : 0) * signo;
    });
  });

  /**
   * Se activa cada vez que cambia un total, para que los números "rueden" en
   * lugar de saltar de golpe. Se apaga al terminar la animación para poder
   * volver a dispararla en la edición siguiente.
   */
  readonly destacados = signal(false);
  private primerCalculo = true;

  constructor() {
    // Sin selección previa no hay nada que verificar: volvemos al paso 2.
    if (!this.importacion.tieneSeleccion()) {
      this.router.navigate(['/importar-pdf']);
    }

    effect((onCleanup) => {
      // Estas tres lecturas son las dependencias del efecto.
      this.totalCreditos();
      this.totalDebitos();
      this.diferencia();

      if (this.primerCalculo) {
        this.primerCalculo = false; // No queremos el destello en el primer render
        return;
      }

      this.destacados.set(true);
      const timer = setTimeout(() => this.destacados.set(false), 500);
      onCleanup(() => clearTimeout(timer));
    });
  }

  // --- Totales formateados --------------------------------------------------

  creditosFormateados(): string {
    return this.importacion.formatearImporte(this.totalCreditos());
  }

  debitosFormateados(): string {
    return this.importacion.formatearImporte(this.totalDebitos());
  }

  diferenciaFormateada(): string {
    return this.importacion.formatearImporte(this.diferencia());
  }

  formatearImporte(valor: number | null): string {
    return this.importacion.formatearImporte(valor ?? 0);
  }

  formatearFecha(iso: string): string {
    return this.importacion.formatearFecha(iso);
  }

  // --- Errores por celda ----------------------------------------------------

  error(mov: MovimientoImportacion, campo: string): string | null {
    return this.importacion.erroresPorMovimiento().get(mov.id)?.[campo] ?? null;
  }

  tieneErrores(mov: MovimientoImportacion): boolean {
    return this.importacion.erroresPorMovimiento().has(mov.id);
  }

  /** Sospecha de formato: se pinta en amarillo pero no frena la importación. */
  aviso(mov: MovimientoImportacion, campo: string): string | null {
    return this.importacion.avisosPorMovimiento().get(mov.id)?.[campo] ?? null;
  }

  tieneAvisos(mov: MovimientoImportacion): boolean {
    return this.importacion.avisosPorMovimiento().has(mov.id);
  }

  /** Una fila no puede tener errores y avisos a la vez: manda el rojo. */
  estadoFila(mov: MovimientoImportacion): 'error' | 'aviso' | 'ok' {
    if (this.tieneErrores(mov)) {
      return 'error';
    }

    return this.tieneAvisos(mov) ? 'aviso' : 'ok';
  }

  // --- Edición en línea -----------------------------------------------------

  editar(mov: MovimientoImportacion): void {
    this.borrador.set({ ...mov });
    this.editandoId.set(mov.id);
  }

  guardar(mov: MovimientoImportacion): void {
    if (this.tieneErrores(mov)) {
      return; // Dejamos la fila en edición para que se corrija
    }
    this.borrador.set(null);
    this.editandoId.set(null);
  }

  /** Cierra el editor y vuelve la fila a como estaba antes de editarlo. */
  cancelarEdicion(): void {
    const borrador = this.borrador();

    if (borrador) {
      this.importacion.actualizarMovimiento(borrador.id, {
        fecha: borrador.fecha,
        concepto: borrador.concepto,
        credito: borrador.credito,
        debito: borrador.debito,
      });
    }

    this.borrador.set(null);
    this.editandoId.set(null);
  }

  /** Agrega una fila y la deja lista para completar (vuelve en modo edición). */
  agregarMovimiento(): MovimientoImportacion {
    const nuevo = this.importacion.agregarMovimiento();
    this.borrador.set({ ...nuevo });
    this.editandoId.set(nuevo.id);

    return nuevo;
  }

  eliminar(mov: MovimientoImportacion): void {
    if (this.editandoId() === mov.id) {
      this.editandoId.set(null);
      this.borrador.set(null);
    }
    this.importacion.eliminarMovimiento(mov.id);
  }

  cambiarFecha(mov: MovimientoImportacion, valor: string): void {
    this.importacion.actualizarMovimiento(mov.id, { fecha: valor });
  }

  cambiarConcepto(mov: MovimientoImportacion, valor: string): void {
    this.importacion.actualizarMovimiento(mov.id, { concepto: valor });
  }

  /** Traduce "1.234,5" a número antes de guardarlo. */
  cambiarImporte(mov: MovimientoImportacion, campo: 'credito' | 'debito', valor: string): void {
    this.importacion.actualizarMovimiento(mov.id, {
      [campo]: this.importacion.parsearImporte(valor),
    });
  }

  // --- Menú de opciones por columna -----------------------------------------

  alternarMenuColumna(columna: ColumnaOrden, event: MouseEvent): void {
    event.stopPropagation();

    if (this.menuColumna() === columna) {
      this.cerrarMenu();
      return;
    }

    const boton = event.currentTarget as HTMLElement;
    const rect = boton.getBoundingClientRect();
    const altoMenu = 168; // Alto aproximado del popover

    // Si no entra abajo del botón, lo abrimos hacia arriba.
    const haciaArriba = rect.bottom + altoMenu > window.innerHeight;
    const left = Math.min(rect.left, window.innerWidth - 240);

    this.menuColumna.set(columna);
    this.menuPos.set({
      left: Math.max(8, left),
      top: haciaArriba ? Math.max(8, rect.top - altoMenu) : rect.bottom + 4,
    });
  }

  cerrarMenu(): void {
    this.menuColumna.set(null);
    this.menuPos.set(null);
  }

  /** El menú único trabaja sobre la columna abierta, así que no necesita recibirla. */
  ordenarPorMenu(direccion: 'asc' | 'desc'): void {
    const columna = this.menuColumna();
    if (columna) {
      this.ordenarPor(columna, direccion);
    }
  }

  quitarOrdenDesdeMenu(): void {
    this.quitarOrden();
  }

  hayOrdenActiva(): boolean {
    return this.columnaOrden() !== null;
  }

  ordenarPor(columna: ColumnaOrden, direccion: 'asc' | 'desc'): void {
    this.columnaOrden.set(columna);
    this.direccionOrden.set(direccion);
    this.cerrarMenu();
  }

  quitarOrden(): void {
    this.columnaOrden.set(null);
    this.cerrarMenu();
  }

  estaOrdenada(columna: ColumnaOrden): boolean {
    return this.columnaOrden() === columna;
  }

  iconoOrden(columna: ColumnaOrden): string {
    if (!this.estaOrdenada(columna)) {
      return '';
    }
    return this.direccionOrden() === 'asc' ? 'pi-arrow-up' : 'pi-arrow-down';
  }

  @HostListener('document:click', ['$event'])
  onClickFuera(event: MouseEvent): void {
    // El clic del propio botón lo corta con stopPropagation, así que si llegamos
    // acá es un clic de verdad en cualquier otro lado.
    this.cerrarMenu();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.menuColumna.set(null);
  }

  // --- Cierre del flujo -----------------------------------------------------

  confirmar(): void {
    if (!this.puedeConfirmar()) {
      return;
    }

    this.importacion.confirmarMovimientos();
    this.router.navigate(['/']);
  }

  cancelar(): void {
    this.importacion.confirmarMovimientos(); // Descarta lo no confirmado
    this.router.navigate(['/']);
  }

  /** Compara según el tipo de la columna (los importes nulos van al final). */
  private valorOrdenable(
    mov: MovimientoImportacion,
    columna: ColumnaOrden,
  ): string | number | null {
    if (columna === 'fecha') {
      return mov.fecha || null;
    }

    if (columna === 'concepto') {
      return mov.concepto || null;
    }

    return mov[columna];
  }
}
