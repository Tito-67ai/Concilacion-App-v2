import { Component, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { ImportarMenuComponent } from '../../componentes/importar-menu/importar-menu';

@Component({
  selector: 'app-conciliacion',
  standalone: true,
  imports: [CommonModule, ImportarMenuComponent],
  templateUrl: './conciliacion.html'
})
export class ConciliacionComponent {
  movimientosBanco: any[] = [];
  movimientosXubio: any[] = [];
  archivoSeleccionado: File | null = null;
  cargando: boolean = false;

  // Estado para controlar qué pestaña está seleccionada (Sin usar la ñ)
  tabActiva: string = 'a_conciliar';

  // Archivo Excel elegido desde el desplegable "Importar". El backend todavía
  // no expone un endpoint de Excel, así que solo mostramos el aviso.
  readonly avisoExcel = signal<File | null>(null);

  constructor(private http: HttpClient) {}

  cambiarTab(tab: string) {
    this.tabActiva = tab;
  }

  capturarArchivo(event: any) {
    this.archivoSeleccionado = event.target.files[0];
    if (this.archivoSeleccionado) {
      this.procesarPDF();
    }
  }

  procesarPDF() {
    if (!this.archivoSeleccionado) return;
    
    this.cargando = true;
    const formData = new FormData();
    // Por ahora enviamos BBVA fijo, luego lo atamos a tu selector de banco
    formData.append('banco', 'BBVA'); 
    formData.append('archivo', this.archivoSeleccionado);

    this.http.post('http://127.0.0.1:8000/api/extractos/procesar', formData)
      .subscribe({
        next: (respuesta: any) => {
          this.movimientosBanco = respuesta.datos;
          this.cargando = false;
        },
        error: (error) => {
          console.error("Error procesando el PDF", error);
          this.cargando = false;
          alert("Ocurrió un error al leer el PDF.");
        }
      });
  }

  ejecutarAutoconciliacion() {
    if (this.movimientosBanco.length === 0) {
      alert("Primero debes importar un extracto bancario.");
      return;
    }

    this.cargando = true;
    this.http.post('http://127.0.0.1:8000/api/xubio/cruzar-datos', this.movimientosBanco)
      .subscribe({
        next: (respuesta: any) => {
          console.log("Resultado del cruce:", respuesta);
          this.cargando = false;
          alert(`¡Conciliación terminada! Pares encontrados: ${respuesta.resumen.pares_encontrados}`);
        },
        error: (error) => {
          console.error("Error al conciliar", error);
          this.cargando = false;
        }
      });
  }
}