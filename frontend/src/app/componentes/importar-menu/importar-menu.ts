import { CommonModule } from '@angular/common';
import { Component, ElementRef, HostListener, inject, output, signal } from '@angular/core';
import { Router } from '@angular/router';

/**
 * Parte 1 del flujo de importacion: el boton "Importar" con su desplegable.
 *
 * Las dos vias van a extractores distintos del backend (POST /extractos/procesar
 * deriva por extension) y fallan por motivos distintos, asi que no se unifican
 * en una sola pantalla: el PDF tiene una pantalla propia con la cuenta y el
 * banco, y el Excel entra por el input de archivo y se procesa en el lugar.
 */
@Component({
  selector: 'app-importar-menu',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './importar-menu.html',
})
export class ImportarMenuComponent {
  /** Se emite cuando se elige un Excel, para que la pantalla lo procese. */
  readonly excelSeleccionado = output<File>();

  readonly menuAbierto = signal(false);

  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);

  /**
   * Abre y cierra el menu sin que el click siga hasta el document, que lo
   * cerraria en el mismo gesto y no se veria abrir.
   */
  alternarMenu(event: MouseEvent): void {
    event.stopPropagation();
    this.menuAbierto.update((abierto) => !abierto);
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
      // Vacia el input para que elegir dos veces el mismo archivo vuelva a
      // disparar el change. Sin esto el segundo intento no hace nada.
      input.value = '';
    }
  }

  /** Cierra el popover si se hace clic fuera del componente. */
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

  private cerrarMenu(): void {
    this.menuAbierto.set(false);
  }
}
