import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { interval, takeWhile, timer } from 'rxjs';
import { ImportacionService } from '../../servicios/importacion.service';

export type EstadoPaso = 'pendiente' | 'cargando' | 'completado';

interface PasoProceso {
  titulo: string;
  detalle: string;
}

const PASOS: PasoProceso[] = [
  {
    titulo: 'Leyendo el archivo',
    detalle: 'Abriendo el PDF y extrayendo el texto de sus páginas',
  },
  {
    titulo: 'Detectando la tabla de movimientos',
    detalle: 'Buscando las columnas de fecha, concepto, debe y haber',
  },
  {
    titulo: 'Interpretando fechas e importes',
    detalle: 'Normalizando los datos para dejarlos listos para conciliar',
  },
];

/** Cada paso tarda estos 3 segundos en "procesarse". */
const DURACION_PASO_MS = 3000;

/**
 * Parte 3 del flujo de importación: pantalla de carga (/procesando-pdf).
 * Los pasos avanzan solos (Pendiente -> Cargando -> Completado) con RxJS.
 *
 * TODO: reemplazar la simulación por la llamada real al backend. Cuando exista,
 * el estado de cada paso debería venir del progreso de la petición (ej. SSE)
 * en lugar de los timers de abajo.
 */
@Component({
  selector: 'app-procesando-pdf',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './procesando-pdf.html',
})
export class ProcesandoPdfComponent {
  private readonly router = inject(Router);
  private readonly importacion = inject(ImportacionService);

  readonly pasos = PASOS;

  /** Nombre del PDF y cuenta elegidos en la pantalla anterior. */
  readonly archivoNombre = this.importacion.archivoNombre;
  readonly cuentaNombre = this.importacion.cuentaNombre;

  /** Estado de cada paso: el primero ya terminó y el segundo está en proceso. */
  readonly estados = signal<EstadoPaso[]>(['completado', 'cargando', 'pendiente']);

  /** Reloj de la espera, para que la espera se vea más viva. */
  readonly segundosTranscurridos = signal(0);

  readonly finalizado = computed(() => this.estados().every((estado) => estado === 'completado'));

  readonly progreso = computed(() => {
    const completados = this.estados().filter((estado) => estado === 'completado').length;
    return Math.round((completados / PASOS.length) * 100);
  });

  readonly tiempoTranscurrido = computed(() => {
    const total = this.segundosTranscurridos();
    const minutos = Math.floor(total / 60);
    const segundos = total % 60;
    return `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
  });

  constructor() {
    // Si el usuario entra directo por la URL no hay nada que procesar:
    // lo mandamos de vuelta al paso anterior.
    if (!this.importacion.tieneSeleccion()) {
      this.router.navigate(['/importar-pdf']);
      return;
    }

    // Cada 3 segundos el paso en curso pasa a completado y arranca el siguiente.
    // takeWhile corta el stream cuando terminamos los tres pasos.
    interval(DURACION_PASO_MS)
      .pipe(
        takeWhile(() => !this.finalizado()),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.avanzarPaso());

    // Reloj: un tick por segundo, independiente del avance de los pasos.
    timer(1000, 1000)
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.segundosTranscurridos.update((segundos) => segundos + 1));
  }

  private avanzarPaso(): void {
    const estados = [...this.estados()];
    const indice = estados.findIndex((estado) => estado === 'cargando');

    if (indice === -1) {
      return;
    }

    estados[indice] = 'completado';

    if (indice + 1 < estados.length) {
      estados[indice + 1] = 'cargando';
    }

    this.estados.set(estados);
  }

  /** Aborta el proceso y vuelve a la pantalla de conciliación. */
  cancelar(): void {
    this.importacion.limpiar();
    this.importacion.limpiarMovimientos();
    this.router.navigate(['/']);
  }

  /** Paso 4: revisar los movimientos antes de confirmar la importación. */
  verMovimientos(): void {
    this.router.navigate(['/verificar-importacion']);
  }

  importarOtro(): void {
    this.importacion.limpiar();
    this.importacion.limpiarMovimientos();
    this.router.navigate(['/importar-pdf']);
  }
}