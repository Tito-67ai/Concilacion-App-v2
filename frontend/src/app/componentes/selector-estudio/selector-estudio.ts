import { CommonModule } from '@angular/common';
import {
  Component,
  ElementRef,
  HostListener,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Estudio, EstudiosService } from '../../servicios/estudios.service';

/** Deja un texto comparable para el buscador: sin acentos ni mayúsculas. */
function normalizar(texto: string): string {
  return (texto ?? '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .trim();
}

/**
 * Selector de Estudio/Empresa de la barra superior.
 *
 * Muestra el estudio elegido y, al abrirse, la lista que bajó el bot de Xubio
 * (todas las empresas de la cuenta logueada). Elegir un estudio NO cambia nada
 * en Xubio: solo deja guardado de qué empresa sale el Libro Mayor.
 *
 * Lee el catálogo al arrancar y lo vuelve a leer cada vez que se abre, así si el
 * usuario acaba de iniciar sesión en otra pantalla ve los estudios nuevos sin
 * recargar la página. "Actualizar desde Xubio" es aparte y corre el bot.
 */
@Component({
  selector: 'app-selector-estudio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './selector-estudio.html',
})
export class SelectorEstudioComponent implements OnInit {
  readonly estudios = inject(EstudiosService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly abierto = signal(false);
  readonly busqueda = signal('');

  readonly filtrados = computed(() => {
    const consulta = normalizar(this.busqueda());
    const lista = this.estudios.estudios();
    if (!consulta) return lista;
    return lista.filter((estudio) => normalizar(estudio.nombre).includes(consulta));
  });

  readonly etiqueta = computed(() => {
    const actual = this.estudios.actual();
    if (actual) return actual.nombre;
    if (this.estudios.cargando()) return 'Cargando estudios…';
    return 'Elegí un estudio';
  });

  ngOnInit(): void {
    this.estudios.cargar();
  }

  alternar(): void {
    const abrir = !this.abierto();
    this.abierto.set(abrir);
    if (abrir) {
      // Refresca al abrir: si la sesión se renovó en otra pantalla, así aparece
      // el catálogo nuevo sin recargar.
      this.busqueda.set('');
      this.estudios.cargar();
    }
  }

  elegir(estudio: Estudio): void {
    this.estudios.elegir(estudio.clave);
    this.abierto.set(false);
  }

  limpiar(evento: Event): void {
    evento.stopPropagation();
    this.estudios.olvidar();
  }

  actualizarDesdeXubio(evento: Event): void {
    evento.stopPropagation();
    this.estudios.sincronizar();
  }

  /** Cierra el desplegable cuando el clic cae fuera del componente. */
  @HostListener('document:click', ['$event'])
  cerrarSiEsAfuera(evento: Event): void {
    if (this.abierto() && !this.host.nativeElement.contains(evento.target as Node)) {
      this.abierto.set(false);
    }
  }
}
