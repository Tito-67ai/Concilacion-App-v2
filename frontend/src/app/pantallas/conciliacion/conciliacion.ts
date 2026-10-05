import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { catchError, throwError, timeout } from 'rxjs';

const API = 'http://127.0.0.1:8000/api';

// Un PDF de 30 paginas con tablas tarda bastante en pdfplumber. Si no se corta,
// el overlay "Procesando..." queda arriba para siempre cuando algo se rompe en el
// medio y el usuario no tiene forma de saber que paso.
const TIMEOUT_IMPORTACION_MS = 180000;

// Las dos vias de entrada. No es decorativo: cada una va a un extractor distinto
// del backend (/extractos/procesar deriva por extension) y falla por motivos
// distintos, asi que la pantalla tiene que poder distinguirlas.
export type ModoImportacion = 'pdf' | 'tabla';

interface OpcionImportacion {
  modo: ModoImportacion;
  titulo: string;
  acepta: string;
  detalle: string;
  icono: string;
}

@Component({
  selector: 'app-conciliacion',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './conciliacion.html'
})
export class ConciliacionComponent implements OnInit {
  movimientosBanco: any[] = [];
  archivoSeleccionado: File | null = null;
  cargando: boolean = false;

  // Importar: menu con las dos vias, y el apartado de carga al que lleva cada
  // una. Con null se ve la pantalla normal de conciliacion.
  readonly opcionesImportacion: OpcionImportacion[] = [
    {
      modo: 'pdf',
      titulo: 'Vía PDF',
      acepta: '.pdf',
      detalle: 'El extracto que descargas del portal del banco.',
      icono: 'pi-file-pdf'
    },
    {
      modo: 'tabla',
      titulo: 'Vía Excel o CSV',
      acepta: '.xlsx,.xls,.csv',
      detalle: 'El detalle de movimientos exportado como tabla.',
      icono: 'pi-table'
    }
  ];

  menuImportarAbierto: boolean = false;
  modoImportacion: ModoImportacion | null = null;
  arrastrandoArchivo: boolean = false;

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
  infoMensaje: string = '';

  // Las tres bandejas que devuelve POST /xubio/cruzar-datos. El nombre de la
  // clave importa: el backend responde {exito, resumen, tablas:{...}}, no
  // "movimientos". Leer una clave que no existe deja la tabla vacia sin avisar.
  cruceRealizado: boolean = false;
  conciliados: any[] = [];
  pendientesBanco: any[] = [];
  pendientesXubio: any[] = [];

  // Estado para controlar qué pestaña está seleccionada (Sin usar la ñ)
  tabActiva: string = 'a_conciliar';

  // Oculta de la bandeja las percepciones y los impuestos del banco.
  //
  // Arranca en true: es decir, se ve todo, como antes. No cambiar lo que se
  // muestra sin que alguien lo pida. Cuando se apaga, las filas de categoria
  // 'percepcion' e 'impuesto' desaparecen de la tabla izquierda.
  mostrarNoOperativas: boolean = true;

  constructor(private http: HttpClient) {}

  // Que se muestra en la columna izquierda. Antes del cruce es el extracto
  // importado; después son los pendientes, o los pares si la pestaña activa es
  // la de conciliados.
  get filasBanco(): any[] {
    if (!this.cruceRealizado) {
      return this.movimientosBanco;
    }
    return this.tabActiva === 'conciliados'
      ? this.conciliados.map((m) => ({ ...m, concepto: m.concepto_banco }))
      : this.pendientesBanco;
  }

  get filasXubio(): any[] {
    if (!this.cruceRealizado) {
      return [];
    }
    return this.tabActiva === 'conciliados'
      ? this.conciliados.map((m) => ({ ...m, concepto: m.concepto_xubio }))
      : this.pendientesXubio;
  }

