import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { SelectorEstudioComponent } from '../selector-estudio/selector-estudio';

/** Un destino del menú lateral. */
interface ItemNav {
  ruta: string;
  etiqueta: string;
  icono: string;
  /** `true` para el inicio: si no, queda activo en cualquier subruta. */
  exacta?: boolean;
}

/**
 * Marco de la aplicación: barra lateral de navegación + barra superior con el
 * selector de Estudio/Empresa + área de contenido.
 *
 * Reemplaza el viejo diseño "una sola pantalla a lo Xubio": ahora hay un lugar
 * fijo para moverse entre la conciliación y la importación de PDF, y las
 * pantallas viven dentro del área de contenido en vez de ocupar todo el ancho.
 *
 * En pantallas chicas la barra se corre a un panel deslizable con un botón en
 * la barra superior; en escritorio queda fija a la izquierda.
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [
    CommonModule,
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    SelectorEstudioComponent,
  ],
  templateUrl: './shell.html',
})
export class ShellComponent {
  readonly menuAbierto = signal(false);

  readonly items: ItemNav[] = [
    { ruta: '/', etiqueta: 'Conciliación', icono: 'pi pi-sync', exacta: true },
    { ruta: '/importar-pdf', etiqueta: 'Importar PDF', icono: 'pi pi-file-pdf' },
  ];

  alternarMenu(): void {
    this.menuAbierto.update((abierto) => !abierto);
  }

  cerrarMenu(): void {
    this.menuAbierto.set(false);
  }
}
