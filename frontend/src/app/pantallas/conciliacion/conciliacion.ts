import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { catchError, throwError, timeout } from 'rxjs';

import { ImportarMenuComponent } from '../../componentes/importar-menu/importar-menu';
import {
  MovimientoBanco,
  MovimientoMayor,
  ParConciliado,
  SolicitudExportacion,
} from '../../modelos/conciliacion';
import { ExportacionService } from '../../servicios/exportacion.service';
import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

// Un Excel de 30.000 filas tarda en pandas. Si no se corta, el overlay
// "Procesando..." queda arriba para siempre cuando algo se rompe en el medio y
// el usuario no tiene forma de saber que paso.
const TIMEOUT_IMPORTACION_MS = 180000;

// De que lado de la pantalla sale o cae una fila en el arrastre manual. El cruce
// manual siempre va de un lado al otro: no tiene sentido soltar una fila del
// banco sobre otra del banco.
export type LadoConciliable = 'banco' | 'xubio';

@Component({
  selector: 'app-conciliacion',
  standalone: true,
  imports: [CommonModule, FormsModule, ImportarMenuComponent],
  templateUrl: './conciliacion.html'
})
export class ConciliacionComponent implements OnInit {
  movimientosBanco: any[] = [];
  archivoSeleccionado: File | null = null;
  cargando: boolean = false;

  // El boton Exportar se pone en guardia mientras se arma el Excel. El tiempo
  // de exportacion depende de la cantidad de filas, no de la de clicks: sin
  // este flag se puede pedir tres veces el mismo archivo.
  exportando: boolean = false;

  // El menu de las dos vias vive en el componente ImportarMenuComponent: la via
  // PDF sale a su propia pantalla (/importar-pdf) y la de tabla entra por el
  // input de archivo de ese menu. El boton "Importar" ya no se dibuja aqui.
  //
  // La via Excel se procesa en esta misma pantalla, sin pantalla intermedia: el
  // archivo se manda apenas se elige y el resultado se ve acá. La via PDF tiene
  // dos pantallas (/importar-pdf y /procesando-pdf) porque necesita pedir banco
  // y cuenta, y mostrar el paso a paso mientras pdfplumber trabaja.

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
  conciliados: ParConciliado[] = [];
  pendientesBanco: MovimientoBanco[] = [];
  pendientesXubio: MovimientoMayor[] = [];

  // El rango de fechas de los filtros. Antes eran dos <input type="date"> con
  // el value puesto en el HTML y sin binding: la pantalla mostraba siempre
  // septiembre de 2026 y lo que el usuario escribiera se perdia. Ahora son las
  // dos cosas, y ademas son de donde sale el periodo del papel de trabajo.
  fechaDesde: string = '';
  fechaHasta: string = '';

  // Estado para controlar qué pestaña está seleccionada (Sin usar la ñ)
  tabActiva: string = 'a_conciliar';

  // Oculta de la bandeja las percepciones y los impuestos del banco.
  //
  // Arranca en true: es decir, se ve todo, como antes. No cambiar lo que se
  // muestra sin que alguien lo pida. Cuando se apaga, las filas de categoria
  // 'percepcion' e 'impuesto' desaparecen de la tabla izquierda.
  mostrarNoOperativas: boolean = true;

  // ------------------------------------------------------------------
  // Conciliacion manual: arrastrar una fila del banco sobre una de Xubio
  //
  // El cruce automatico solo acepta el importe AL CENTIMO (conciliador.py:66) y
  // dentro de 3 dias. Queda todo lo demas para que lo resuelva una persona, y
  // esa persona necesita poder decir "este par es este par" aunque los importes
  // no den exactamente: una perceccion mal imputada, un cheque que el banco
  // partio al cobrar, un ajuste de contabilidad.
  //
  // Por eso el pareo manual no exige que cuadren: avisa si no cuadran y lo deja
  // anotado en el par, para que quede a la vista y no se pierda.
  // ------------------------------------------------------------------

  // La fila que se esta arrastrando, y de que lado salio. Sin esto el drop no
  // sabe que fila se solto: el evento de drop no lo dice.
  filaArrastrada: any = null;
  ladoArrastrado: LadoConciliable | null = null;