  /**
   * Las percepciones y los impuestos que se ocultan con el toggle. No son
   * operaciones de la empresa: la plata retenida se gira a ARCA y el impuesto lo
   * cobra el banco por sus comisiones. Casi nunca encuentran su par en Xubio,
   * asi que solo ensucian la bandeja de pendientes.
   *
   * Ojo con el `!m.categoria`: las filas sin categoria (un backend viejo que no
   * manda el campo, o las que vienen del cruce) se muestran siempre. Unknown
   * no se esconde: esconder por no saber seria justo el error que este filtro
   * no tiene que cometer.
   */
  get filasBancoVisibles(): any[] {
    if (this.mostrarNoOperativas) {
      return this.filasBanco;
    }
    return this.filasBanco.filter((m) => !m.categoria || m.categoria === 'operativo');
  }

  /** Cuantas de las filas visibles serian percepcion o impuesto. Para el badge. */
  get totalNoOperativas(): number {
    return this.filasBanco.filter((m) => m.categoria === 'percepcion' || m.categoria === 'impuesto')
      .length;
  }

  etiquetaCategoria(categoria: string | null | undefined): string {
    if (categoria === 'percepcion') return 'Percepción';
    if (categoria === 'impuesto') return 'Impuesto';
    return '';
  }

  get totalConciliables(): number {
    return this.cruceRealizado ? this.pendientesBanco.length : this.movimientosBanco.length;
  }

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

  // ------------------------------------------------------------------
  // Importar: elegir la via y cargar el archivo
  // ------------------------------------------------------------------

  get opcionActiva(): OpcionImportacion | null {
    return this.opcionesImportacion.find((o) => o.modo === this.modoImportacion) ?? null;
  }

  get enApartadoDeImportacion(): boolean {
    return this.modoImportacion !== null;
  }

  alternarMenuImportar() {
    this.menuImportarAbierto = !this.menuImportarAbierto;
  }

  /** Entra al apartado de carga de la via elegida. */
  elegirModo(modo: ModoImportacion) {
    this.modoImportacion = modo;
    this.menuImportarAbierto = false;
    this.errorMensaje = '';
    this.infoMensaje = '';
    this.archivoSeleccionado = null;
  }

  /** Vuelve a la pantalla de conciliacion sin cargar nada. */
  cerrarApartadoImportacion() {
    this.modoImportacion = null;
    this.menuImportarAbierto = false;
    this.archivoSeleccionado = null;
    this.arrastrandoArchivo = false;
    this.errorMensaje = '';
    this.infoMensaje = '';
  }

  /**
   * Chequea la extension antes de mandarlo al backend.
   *
   * El backend ya responde con un 400 claro si el formato no es el, pero esperar
   * el viaje entero para que la pantalla diga "formato no soportado" es una
   * espera que no aporta nada: el usuario ya sabe que eligio mal.
   */
  private validarExtension(archivo: File): string | null {
    const opcion = this.opcionActiva;
    if (!opcion) return null;

    const punto = archivo.name.lastIndexOf('.');
    const extension = punto >= 0 ? archivo.name.slice(punto).toLowerCase() : '';

    if (!opcion.acepta.split(',').includes(extension)) {
      if (this.modoImportacion === 'pdf') {
        return `Un extracto por PDF tiene que ser un archivo .pdf y "${archivo.name}" no lo es. Si lo tenés como tabla, usá la vía Excel o CSV.`;
      }
      return `La vía Excel o CSV acepta .xlsx, .xls y .csv, y "${archivo.name}" no es ninguno de esos. Si lo tenés como PDF, usá la vía PDF.`;
    }
    return null;
  }

  /** Un solo camino para los dos ejemplos de elegir archivo: click o arrastre. */
  private recibirArchivo(archivo: File | null) {
    if (!archivo) return;

    const problema = this.validarExtension(archivo);
    if (problema) {
      this.errorMensaje = problema;
      this.archivoSeleccionado = null;
      return;
    }

    this.archivoSeleccionado = archivo;
    this.errorMensaje = '';
    this.infoMensaje = '';

    // Un extracto nuevo invalida el cruce anterior: si no, la pantalla sigue
    // mostrando los pendientes del extracto anterior con el nuevo cargado.
    this.cruceRealizado = false;
    this.conciliados = [];
    this.pendientesBanco = [];
    this.pendientesXubio = [];
    this.tabActiva = 'a_conciliar';
  }

