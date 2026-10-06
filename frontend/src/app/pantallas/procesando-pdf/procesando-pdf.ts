import { CommonModule } from '@angular/common';
import { HttpClient, HttpEventType } from '@angular/common/http';
import { Component, OnDestroy, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Subscription, timeout } from 'rxjs';

import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

/**
 * Un PDF de 30 paginas con tablas tarda bastante en pdfplumber. Si no se corta,
 * el paso queda en "cargando" para siempre cuando algo se rompe en el medio y el
 * usuario no tiene forma de saber que paso.
 */
const TIMEOUT_IMPORTACION_MS = 180000;

export type EstadoPaso = 'pendiente' | 'cargando' | 'completado' | 'error';

interface PasoProceso {
  titulo: string;
  detalle: string;
  /** Que esta haciendo el backend mientras este paso esta en curso. */
  haciendo: string;
}

/**
 * Los tres pasos del analisis, con el motivo real de cada uno.
 *
 * El texto importa: "Puede demorar unos minutos" sin decir que esta haciendo el
 * servidor no le dice a nadie si esperar es normal o si se colgó.
 */
const PASOS: PasoProceso[] = [
  {
    titulo: 'Leyendo el archivo',
    detalle: 'Abriendo el PDF y extrayendo el texto de sus páginas',
    haciendo: 'Subiendo el archivo y abriendo el PDF',
  },
  {
    titulo: 'Detectando la tabla de movimientos',
    detalle: 'Buscando las columnas de fecha, concepto, debe y haber',
    haciendo: 'Recorriendo las páginas y armando las filas',
  },
  {
    titulo: 'Interpretando fechas e importes',
    detalle: 'Normalizando los datos y calculando el saldo de cada línea',
    haciendo: 'Ajustando fechas, importes y la cadena de saldos',
  },
];

/**
 * Parte 3 del flujo de importacion: pantalla de procesamiento (/procesando-pdf).
 *
 * Los pasos NO avanzan con timers: cada uno se mueve por un evento real de la
 * request. POST /extractos/procesar es una sola llamada que hace todo el trabajo
 * (extractos.py:177), asi que los unicos cortes reales que hay son el envio del
 * cuerpo, la llegada de la respuesta y el parseo de la respuesta. Los pasos se
 * mapean a eso:
 *
 *   1. Leyendo        -> de "cargando" a "completado" cuando el cuerpo se subio.
 *   2. Detectando     -> cubre la espera del servidor, que es donde esta el
 *                        trabajo de verdad (pdfplumber sobre todas las paginas).
 *   3. Interpretando  -> se completa cuando se leyeron las filas y se pasaron
 *                        a /verificar-importacion para que el usuario las revise.
 *
 * La version anterior de esta pantalla usaba un interval de 3 segundos por paso
 * y un POST que nunca se hacia: el stepper avanzaba solo, con luz verde, sobre
 * un archivo que en realidad no se estaba leyendo. Un progreso falso en una
 * conciliacion es peor que no tener progreso.
 */
@Component({
  selector: 'app-procesando-pdf',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './procesando-pdf.html',
})
export class ProcesandoPdfComponent implements OnDestroy {
  readonly pasos = PASOS;

  // Se leen del servicio con computed en vez de guardar el valor: el servicio
  // se inyecta mas abajo en la clase y una referencia directa a uno de sus
  // signals todavia no existe cuando estos campos se inicializan.
  readonly archivoNombre = computed(() => this.importacion.archivoNombre());
  readonly cuentaNombre = computed(() => this.importacion.cuentaNombre());
  readonly bancoNombre = computed(() => this.importacion.banco());

  /** Estado de cada paso. El primero arranca en curso porque el envio empieza ya. */
  readonly estados = signal<EstadoPaso[]>(['cargando', 'pendiente', 'pendiente']);

  /** Porcentaje del cuerpo ya subido. -1 cuando el navegador no lo reporta. */
  readonly envioProgreso = signal(-1);