  // La fila sobre la que esta el puntero ahora, para pintar el destino. Es
  // distinta de filaArrastrada: una es la que se mueve, esta es la que recibe.
  filaDestino: any = null;

  // Ultimo par manual, para poder deshacerlo. Emparejar a mano se equivoca
  // seguido y sin vuelta atras el error queda en la bandeja para siempre.
  ultimoPareoManual: { banco: any; xubio: any } | null = null;

  /**
   * Solo se arrastra despues de un cruce y mientras se mire la bandeja de
   * pendientes. En la pestana de conciliados no hay nada que emparejar: los
   * pares ya estan armados y se deshacen con el boton de deshacer.
   */
  get puedeArrastrar(): boolean {
    return this.cruceRealizado && this.tabActiva !== 'conciliados';
  }

  /**
   * Un destino valido es la fila pendiente del lado contrario. Una fila del
   * lado del arrastre no es destino: no tiene sentido emparejar banco con banco.
   */
  puedeRecibir(mov: any, lado: LadoConciliable): boolean {
    if (!this.filaArrastrada || !this.puedeArrastrar) return false;
    return this.ladoArrastrado !== lado;
  }

  /** El puntero entro en una fila: se marca como destino. */
  alArrastrarSobreFila(mov: any, lado: LadoConciliable, event: DragEvent) {
    if (!this.puedeRecibir(mov, lado)) return;
    // Sin preventDefault el navegador no deja soltar aca. Ademas el drop es
    // bloqueado: no se quiere arrastrar archivos del escritorio a una fila.
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'move';
    }
    this.filaDestino = mov;
  }

  alArrastrarSalirFila(event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();
    this.filaDestino = null;
  }

  /** Empieza el arrastre de una fila del lado indicado. */
  alArrastrarFila(mov: any, lado: LadoConciliable, event: DragEvent) {
    if (!this.puedeArrastrar) return;

    event.preventDefault();
    this.filaArrastrada = mov;
    this.ladoArrastrado = lado;

    if (event.dataTransfer) {
      // Firefox no arrastra si no hay datos: setData es obligatorio, no
      // decorativo.
      event.dataTransfer.setData('text/plain', mov.concepto ?? '');
      event.dataTransfer.effectAllowed = 'move';
    }
  }

  /** Se solto una fila sobre otra. Empareja las dos y saca ambas de pendientes. */
  alSoltarSobreFila(destino: any, ladoDestino: LadoConciliable, event: DragEvent) {
    event.preventDefault();
    event.stopPropagation();

    const origen = this.filaArrastrada;
    const ladoOrigen = this.ladoArrastrado;

    // Se valida ANTES de limpiar: puedeRecibir mira si hay algo arrastrado, y
    // si se limpiara primero el chequeo daria falso siempre y ningun par se
    // armaria nunca.
    const esValido =
      !!origen && !!destino && ladoOrigen !== ladoDestino && this.puedeRecibir(destino, ladoDestino);

    // Se limpia siempre, acierte o falle el pareo: si el puntero se queda
    // sobre una fila, el renglón queda pintado para siempre.
    this.filaArrastrada = null;
    this.ladoArrastrado = null;
    this.filaDestino = null;

    if (!esValido) return;

    // El que se arrastro puede venir de cualquiera de los dos lados.
    const movBanco = ladoOrigen === 'banco' ? origen : destino;
    const movXubio = ladoOrigen === 'xubio' ? origen : destino;

    this.emparejar(movBanco, movXubio);
  }

  /** El arrastre termino fuera de cualquier fila: se descarta. */
  alTerminarArrastre() {
    this.filaArrastrada = null;
    this.ladoArrastrado = null;
    this.filaDestino = null;
  }

  /**
   * Empareja un movimiento del banco con uno de Xubio y los saca de las dos
   * bandejas de pendientes.
   *
   * El par queda marcado como manual y con la diferencia de importe, para que
   * en la pestana de conciliados se vea que no lo hizo el cruce automatico y por
   * que monto. Sin eso, un par con 200 de diferencia queda igual que uno
   * perfecto y nadie lo vuelve a mirar.
   */
  emparejar(movBanco: any, movXubio: any) {
    const diferencia = this.diferenciaDeImporte(movBanco, movXubio);

    const existeBanco = this.pendientesBanco.includes(movBanco);
    const existeXubio = this.pendientesXubio.includes(movXubio);
    if (!existeBanco || !existeXubio) {
      this.errorMensaje =
        'Uno de los dos movimientos ya no está pendiente, así que no se puede ' +
        'armar el par. Volvé a hacer el cruce.';
      return;
    }

    this.pendientesBanco = this.pendientesBanco.filter((m) => m !== movBanco);
    this.pendientesXubio = this.pendientesXubio.filter((m) => m !== movXubio);

    this.conciliados = [
      ...this.conciliados,
      {
        fecha: movBanco.fecha,
        concepto_banco: movBanco.concepto,
        concepto_xubio: movXubio.concepto,
        debe: movBanco.debe,
        haber: movBanco.haber,
        saldo: movBanco.saldo,
        importe: movBanco.importe,
        categoria: movBanco.categoria,
        // Los campos que el cruce automatico no manda. El frontend los lee
        // con ? y con || justamente por esto: un par automatico no los tiene.
        cuadra: true,
        manual: true,
        diferencia,
      },
    ];

    this.ultimoPareoManual = { banco: movBanco, xubio: movXubio };
    this.errorMensaje = '';

    if (diferencia !== 0) {
      this.infoMensaje =
        `Par manual armado, pero los importes no coinciden: difieren ${diferencia}. ` +
        'Queda anotado en la pestaña de conciliados.';
    } else {
      this.infoMensaje = 'Par manual armado.';
    }
  }

  /** Vuelve el ultimo par manual a las bandejas de pendientes. */
  deshacerPareoManual() {
    const ultimo = this.ultimoPareoManual;
    if (!ultimo) return;

    this.conciliados = this.conciliados.filter((m) => !m.manual);
    this.pendientesBanco = [...this.pendientesBanco, ultimo.banco];
    this.pendientesXubio = [...this.pendientesXubio, ultimo.xubio];
    this.ultimoPareoManual = null;
    this.infoMensaje = 'Se deshizo el último par manual.';
  }

  /**
   * Diferencia de importe entre las dos filas, con signo, o 0 si cuadran.
   *
   * Se comparan los importes con signo y no debe/haber: las dos columnas por
   * separado no son comparables (un ingreso del banco es un DEBE del Xubio, y
   * viceversa), y eso ya lo tiene en cuenta el backend al unificar el signo.
   */
  diferenciaDeImporte(movBanco: any, movXubio: any): number {
    const banco = Number(movBanco?.importe ?? 0);
    const xubio = Number(movXubio?.importe ?? 0);
    const diferencia = Math.round((banco - xubio) * 100) / 100;
    return diferencia;
  }

  constructor(
    private http: HttpClient,
    private importacion: ImportacionService,
    private exportacion: ExportacionService,
  ) {}

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

  /**
   * Como se muestra un importe en la pantalla.
   *
   * Va con toLocaleString y no con el numero crudo: un saldo de 1234567.89
   * pegado en la celda es ilegible, y la idea de la conciliacion es que alguien
   * lo revise con los numeros a la vista. El signo va siempre adelante para que
   * un negativo se distinga de un positivo de un vistazo.
   */
  formatoImporte(valor: number | null | undefined): string {
    const numero = Number(valor ?? 0);
    if (!numero) return '';
    const signo = numero < 0 ? '-' : '';
    return signo + Math.abs(numero).toLocaleString('es-AR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  get totalConciliables(): number {
    return this.cruceRealizado ? this.pendientesBanco.length : this.movimientosBanco.length;
  }

  /**
   * Los pares armados a mano, para el filtro de la pestana de conciliados.
   *
   * El cruce automatico no manda estos campos, asi que se leen con truthy y no
   * con === true: los pares del backend tienen que contar como automaticos.
   */
  get paresManuales(): any[] {
    return this.conciliados.filter((m) => m.manual);
  }

  /** Solo los pares automaticos. El complemento de paresManuales. */
  get paresAutomaticos(): any[] {
    return this.conciliados.filter((m) => !m.manual);
  }

  // ------------------------------------------------------------------
  // Importar: la via Excel entra por el menu, la PDF va a su pantalla
  // ------------------------------------------------------------------

  /**
   * Llego desde /procesando-pdf con los movimientos ya leidos.
   *
   * El flujo del PDF vive en sus propias dos pantallas, asi que al volver a la
   * conciliacion no hay request que hacer: los movimientos vinieron en el
   * servicio. Si vinieran vacios no se dice nada, porque entrar a '/' a mano
   * tambien es una forma valida de llegar.
   */
  ngOnInit() {
    this.cargarBancos();

    const delFlujo = this.importacion.movimientos();
    if (delFlujo.length > 0) {
      this.movimientosBanco = delFlujo;
      // El servicio se vacia despues de tomar los movimientos: si no, al
      // recargar la pagina volverian a aparecer solos, sin que nadie los haya
      // importado en esta sesion.
      this.importacion.limpiar();
      this.infoMensaje = `Se leyeron ${delFlujo.length} movimientos.`;
    }
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

  /**
   * Eligio un Excel en el menu de Importar: se procesa acá mismo.
   *
   * No hay pantalla intermedia para esta via a proposito: el archivo se manda
   * apenas se elige y el resultado se ve en esta misma pantalla. La via PDF si
   * tiene (/importar-pdf y /procesando-pdf) porque necesita pedir banco y
   * cuenta, y porque un PDF de 30 paginas tarda lo suficiente como para que
   * haga falta ver que esta pasando.
   */
  importarExcel(archivo: File) {
    this.archivoSeleccionado = archivo;
    this.procesarTabla(archivo);
  }

  /**
   * Chequea la extension antes de mandarla al backend.
   *
   * El backend ya responde con un 400 claro si el formato no es el, pero esperar
   * el viaje entero para que la pantalla diga "formato no soportado" es una
   * espera que no aporta nada: el usuario ya sabe que eligio mal.
   */
  private validarExtension(archivo: File): string | null {
    const punto = archivo.name.lastIndexOf('.');
    const extension = punto >= 0 ? archivo.name.slice(punto).toLowerCase() : '';
    const aceptadas = ['.xlsx', '.xls', '.csv'];

    if (!aceptadas.includes(extension)) {
      return (
        `La vía Excel o CSV acepta .xlsx, .xls y .csv, y "${archivo.name}" no es ` +
        'ninguno de esos. Si lo tenés como PDF, usá la vía PDF.'
      );
    }

    return null;
  }

  /** Un extracto nuevo invalida el cruce anterior. */
  private limpiarCruceAnterior() {
    this.cruceRealizado = false;
    this.conciliados = [];
    this.pendientesBanco = [];
    this.pendientesXubio = [];
    this.tabActiva = 'a_conciliar';
    this.ultimoPareoManual = null;
  }

  procesarTabla(archivo: File) {
    const problema = this.validarExtension(archivo);
    if (problema) {
      this.errorMensaje = problema;
      this.archivoSeleccionado = null;
      return;
    }

    this.cargando = true;
    this.errorMensaje = '';
    this.infoMensaje = '';

    const formData = new FormData();
    // En la via tabla el banco no elige extractor: las columnas se reconocen por
    // el encabezado del archivo (importador_tablas.py:150) y el banco solo queda
    // como etiqueta en los logs. Va GENERICO porque es lo que el backend acepta
    // sin intentar adivinar un parser de PDF.
    formData.append('banco', 'GENERICO');
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
            this.limpiarCruceAnterior();

            if (this.movimientosBanco.length === 0) {
              this.errorMensaje = `El archivo se leyó pero no tiene movimientos.`;
              return;
            }

            this.infoMensaje = `Se leyeron ${this.movimientosBanco.length} movimientos.`;
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

  // ------------------------------------------------------------------
  // Exportar: el papel de trabajo FO 02-03
  // ------------------------------------------------------------------

  /**
   * Que se puede exportar ahora mismo.
   *
   * Antes del cruce solo hay un extracto del lado del banco: no se puede llamar
   * a eso conciliacion, asi que el boton avisa por que no hace nada en vez de
   * bajar un archivo vacio que parece un error.
   */
  get puedeExportar(): boolean {
    return !this.exportando && this.tieneAlgoParaExportar;
  }

  /** Lo mismo, pero para el *ngIf del aviso que explica el boton apagado. */
  tieneAlgoQueExportar(): boolean {
    return this.tieneAlgoParaExportar;
  }

  private get tieneAlgoParaExportar(): boolean {
    return (
      this.conciliados.length > 0 ||
      this.pendientesBanco.length > 0 ||
      this.pendientesXubio.length > 0
    );
  }

  get motivoExportBloqueado(): string {
    if (!this.tieneAlgoParaExportar) {
      return 'Todavía no hay una conciliación para exportar. Importá un extracto y hacé el cruce primero.';
    }
    return '';
  }

  /**
   * Arma el payload del papel de trabajo.
   *
   * Va con el estado de las tres bandejas, no con un cruce nuevo: el archivo
   * tiene que mostrar lo que el usuario acaba de revisar en pantalla,
   * incluyendo los pares que emparejo a mano, de los que el backend no sabe
   * nada porque nunca los vio.
   */
  payloadDeExportacion(): SolicitudExportacion {
    return {
      conciliados: this.conciliados,
      pendientes_banco: this.pendientesBanco,
      pendientes_xubio: this.pendientesXubio,
      encabezado: this.encabezadoDelPapel(),
    };
  }

  /**
   * Los cuatro campos del membrete.
   *
   * La cuenta no viene de ningun lado: en esta pantalla el selector de cuenta
   * todavia esta deshabilitado porque no hay endpoint de cuentas. Se manda la
   * cuenta del flujo de importacion si todavia la hay, y si no queda vacio
   * para que el papel salga con el campo sin completar y se note.
   */
  encabezadoDelPapel(): SolicitudExportacion['encabezado'] {
    const seleccion = this.importacion.seleccion();
    const desde = this.fechaFiltroDesde();
    const hasta = this.fechaFiltroHasta();

    return {
      // El nombre de la empresa no esta en ningun lado todavia: el backend no
      // tiene endpoint y no hay dato hardcodeado. Sale vacio a proposito, mejor
      // que inventar un nombre en un papel de trabajo firmado.
      empresa: '',
      banco: this.bancoSeleccionado || seleccion?.banco || '',
      numeroCuenta: seleccion?.cuentaId ?? '',
      // El periodo sale del rango de fechas de los filtros, que es lo unico
      // que el usuario controla en pantalla. Si no hay fechas, no se inventa.
      periodo: desde && hasta ? `${desde.slice(0, 7)}` : null,
    };
  }

  private fechaFiltroDesde(): string {
    return this.fechaDesde.trim();
  }

  private fechaFiltroHasta(): string {
    return this.fechaHasta.trim();
  }

  /**
   * Pide el papel de trabajo y lo baja.
   *
   * El Excel lo arma el backend: lo que viaja es el estado de las bandejas.
   */
  exportarPapelDeTrabajo() {
    if (this.exportando) return;
    if (!this.tieneAlgoParaExportar) {
      this.errorMensaje = this.motivoExportBloqueado;
      this.infoMensaje = '';
      return;
    }

    this.exportando = true;
    this.errorMensaje = '';
    this.infoMensaje = '';

    this.exportacion.exportarYDescargar(this.payloadDeExportacion()).subscribe({
      next: () => {
        this.exportando = false;
        this.infoMensaje =
          `Se exportó el papel de trabajo con ${this.conciliados.length} conciliados, ` +
          `${this.pendientesBanco.length} pendientes del banco y ` +
          `${this.pendientesXubio.length} pendientes de Xubio.`;
      },
      error: (error) => {
        console.error('Error exportando el papel de trabajo', error);
        this.exportando = false;
        // El mensaje se resuelve despues porque con responseType 'blob' el
        // motivo del backend hay que leerlo del blob.
        this.exportacion.mensajeDeError(error).then((mensaje) => {
          this.errorMensaje = mensaje;
        });
      },
    });
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
          // Los pares que manda el backend son todos automaticos. Si no se
          // limpiaran los flags, el filtro de "solo manuales" de la pestana de
          // conciliados no tendria con que trabajar despues de un cruce nuevo,
          // y el papel de trabajo los marcaria como hechos a mano.
          for (const par of this.conciliados) {
            delete par.manual;
            delete par.diferencia;
          }
        this.cruceRealizado = true;
        this.cargando = false;
        this.tabActiva = 'a_conciliar';
        // Un cruce nuevo borra los pares manuales anteriores:-salieron de las
        // bandejas que este cruce recien creo, asi que sin esto "deshacer"
        // intentaria devolver filas que ya no existen.
        this.ultimoPareoManual = null;
        this.alTerminarArrastre();

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