import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { Component, ElementRef, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';

import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

const TAMANO_MAXIMO_MB = 10;
const IMPORTACIONES_RESTANTES = 3;

interface CuentaContable {
  id: string;
  nombre: string;
}

/**
 * Cuentas contables de ejemplo.
 *
 * El backend no tiene endpoint de cuentas: app/db/session.py esta vacio y no
 * hay donde leerlas. Cuando exista, esta lista se reemplaza por la llamada y
 * esto desaparece. Mientras tanto son fijas y la eleccion no se guarda en
 * ningun lado, asi que el nombre de la cuenta es solo una etiqueta para el
 * usuario.
 */
const CUENTAS_CONTABLES: CuentaContable[] = [
  { id: '4301', nombre: '4301 - Clientes' },
  { id: '1101', nombre: '1101 - Caja en pesos' },
  { id: '1105', nombre: '1105 - Banco BBVA - Cuenta 1234' },
  { id: '2011', nombre: '2011 - Proveedores' },
  { id: '4101', nombre: '4101 - Ingresos por servicios' },
];

/**
 * El archivo tiene que ser un PDF de verdad y pesar hasta 10 MB.
 *
 * El chequeo del tipo declarado del navegador no alcanza: un .pdf renombrado
 * desde un .txt llega con type application/pdf y el backend lo rechaza con un
 * 400 al leer los bytes (extractos.py:44). Este validador ataja el caso obvio
 * antes de gastar el viaje, no reemplaza al del backend.
 */
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
 * Parte 2 del flujo de importacion: pantalla de seleccion de archivo
 * (/importar-pdf).
 *
 * El boton "Previsualizar importacion" se habilita recien cuando hay cuenta,
 * banco y un PDF valido. No hace la previsualizacion: guarda la seleccion y
 * navega a /procesando-pdf, que es la que de verdad llama al backend.
 */
@Component({
  selector: 'app-importar-pdf',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './importar-pdf.html',
})
export class ImportarPdfComponent {
  readonly cuentas = CUENTAS_CONTABLES;
  readonly tamanoMaximo = TAMANO_MAXIMO_MB;
  readonly importacionesRestantes = IMPORTACIONES_RESTANTES;

  /**
   * Los bancos salen del backend (GET /extractos/bancos) y no de una lista
   * escrita aca: agregar un extractor es cambiar el backend, no este archivo.
   */
  readonly bancos = signal<string[]>([]);
  readonly errorBancos = signal('');

  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);
  private readonly http = inject(HttpClient);
  private readonly importacion = inject(ImportacionService);

  /** El input real, para poder vaciarlo cuando el usuario saca el archivo. */
  private readonly archivoInput = viewChild<ElementRef<HTMLInputElement>>('archivoInput');

  readonly formulario = this.fb.group({
    cuentaId: this.fb.control('', { nonNullable: true, validators: Validators.required }),
    banco: this.fb.control('', { nonNullable: true, validators: Validators.required }),
    archivo: this.fb.control<File | null>(null, {
      validators: [Validators.required, validarPdf],
    }),
  });

  /** Resalta la zona de carga mientras hay un archivo arrastrado encima. */
  readonly arrastrando = signal(false);

  constructor() {
    this.cargarBancos();
  }

  private cargarBancos(): void {
    this.http.get(`${API}/extractos/bancos`).subscribe({
      next: (respuesta: any) => {
        const bancos: string[] = respuesta?.bancos ?? [];
        this.bancos.set(bancos);
        // Se preselecciona el primero: preguntar algo que no cambia el
        // resultado es ruido. El generico va al final asi que el banco queda
        // arriba y el extractor de verdad es el que se elige.
        const preferred = bancos.find((banco) => banco !== 'GENERICO');
        if (preferred) {
          this.formulario.controls.banco.setValue(preferred);
        }
      },
      error: () => {
        // Sin la lista de bancos no se puede procesar: el backend no adivina
        // que extractor usar. Se avisa en la pantalla en vez de fallar despues
        // al procesar, donde el motivo seria mas dificil de entender.
        this.errorBancos.set(
          'No se pudieron cargar los bancos soportados. Revisá que el backend ' +
            'esté corriendo en el puerto 8000.',
        );
      },
    });
  }

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

  /** Mensaje de error del archivo, o null si todavia no hay nada que avisar. */
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

  get errorBanco(): boolean {
    const control = this.formulario.controls.banco;
    return control.invalid && (control.touched || control.dirty);
  }

  /** El CTA se habilita unicamente con cuenta + banco + PDF valido. */
  get habilitado(): boolean {
    return this.formulario.valid && this.bancos().length > 0;
  }

  abrirSelector(): void {
    this.archivoInput()?.nativeElement.click();
  }

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.formulario.controls.archivo.setValue(input.files?.[0] ?? null);
  }

  alArrastrarSobre(event: DragEvent): void {
    // Sin preventDefault el navegador abre el PDF en otra pestaña y la pantalla
    // no hace nada.
    event.preventDefault();
    event.stopPropagation();
    this.arrastrando.set(true);
  }

  alSalirZona(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
    this.arrastrando.set(false);
  }

  alSoltar(event: DragEvent): void {
    event.preventDefault();
    event.stopPropagation();
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
    const banco = this.formulario.controls.banco.value;

    if (!archivo || !cuenta || !banco) {
      this.formulario.markAllAsTouched();
      return;
    }

    this.importacion.guardar({
      cuentaId: cuenta.id,
      cuentaNombre: cuenta.nombre,
      banco,
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