  /** Reloj de la espera, para que se vea que sigue trabajando. */
  readonly segundosTranscurridos = signal(0);

  /** El motivo real del fallo, tal cual lo devuelve el backend. */
  readonly errorMensaje = signal('');

  readonly finalizado = computed(() => this.estados().every((estado) => estado === 'completado'));

  readonly fallo = computed(() => this.estados().some((estado) => estado === 'error'));

  readonly progreso = computed(() => {
    const completados = this.estados().filter((estado) => estado === 'completado').length;
    // Un fallo no cuenta como avance: si el paso 2 falla, mostrar 66% de
    // progreso seria decir que se hizo trabajo que no se hizo.
    return Math.round((completados / PASOS.length) * 100);
  });

  readonly tiempoTranscurrido = computed(() => {
    const total = this.segundosTranscurridos();
    const minutos = Math.floor(total / 60);
    const segundos = total % 60;
    return `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`;
  });

  /** El paso en curso, para el titulo del spinner. */
  readonly pasoEnCurso = computed(() => PASOS.findIndex((_, i) => this.estados()[i] === 'cargando'));

  private readonly router = inject(Router);
  private readonly http = inject(HttpClient);
  private readonly importacion = inject(ImportacionService);

  private readonly subscription = new Subscription();
  private reloj: ReturnType<typeof setInterval> | null = null;

  constructor() {
    // Si el usuario entra directo por la URL no hay nada que procesar: Angular
    // destruyo la pantalla anterior y con ella la seleccion.
    if (!this.importacion.tieneSeleccion()) {
      this.router.navigate(['/importar-pdf']);
      return;
    }

    this.reloj = setInterval(() => this.segundosTranscurridos.update((s) => s + 1), 1000);
    this.procesar();
  }

  ngOnDestroy(): void {
    if (this.reloj) {
      clearInterval(this.reloj);
    }
    // Abortar la peticion: si el usuario se va a otra pantalla mientras el
    // backend sigue leyendo un PDF de 30 paginas, el trabajo se sigue
    // consumiendo en el servidor sin que nadie mire el resultado.
    this.subscription.unsubscribe();
  }

  private procesar(): void {
    const { archivo, banco } = this.importacion.seleccion()!;
    const cuerpo = new FormData();
    cuerpo.append('banco', banco);
    cuerpo.append('archivo', archivo, archivo.name);

    // observe: 'events' es lo que da los tipos de evento en vez de solo la
    // respuesta final. Sin esto no hay forma de saber cuando termino de subir
    // el cuerpo, que es lo que separa el paso 1 del paso 2.
    this.subscription.add(
      this.http
        .post(`${API}/extractos/procesar`, cuerpo, {
          observe: 'events',
          reportProgress: true,
        })
        .pipe(timeout(TIMEOUT_IMPORTACION_MS))
        .subscribe({
          next: (evento) => this.alEvento(evento),
          error: (error) => this.alError(error),
          complete: () => {
            // El next de la respuesta ya hizo todo. Si se llegara aca sin
            // respuesta seria raro, pero el paso 3 tiene que quedar en un
            // estado y no en "cargando" para siempre.
            //
            // Con un fallo ya marcado no se toca nada: sin este chequeo, un
            // error de contenido (respuesta 200 sin movimientos) terminaba
            // borrando el paso en rojo y volviendo a mostrar todo en verde.
            if (!this.fallo()) {
              this.marcarFinalizado();
            }
          },
        }),
    );
  }

  private alEvento(evento: any): void {
    switch (evento.type) {
      case HttpEventType.UploadProgress:
        this.envioProgreso.set(
          evento.total ? Math.round((evento.loaded / evento.total) * 100) : -1,
        );
        // El cuerpo ya subio completo: el servidor arranco a abrir el PDF.
        if (evento.total && evento.loaded >= evento.total) {
          this.completarPaso(0);
          this.iniciarPaso(1);
        }
        break;

      case HttpEventType.Response:
        // El paso 3 arranca ANTES de cerrar los dos primeros: si se cerraran
        // primero, el 2 todavia estaria en "pendiente", no habria ningun paso
        // en curso y marcarFinalizado() daria por terminada la pantalla antes
        // de tiempo.
        this.iniciarPaso(2);
        this.completarPaso(0);
        this.completarPaso(1);
        this.alRespuesta(evento.body);
        break;

      default:
        // Sent, ResponseHeader, DownloadProgress: no mueven ningun paso.
        break;
    }
  }

