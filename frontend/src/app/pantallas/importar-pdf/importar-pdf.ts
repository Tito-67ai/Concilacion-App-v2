import { CommonModule } from '@angular/common';
import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { Router } from '@angular/router';
import { ImportacionService } from '../../servicios/importacion.service';

const TAMANO_MAXIMO_MB = 10;
const IMPORTACIONES_RESTANTES = 3;

interface CuentaContable {
  id: string;
  nombre: string;
}

/** TODO: reemplazar por el endpoint de cuentas del backend cuando exista. */
const CUENTAS_CONTABLES: CuentaContable[] = [
  { id: '4301', nombre: '4301 - Clientes' },
  { id: '1101', nombre: '1101 - Caja en pesos' },
  { id: '1105', nombre: '1105 - Banco BBVA - Cuenta 1234' },
  { id: '2011', nombre: '2011 - Proveedores' },
  { id: '4101', nombre: '4101 - Ingresos por servicios' },
];

/** El archivo tiene que ser un PDF y pesar hasta 10 MB. */
function validarPdf(control: AbstractControl<File | null>): ValidationErrors | null {
  const archivo = control.value;

  if (!archivo) {
    return null; // La obligatoriedad la controla Validators.required
  }

  const esPdf = archivo.type === 'application/pdf' || archivo.name.toLowerCase().endsWith('.pdf');
  if (!esPdf) {
    return { formato: true };
  }

  if (archivo.size > TAMANO_MAXIMO_MB * 1024 * 1024) {
    return { tamano: true };
  }

  return null;
}

/**
 * Parte 2 del flujo de importación: pantalla de selección de archivo (/importar-pdf).
 * El botón "Previsualizar importación" se habilita recién cuando hay cuenta + PDF válido.
 */
@Component({
  selector: 'app-importar-pdf',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './importar-pdf.html',
})
export class ImportarPdfComponent {
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly importacion = inject(ImportacionService);

  readonly cuentas = CUENTAS_CONTABLES;
  readonly tamanoMaximo = TAMANO_MAXIMO_MB;
  readonly importacionesRestantes = IMPORTACIONES_RESTANTES;

  /** El input real, para poder vaciarlo cuando el usuario saca el archivo. */
  private readonly archivoInput = viewChild<ElementRef<HTMLInputElement>>('archivoInput');

  readonly formulario = this.fb.group({
    cuentaId: this.fb.control('', {
      nonNullable: true,
      validators: Validators.required,
    }),
    archivo: this.fb.control<File | null>(null, {
      validators: [Validators.required, validarPdf],
    }),
  });

  /** Resalta la zona de carga mientras hay un archivo arrastrado encima. */
  readonly arrastrando = signal(false);

  get cuentaElegida(): CuentaContable | undefined {
    return this.cuentas.find((cuenta) => cuenta.id === this.formulario.controls.cuentaId.value);
  }

  get nombreArchivo(): string | null {
    return this.formulario.controls.archivo.value?.name ?? null;
  }

  get tamanoArchivo(): string | null {
    const archivo = this.formulario.controls.archivo.value;
    return archivo ? this.formatearTamano(archivo.size) : null;
  }

  /** Mensaje de error del archivo, o null si todavía no hay nada que avisar. */
  get errorArchivo(): string | null {
    const control = this.formulario.controls.archivo;

    if (control.hasError('formato')) {
      return 'El archivo tiene que ser un PDF (.pdf).';
    }
    if (control.hasError('tamano')) {
      return `El archivo supera el tamaño máximo de ${this.tamanoMaximo} MB.`;
    }
    if (control.hasError('required') && control.touched) {
      return 'Tenés que adjuntar el PDF del extracto.';
    }

    return null;
  }

  get errorCuenta(): boolean {
    const control = this.formulario.controls.cuentaId;
    return control.invalid && (control.touched || control.dirty);
  }

  /** El CTA se habilita únicamente con cuenta elegida + PDF válido. */
  get habilitado(): boolean {
    return this.formulario.valid;
  }

  abrirSelector(): void {
    this.archivoInput()?.nativeElement.click();
  }

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.formulario.controls.archivo.setValue(input.files?.[0] ?? null);
  }

  alArrastrarSobre(event: DragEvent): void {
    event.preventDefault();
    this.arrastrando.set(true);
  }

  alSalirZona(event: DragEvent): void {
    event.preventDefault();
    this.arrastrando.set(false);
  }

  alSoltar(event: DragEvent): void {
    event.preventDefault();
    this.arrastrando.set(false);
    this.formulario.controls.archivo.setValue(event.dataTransfer?.files?.[0] ?? null);
  }

  cambiarArchivo(event: Event): void {
    event.stopPropagation();
    this.seleccionarArchivo(event);
  }

  quitarArchivo(event: Event): void {
    event.stopPropagation();
    this.formulario.controls.archivo.reset(null);
    this.vaciarInputArchivo();
  }

  previsualizar(): void {
    const archivo = this.formulario.controls.archivo.value;
    const cuenta = this.cuentaElegida;

    if (!archivo || !cuenta) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.importacion.guardar({
      cuentaId: cuenta.id,
      cuentaNombre: cuenta.nombre,
      archivo,
    });

    this.router.navigate(['/procesando-pdf']);
  }

  volver(): void {
    this.router.navigate(['/']);
  }

  private vaciarInputArchivo(): void {
    const input = this.archivoInput();
    if (input) {
      input.nativeElement.value = '';
    }
  }

  private formatearTamano(bytes: number): string {
    const megas = bytes / (1024 * 1024);
    return megas >= 1 ? `${megas.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
}