import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, output, signal } from '@angular/core';
import { Router } from '@angular/router';

/**
 * Parte 1 del flujo de importación: botón "Importar" con desplegable.
 * - Importar vía Excel  -> elige el archivo y avisa al padre (aún no hay
 *   endpoint de Excel en el backend, así que no se finge una importación).
 * - Importar vía PDF   -> navega a /importar-pdf.
 */
@Component({
  selector: 'app-importar-menu',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './importar-menu.html',
})
export class ImportarMenuComponent {
  /** Se emite cuando el usuario elige un Excel, para que la pantalla avise. */
  readonly excelSeleccionado = output<File>();

  readonly menuAbierto = signal(false);

  constructor(
    private readonly router: Router,
    private readonly host: ElementRef<HTMLElement>,
  ) {}

  /** Abre/cierra el desplegable sin que el click llegue al document. */
  alternarMenu(event: MouseEvent): void {
    event.stopPropagation();
    this.menuAbierto.update((abierto) => !abierto);
  }

  cerrarMenu(): void {
    this.menuAbierto.set(false);
  }

  irAImportarPdf(): void {
    this.cerrarMenu();
    this.router.navigate(['/importar-pdf']);
  }

  elegirExcel(event: Event): void {
    const input = event.target as HTMLInputElement;
    const archivo = input.files?.[0];
    this.cerrarMenu();

    if (archivo) {
      this.excelSeleccionado.emit(archivo);
      // Permite volver a elegir el mismo archivo más tarde.
      input.value = '';
    }
  }

  /** Cierra el popover si el usuario hace clic fuera del componente. */
  @HostListener('document:click', ['$event'])
  onClickFuera(event: MouseEvent): void {
    if (this.menuAbierto() && !this.host.nativeElement.contains(event.target as Node)) {
      this.cerrarMenu();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.cerrarMenu();
  }
}