  private alRespuesta(cuerpo: any): void {
    const movimientos = cuerpo?.datos ?? [];

    if (!movimientos.length) {
      // El backend respondio 200 pero no hay movimientos. El 200 con una lista
      // vacia es indistinguible de un extracto sin movimientos, asi que se
      // avisa con el motivo que mando el extractor.
      this.fallar(1, cuerpo?.detail ?? 'El archivo se leyó pero no tiene movimientos.');
      return;
    }

    this.importacion.setMovimientos(movimientos);

    // El tercer paso se completa recien aca: recien ahora hay fechas e importes
    // normalizados, que es literalmente lo que el paso promete.
    this.completarPaso(2);

    // No se va directo a la conciliacion todavia: antes hay que dejar revisar
    // lo leido. /verificar-importacion es la ultima pantalla del flujo y desde
    // ahi, con el OK del usuario, la conciliacion toma los movimientos.
    this.router.navigate(['/verificar-importacion']);
  }

  private alError(error: any): void {
    const detalle = error?.error?.detail;
    const mensaje =
      typeof detalle === 'string' && detalle.trim()
        ? detalle
        : Array.isArray(detalle) && detalle.length
          ? detalle.map((d: any) => d?.msg ?? JSON.stringify(d)).join('; ')
          : error?.name === 'TimeoutError'
            ? `El backend no respondió en ${TIMEOUT_IMPORTACION_MS / 1000} segundos. Puede que el PDF sea muy pesado o que un extractor se haya quedado leyendo.`
            : 'No se pudo procesar el PDF.';

    this.fallar(this.pasoEnCurso() < 0 ? 0 : this.pasoEnCurso(), mensaje);
  }

  private completarPaso(indice: number): void {
    // Nada de marcar la pantalla como terminada desde aca. Cerrar un paso
    // deja al siguiente en "pendiente", no en "cargando", asi que en el
    // instante en que termina la subida todavia no hay ningun paso en curso y
    // un chequeo de "se acabaron?" daria la pantalla por lista antes de que el
    // backend haya leido una sola pagina. El cierre real lo decide la respuesta.
    this.estados.update((estados) => {
      const copia = [...estados];
      copia[indice] = 'completado';
      return copia;
    });
  }

  private iniciarPaso(indice: number): void {
    this.estados.update((estados) => {
      const copia = [...estados];
      if (copia[indice] === 'pendiente') {
        copia[indice] = 'cargando';
      }
      return copia;
    });
  }

  private fallar(indice: number, mensaje: string): void {
    this.errorMensaje.set(mensaje);
    this.estados.update((estados) => {
      const copia = [...estados];
      copia[indice] = 'error';
      // Los pasos que no llegaron a empezar no quedan para siempre en
      // "cargando": se pasan a pendientes para que el stepper no mienta.
      for (let i = indice + 1; i < copia.length; i++) {
        if (copia[i] === 'cargando') {
          copia[i] = 'pendiente';
        }
      }
      return copia;
    });
  }

  private marcarFinalizado(): void {
    if (!this.finalizado()) {
      this.estados.set(['completado', 'completado', 'completado']);
    }
  }

  /** Vuelve a la pantalla de conciliacion sin cargar nada. */
  cancelar(): void {
    this.importacion.limpiar();
    this.router.navigate(['/']);
  }

  /** Reintenta: vuelve a /importar-pdf para elegir el archivo otra vez. */
  reintentar(): void {
    this.importacion.limpiar();
    this.router.navigate(['/importar-pdf']);
  }
}