  capturarArchivo(event: any) {
    const input = event.target as HTMLInputElement;
    this.recibirArchivo(input.files?.[0] ?? null);

    // Limpiar el input hace que elegir dos veces el mismo archivo vuelva a
    // disparar el change: sin esto el segundo intento no hace nada y parece que
    // la aplicacion se froze.
    input.value = '';
  }

  alArrastrarSobre(event: DragEvent) {
    // Solo se usa para el resaltado: sin preventDefault el navegador abre el
    // archivo en otra pestaña y te deja la pantalla sin hacer nada.
    event.preventDefault();
    event.stopPropagation();
    if (!this.cargando) {
      this.arrastrandoArchivo = true;
    }
  }

  alArrastrarSalir(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.arrastrandoArchivo = false;
  }

  alSoltarArchivo(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.arrastrandoArchivo = false;
    if (this.cargando) return;

    const archivos = event.dataTransfer?.files;
    this.recibirArchivo(archivos?.[0] ?? null);
  }

  procesarArchivo() {
    if (!this.archivoSeleccionado) return;

    const archivo = this.archivoSeleccionado;
    // El banco elige el extractor del PDF, asi que sin el no se puede leer.
    // En la via tabla no hace falta: ahi las columnas se reconocen por el
    // encabezado del archivo y el banco solo queda como etiqueta en los logs
    // del backend. Preguntar algo que no va a cambiar el resultado es ruido.
    if (this.modoImportacion !== 'tabla' && !this.bancoSeleccionado) {
      this.errorMensaje = 'Elegí el banco del extracto antes de importar.';
      return;
    }

    this.cargando = true;
    this.errorMensaje = '';
    const formData = new FormData();
    formData.append('banco', this.bancoSeleccionado || 'GENERICO');
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
              return;
            }
            // Salimos del apartado de importacion: ya hay movimientos para
            // conciliar y quedarse en la pantalla de carga solo confunde.
            this.cerrarApartadoImportacion();
            const leidoDe = respuesta.banco ? ` de ${respuesta.banco}` : '';
            this.infoMensaje = `Se leyeron ${this.movimientosBanco.length} movimientos${leidoDe}.`;
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
    this.errorMensaje = '';
    this.infoMensaje = '';

    this.http.post(`${API}/xubio/cruzar-datos`, this.movimientosBanco).subscribe({
      next: (respuesta: any) => {
        // El backend devuelve {exito, resumen, tablas:{conciliados,
        // pendientes_banco, pendientes_xubio}}. Leer respuesta.movimientos
        // devolvia undefined y dejaba la columna derecha siempre vacia.
        const tablas = respuesta?.tablas ?? {};
        this.conciliados = tablas.conciliados ?? [];
        this.pendientesBanco = tablas.pendientes_banco ?? [];
        this.pendientesXubio = tablas.pendientes_xubio ?? [];
        this.cruceRealizado = true;
        this.cargando = false;
        this.tabActiva = 'a_conciliar';

        // El conteo sale de las propias bandejas y no de "resumen" para que no
        // puedan discordar entre si.
        this.infoMensaje =
          `Conciliación terminada: ${this.conciliados.length} pares encontrados, ` +
          `${this.pendientesBanco.length} del banco sin cruce y ` +
          `${this.pendientesXubio.length} de Xubio sin cruce.`;
      },
      error: (error) => {
        console.error("Error al conciliar", error);
        this.cargando = false;
        this.cruceRealizado = false;
        this.errorMensaje = this.mensajeDeError(
          error,
          'No se pudo cruzar con Xubio. Revisá las credenciales en el backend.'
        );
      }
    });
  }
}