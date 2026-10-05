import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { catchError, throwError, timeout } from 'rxjs';

const API = 'http://127.0.0.1:8000/api';

// Un PDF de 30 paginas con tablas tarda bastante en pdfplumber. Si no se corta,
// el overlay "Procesando..." queda arriba para siempre cuando algo se rompe en
// el medio y el usuario no tiene forma de saber que paso.
const TIMEOUT_IMPORTACION_MS = 180000;

@Component({
  selector: 'app-conciliacion',
  standalone: true,
  imports: [CommonModule, ImportarMenuComponent],
  templateUrl: './conciliacion.html'
})
export class ConciliacionComponent implements OnInit {
  movimientosBanco: any[] = [];
  movimientosXubio: any[] = [];
  archivoSeleccionado: File | null = null;
  cargando: boolean = false;

  // El backend expone GET /extractos/bancos para que esta lista no viva
  // hardcodeada en el frontend: agregar un banco es cambiar el extractor, no
  // tocar la pantalla.
  bancos: string[] = [];
  bancoSeleccionado: string = '';
  formatos: string[] = [];

  // Errores del backend. Se muestran en pantalla en vez de un alert generico:
  // el backend ya devuelve el motivo real (columnas que no entiende, archivo
  // que no es PDF, etc.) y con un alert "ocurrio un error" eso se pierde.
  errorMensaje: string = '';

  // Estado para controlar qué pestaña está seleccionada (Sin usar la ñ)
  tabActiva: string = 'a_conciliar';

  // Archivo Excel elegido desde el desplegable "Importar". El backend todavía
  // no expone un endpoint de Excel, así que solo mostramos el aviso.
  readonly avisoExcel = signal<File | null>(null);

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.cargarBancos();
  }

  cargarBancos() {
    this.http.get(`${API}/extractos/bancos`).subscribe({
      next: (respuesta: any) => {
        this.bancos = respuesta.bancos ?? [];
        this.formatos = respuesta.formatos ?? [];
        // Preselecciona el primero para no obligar a elegir antes de importar.
        if (this.bancos.length > 0) {
          this.bancoSeleccionado = this.bancos[0];
        }
      },
      error: (error) => {
        console.error("Error cargando los bancos soportados", error);
        this.errorMensaje = this.mensajeDeError(
          error,
          'No se pudieron cargar los bancos soportados. ¿El backend está corriendo en el puerto 8000?'
        );
      }
    });
  }

  cambiarTab(tab: string) {
    this.tabActiva = tab;
  }

  capturarArchivo(event: any) {
    const input = event.target as HTMLInputElement;
    this.archivoSeleccionado = input.files?.[0] ?? null;
    this.errorMensaje = '';

    if (!this.archivoSeleccionado) {
      return;
    }

    this.procesarArchivo();

    // Limpiar el input hace que elegir dos veces el mismo archivo vuelve a
    // disparar el change: sin esto el segundo intento no hace nada y parece que
    // la aplicacion se froze.
    input.value = '';
  }

  procesarArchivo() {
    if (!this.archivoSeleccionado) return;

    const archivo = this.archivoSeleccionado;
    if (!this.bancoSeleccionado) {
      this.errorMensaje = 'Elegí el banco del extracto antes de importar.';
      return;
    }

    this.cargando = true;
    const formData = new FormData();
    formData.append('banco', this.bancoSeleccionado);
    formData.append('archivo', archivo, archivo.name);

    try {
      this.http
        .post(`${API}/extractos/procesar`, formData)
        .pipe(
          timeout(TIMEOUT_IMPORTACION_MS),
          catchError((error) => {
            if (error?.name === 'TimeoutError') {
              error.error = {
                detail:
                  `El backend no respondió en ${TIMEOUT_IMPORTACION_MS / 1000} segundos. ` +
                  'Puede que el PDF sea muy pesado o que un extractor del banco se haya quedado leyendo.',
              };
            }
            return throwError(() => error);
          })
        )
        .subscribe({
          next: (respuesta: any) => {
            this.movimientosBanco = respuesta.datos ?? [];
            this.cargando = false;
            if (this.movimientosBanco.length === 0) {
              this.errorMensaje = `El archivo se leyó pero no tiene movimientos para ${this.bancoSeleccionado}.`;
            }
          },
          error: (error) => {
            console.error("Error procesando el extracto", error);
            this.cargando = false;
            this.movimientosBanco = [];
            this.errorMensaje = this.mensajeDeError(error);
          }
        });
    } catch (e) {
      // Si falla algo antes de salir la request (por ejemplo, si el backend no
      // esta levantado), cargando queda en true y el overlay tapa la pantalla
      // para siempre.
      console.error("No se pudo enviar el extracto", e);
      this.cargando = false;
      this.errorMensaje =
        'No se pudo enviar el archivo al backend. Revisá que FastAPI esté corriendo en el puerto 8000.';
    }
  }

  /**
   * FastAPI manda los motivos en error.detail. A veces es un string y a veces
   * una lista de validación, así que se lee de los dos tamaños.
   */
  mensajeDeError(error: any, porDefecto = 'Ocurrió un error al leer el extracto.'): string {
    const detail = error?.error?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      return detail.map((d: any) => d?.msg ?? JSON.stringify(d)).join('; ');
    }
    return porDefecto;
  }

  ejecutarAutoconciliacion() {
    if (this.movimientosBanco.length === 0) {
      this.errorMensaje = 'Primero tenés que importar un extracto bancario.';
      return;
    }

    this.cargando = true;
    this.http.post(`${API}/xubio/cruzar-datos`, this.movimientosBanco).subscribe({
      next: (respuesta: any) => {
        console.log("Resultado del cruce:", respuesta);
        this.movimientosXubio = respuesta?.movimientos ?? [];
        this.cargando = false;
        alert(`¡Conciliación terminada! Pares encontrados: ${respuesta.resumen.pares_encontrados}`);
      },
      error: (error) => {
        console.error("Error al conciliar", error);
        this.cargando = false;
        this.errorMensaje = this.mensajeDeError(
          error,
          'No se pudo cruzar con Xubio. Revisá las credenciales en el backend.'
        );
      }
    });
  }
}