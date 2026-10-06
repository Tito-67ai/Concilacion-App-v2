import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { ConciliacionComponent } from './conciliacion';
import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

describe('ConciliacionComponent', () => {
  let component: ConciliacionComponent;
  let fixture: ComponentFixture<ConciliacionComponent>;
  let http: HttpTestingController;
  let importacion: ImportacionService;

  /** Arma un File con el nombre que se le pida (el constructor no acepta props). */
  function archivoConNombre(nombre: string): File {
    return new File([new Uint8Array([80, 75, 3, 4])], nombre);
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConciliacionComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([])
      ]
    }).compileComponents();

    importacion = TestBed.inject(ImportacionService);
    importacion.limpiar();
    fixture = TestBed.createComponent(ConciliacionComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    await fixture.whenStable();
    // El componente pide la lista de bancos al arrancar.
    http.expectOne(`${API}/extractos/bancos`).flush({
      bancos: ['SANT', 'ICBC', 'GENERICO'],
      formatos: ['pdf', 'tabla']
    });
  });

  afterEach(() => http.verify());

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ------------------------------------------------------------------
  // Importar: el boton que ofrece las dos vias es del ImportarMenuComponent
  // ------------------------------------------------------------------

  it('el boton Importar muestra las dos vias en pantalla', async () => {
    expect(clickEnTexto('Importar')).toBe(true);
    await fixture.whenStable();

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Importar vía Excel');
    expect(texto).toContain('Importar vía PDF');
  });

  it('elegir la via PDF sale a su propia pantalla, no procesa acá', async () => {
    const navegar = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    await abrirMenuImportar();
    expect(clickEnTexto('Importar vía PDF')).toBe(true);
    await fixture.whenStable();

    expect(navegar).toHaveBeenCalledWith(['/importar-pdf']);
    // No se manda nada al backend desde la conciliacion en esta via.
    http.expectNone(`${API}/extractos/procesar`);
  });

  it('el input de Excel acepta solo los tres formatos de tabla', async () => {
    await abrirMenuImportar();
    const input = fixture.nativeElement.querySelector('#importarExcel');
    expect(input.getAttribute('accept')).toBe('.xlsx,.xls,.csv');
  });

  it('elegir un Excel lo manda al backend con GENERICO y sin pedir banco', async () => {
    await abrirMenuImportar();
    const input = fixture.nativeElement.querySelector('#importarExcel');
    Object.defineProperty(input, 'files', {
      value: [archivoConNombre('julio.xlsx')],
      // configurable: el TestBed reutiliza el elemento raiz entre tests, y sin
      // esto el segundo test que redefine "files" revienta.
      configurable: true,
    });
    input.dispatchEvent(new Event('change'));

    const req = http.expectOne(`${API}/extractos/procesar`);
    // Ahi las columnas se reconocen por el encabezado: el banco no cambia el
    // resultado, solo aparece en los logs del backend.
    expect(req.request.body.get('banco')).toBe('GENERICO');
    expect(req.request.body.get('archivo') instanceof File).toBe(true);
    req.flush({ exito: true, banco: 'GENERICO', datos: [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }] });

    await fixture.whenStable();
    expect(component.movimientosBanco.length).toBe(1);
    expect(component.infoMensaje).toContain('1 movimientos');
  });

  it('un Excel con otra extension no sale al backend', async () => {
    component.importarExcel(archivoConNombre('julio.pdf'));

    http.expectNone(`${API}/extractos/procesar`);
    expect(component.errorMensaje).toContain('julio.pdf');
    expect(component.movimientosBanco.length).toBe(0);
  });

  it('un Excel sin movimientos avisa y no deja la pantalla en cargado', async () => {
    component.importarExcel(archivoConNombre('julio.csv'));
    http.expectOne(`${API}/extractos/procesar`).flush({ exito: true, banco: 'GENERICO', datos: [] });

    expect(component.cargando).toBe(false);
    expect(component.errorMensaje).toContain('no tiene movimientos');
    expect(component.infoMensaje).toBe('');
  });

  it('si el backend cae se muestra el motivo, no queda cargado para siempre', async () => {
    component.importarExcel(archivoConNombre('julio.xlsx'));
    http.expectOne(`${API}/extractos/procesar`).flush(
      { detail: 'El archivo no tiene tablas legibles.' },
      { status: 422, statusText: 'Unprocessable Entity' }
    );

    expect(component.cargando).toBe(false);
    expect(component.errorMensaje).toContain('no tiene tablas legibles');
    expect(component.movimientosBanco).toEqual([]);
  });

  it('leer un Excel nuevo borra el cruce anterior', async () => {
    component.cruceRealizado = true;
    component.conciliados = [
      {
        fecha: '2026-07-01',
        concepto_banco: 'X',
        concepto_xubio: 'Y',
        debe: 1,
        haber: 0,
        saldo: 1,
        importe: -1,
        manual: true,
      },
    ];
    component.ultimoPareoManual = { banco: {}, xubio: {} };

    component.importarExcel(archivoConNombre('agosto.xlsx'));
    http.expectOne(`${API}/extractos/procesar`).flush({
      exito: true,
      banco: 'GENERICO',
      datos: [{ fecha: '2026-08-01', concepto: 'Y', debe: 2, haber: 0, saldo: 2 }],
    });

    expect(component.cruceRealizado).toBe(false);
    expect(component.conciliados).toEqual([]);
    expect(component.ultimoPareoManual).toBeNull();
  });

  // ------------------------------------------------------------------
  // Volver desde /procesando-pdf: los movimientos llegan por el servicio
  // ------------------------------------------------------------------

  it('al volver del flujo de PDF toma los movimientos del servicio', () => {
    importacion.setMovimientos([
      { fecha: '2026-07-01', concepto: 'COBRO', debe: 0, haber: 5, saldo: 5 },
    ] as any);
    const recienCreado = TestBed.createComponent(ConciliacionComponent);
    recienCreado.componentInstance.ngOnInit();
    http.expectOne(`${API}/extractos/bancos`).flush({ bancos: [], formatos: [] });

    expect(recienCreado.componentInstance.movimientosBanco.length).toBe(1);
    expect(recienCreado.componentInstance.infoMensaje).toContain('1 movimientos');
  });

  it('el servicio queda vacio despues de tomar los movimientos', () => {
    importacion.setMovimientos([
      { fecha: '2026-07-01', concepto: 'COBRO', debe: 0, haber: 5, saldo: 5 },
    ] as any);
    const recienCreado = TestBed.createComponent(ConciliacionComponent);
    recienCreado.componentInstance.ngOnInit();
    http.expectOne(`${API}/extractos/bancos`).flush({ bancos: [], formatos: [] });

    // Si no se limpiera, al recargar '/' los movimientos aparecerian solos sin
    // que nadie los hubiera importado en esta sesion.
    expect(importacion.movimientos().length).toBe(0);
  });

  it('entrar a la conciliacion sin movimientos no inventa nada', () => {
    expect(component.movimientosBanco).toEqual([]);
    expect(component.infoMensaje).toBe('');
  });

  // ------------------------------------------------------------------
  // Conciliacion manual: arrastrar una fila hasta su par
  // ------------------------------------------------------------------

  /** Dos pendientes, uno de cada lado, como los deja un cruce ya hecho. */
  function conBandejasListas() {
    component.cruceRealizado = true;
    component.pendientesBanco = [
      { fecha: '2026-07-01', concepto: 'COBRO CLIENTE A', importe: 1000, debe: 0, haber: 1000, saldo: 9000, categoria: 'operativo' },
      { fecha: '2026-07-02', concepto: 'PAGO PROVEEDOR', importe: -250.5, debe: 250.5, haber: 0, saldo: 8749.5, categoria: 'operativo' },
    ];
    component.pendientesXubio = [
      { fecha: '2026-07-01', concepto: 'FACT 0001 A', importe: 1000, debe: 1000, haber: 0 },
      { fecha: '2026-07-05', concepto: 'OP RECIBIDA B', importe: 700, debe: 700, haber: 0 },
    ];
  }

  const eventoFalso = () => ({
    preventDefault: () => {},
    stopPropagation: () => {},
    dataTransfer: { setData: () => {}, effectAllowed: '', dropEffect: '' },
  }) as any;

  it('antes del cruce no se puede arrastrar', () => {
    expect(component.puedeArrastrar).toBe(false);
  });

  it('despues del cruce y en la bandeja de pendientes si se puede arrastrar', () => {
    conBandejasListas();

    expect(component.puedeArrastrar).toBe(true);
  });

  it('en la pestana de conciliados no se arrastra', () => {
    conBandejasListas();
    component.cambiarTab('conciliados');

    expect(component.puedeArrastrar).toBe(false);
  });

  it('soltar sobre una fila del otro lado arma el par y saca ambas de pendientes', () => {
    conBandejasListas();
    const banco = component.pendientesBanco[0];
    const xubio = component.pendientesXubio[0];

    component.alArrastrarFila(banco, 'banco', eventoFalso());
    component.alSoltarSobreFila(xubio, 'xubio', eventoFalso());

    expect(component.pendientesBanco).not.toContain(banco);
    expect(component.pendientesXubio).not.toContain(xubio);
    expect(component.conciliados.length).toBe(1);
    expect(component.conciliados[0].manual).toBe(true);
    expect(component.conciliados[0].concepto_banco).toBe('COBRO CLIENTE A');
    expect(component.conciliados[0].concepto_xubio).toBe('FACT 0001 A');
  });

  it('el par manual que no cuadra queda anotado con la diferencia', () => {
    conBandejasListas();

    component.emparejar(component.pendientesBanco[0], component.pendientesXubio[1]);

    // 1000 contra 700
    expect(component.conciliados[0].diferencia).toBe(300);
    expect(component.infoMensaje).toContain('300');
  });

  it('un par que cuadra al centimo no reporta diferencia', () => {
    conBandejasListas();

    component.emparejar(component.pendientesBanco[0], component.pendientesXubio[0]);

    expect(component.conciliados[0].diferencia).toBe(0);
  });

  it('la diferencia de importe ignora el signo y compara los importes unificados', () => {
    // El banco y el Xubio invierten debe/haber: el mismo hecho va con signo
    // contrario en las dos columnas, pero el importe con signo ya viene
    // unificado por el backend.
    expect(component.diferenciaDeImporte({ importe: -250.5 }, { importe: -250.5 })).toBe(0);
    expect(component.diferenciaDeImporte({ importe: 1000 }, { importe: 700 })).toBe(300);
  });

  it('no se puede soltar una fila del banco sobre otra del banco', () => {
    conBandejasListas();
    const origen = component.pendientesBanco[0];
    const otraDelBanco = component.pendientesBanco[1];

    component.alArrastrarFila(origen, 'banco', eventoFalso());
    expect(component.puedeRecibir(otraDelBanco, 'banco')).toBe(false);

    component.alSoltarSobreFila(otraDelBanco, 'banco', eventoFalso());

    expect(component.conciliados.length).toBe(0);
    expect(component.pendientesBanco.length).toBe(2);
  });

  it('el arrastre se puede hacer tambien desde la tabla de Xubio', () => {
    conBandejasListas();

    component.alArrastrarFila(component.pendientesXubio[0], 'xubio', eventoFalso());
    component.alSoltarSobreFila(component.pendientesBanco[0], 'banco', eventoFalso());

    expect(component.conciliados.length).toBe(1);
    expect(component.pendientesXubio.length).toBe(1);
    expect(component.pendientesBanco.length).toBe(1);
  });

  it('soltar limpia el arrastre, para que el renglon no quede pintado', () => {
    conBandejasListas();

    component.alArrastrarFila(component.pendientesBanco[0], 'banco', eventoFalso());
    component.alArrastrarSobreFila(component.pendientesXubio[0], 'xubio', eventoFalso());
    expect(component.filaDestino).not.toBeNull();

    component.alSoltarSobreFila(component.pendientesXubio[0], 'xubio', eventoFalso());

    expect(component.filaArrastrada).toBeNull();
    expect(component.ladoArrastrado).toBeNull();
    expect(component.filaDestino).toBeNull();
  });

  it('deshacer devuelve las dos filas a su bandeja', () => {
    conBandejasListas();
    const banco = component.pendientesBanco[0];
    const xubio = component.pendientesXubio[0];
    component.emparejar(banco, xubio);

    component.deshacerPareoManual();

    expect(component.conciliados.length).toBe(0);
    expect(component.pendientesBanco).toContain(banco);
    expect(component.pendientesXubio).toContain(xubio);
    expect(component.ultimoPareoManual).toBeNull();
  });

  it('deshacer sin paresPrevios no rompe', () => {
    conBandejasListas();

    expect(() => component.deshacerPareoManual()).not.toThrow();
    expect(component.pendientesBanco.length).toBe(2);
  });

  it('no se puede armar un par con una fila que ya no esta pendiente', () => {
    conBandejasListas();
    const banco = component.pendientesBanco[0];
    const xubio = component.pendientesXubio[0];
    component.emparejar(banco, xubio);

    // La segunda vez la fila del banco ya salio de pendientes.
    component.emparejar(banco, component.pendientesXubio[0]);

    expect(component.conciliados.length).toBe(1);
    expect(component.errorMensaje).not.toBe('');
  });

  it('un cruce nuevo borra los pares manuales del cruce anterior', () => {
    conBandejasListas();
    component.emparejar(component.pendientesBanco[0], component.pendientesXubio[0]);
    expect(component.ultimoPareoManual).not.toBeNull();

    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];
    component.movimientosMayor = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0 }];
    component.ejecutarAutoconciliacion();
    http.expectOne(`${API}/conciliacion/cruzar`).flush({
      exito: true,
      tablas: { conciliados: [], pendientes_banco: [], pendientes_xubio: [] },
    });

    expect(component.ultimoPareoManual).toBeNull();
  });

  it('los pares del backend cuentan como automaticos, no como manuales', () => {
    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];
    component.movimientosMayor = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0 }];
    component.ejecutarAutoconciliacion();
    http.expectOne(`${API}/conciliacion/cruzar`).flush({
      exito: true,
      tablas: {
        conciliados: [{ fecha: '2026-07-01', concepto_banco: 'A', concepto_xubio: 'B', cuadra: true }],
        pendientes_banco: [],
        pendientes_xubio: [],
      },
    });

    expect(component.paresManuales.length).toBe(0);
    expect(component.paresAutomaticos.length).toBe(1);
  });

  it('sin extracto el boton de autoconciliar esta apagado y dice por que', () => {
    expect(component.puedeAutoconciliar).toBe(false);
    expect(component.motivoAutoconciliarBloqueado).toContain('importar un extracto');

    // Con el extracto solo todavia no hay contra que cruzar: la bandeja
    // derecha se llena unicamente con el cruce.
    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];
    expect(component.puedeAutoconciliar).toBe(false);
    expect(component.motivoAutoconciliarBloqueado).toContain('Libro Mayor');

    component.movimientosMayor = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0 }];
    expect(component.puedeAutoconciliar).toBe(true);
    expect(component.motivoAutoconciliarBloqueado).toBe('');
  });

  it('mientras corre el cruce no se manda otro', () => {
    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];
    component.movimientosMayor = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0 }];
    component.ejecutarAutoconciliacion();

    expect(component.cargando).toBe(true);
    expect(component.puedeAutoconciliar).toBe(false);

    // Tres clicks seguidos tienen que ser un solo cruce: cada uno arma las
    // tres bandejas de nuevo y el overlay saltaria como un estroboscopio.
    component.ejecutarAutoconciliacion();
    component.ejecutarAutoconciliacion();
    http.expectOne(`${API}/conciliacion/cruzar`).flush({
      exito: true,
      tablas: { conciliados: [], pendientes_banco: [], pendientes_xubio: [] },
    });

    expect(component.cargando).toBe(false);
  });

  // ------------------------------------------------------------------
  // Libro Mayor: la otra mitad del cruce
  //
  // La API de Xubio esta reservada a planes superiores al contratado, asi que
  // el mayor entra como archivo exportado desde el navegador. Sin ese archivo
  // la bandeja derecha no se llena nunca, no se puede parear nada a mano y no
  // hay conciliacion que exportar: por eso es condicion del Autoconciliar.
  // ------------------------------------------------------------------

  /** El input del Libro Mayor, que vive en la botonera de la pantalla. */
  function inputMayor(): HTMLInputElement {
    return fixture.nativeElement.querySelector('#archivoMayor');
  }

  /** Pone un archivo en el input y dispara change, como al elegirlo. */
  function elegirMayor(nombre: string) {
    const input = inputMayor();
    Object.defineProperty(input, 'files', {
      value: [archivoConNombre(nombre)],
      // configurable y writable: el TestBed reutiliza el elemento raiz entre
      // tests y value='' del componente escribe sobre esta propiedad.
      configurable: true,
      writable: true,
    });
    input.dispatchEvent(new Event('change'));
  }

  const FILA_MAYOR = { fecha: '2026-09-01', concepto: 'Cobro cliente', debe: 100, haber: 0 };

  it('el input del Libro Mayor acepta los tres formatos de tabla', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    expect(inputMayor().getAttribute('accept')).toBe('.xlsx,.xls,.csv');
  });

  it('cargar el Libro Mayor lo manda al backend y habilita Autoconciliar', async () => {
    elegirMayor('mayor-septiembre.xlsx');

    const req = http.expectOne(`${API}/conciliacion/mayor`);
    expect(req.request.body.get('archivo') instanceof File).toBe(true);
    req.flush({ exito: true, cantidad_movimientos: 2, datos: [FILA_MAYOR, FILA_MAYOR] });
    await fixture.whenStable();

    expect(component.movimientosMayor.length).toBe(2);
    expect(component.nombreMayor).toBe('mayor-septiembre.xlsx');
    expect(component.infoMensaje).toContain('2 movimientos');
    expect(component.infoMensaje).not.toContain('el débito es salida');
    expect(component.puedeAutoconciliar).toBe(false);
    expect(component.motivoAutoconciliarBloqueado).toContain('importar un extracto');
  });

  it('un mayor en formato de movimientos de cuenta muestra que el debito es salida', async () => {
    // Xubio exporta "Movimientos de CC" con Debito/Credito en $: ahi el debito
    // es plata que SALE, al reves de un Libro Mayor contable. El backend lo
    // detecta por los encabezados y la pantalla tiene que mostrarlo, o alguien
    // podria pensar que los signos andan mal.
    elegirMayor('movimientos-cc.xlsx');

    const req = http.expectOne(`${API}/conciliacion/mayor`);
    req.flush({
      exito: true,
      cantidad_movimientos: 1,
      convencion: 'cuenta',
      datos: [FILA_MAYOR],
    });
    await fixture.whenStable();

    expect(component.movimientosMayor.length).toBe(1);
    expect(component.infoMensaje).toContain('el débito es salida');
    expect(component.infoMensaje).toContain('Ya se puede pedir Autoconciliar');
  });

  it('un Libro Mayor con otra extension no sale al backend', () => {
    elegirMayor('mayor.pdf');

    http.expectNone(`${API}/conciliacion/mayor`);
    expect(component.errorMensaje).toContain('mayor.pdf');
    expect(component.movimientosMayor.length).toBe(0);
  });

  it('si el Libro Mayor no se puede leer se ve el motivo y no se pierde el anterior', () => {
    component.movimientosMayor = [{ fecha: '2026-08-01', concepto: 'X', debe: 1, haber: 0 }];
    component.nombreMayor = 'agosto.xlsx';

    elegirMayor('septiembre.xlsx');
    http.expectOne(`${API}/conciliacion/mayor`).flush(
      { detail: 'El Libro Mayor no tiene columna de Fecha.' },
      { status: 422, statusText: 'Unprocessable Entity' }
    );

    expect(component.cargando).toBe(false);
    expect(component.errorMensaje).toContain('no tiene columna de Fecha');
    // Tirar una carga buena por un intento fallido deja la pantalla peor.
    expect(component.movimientosMayor.length).toBe(1);
    expect(component.errorMensaje).toContain('agosto.xlsx');
  });

  it('cargar un Libro Mayor nuevo borra el cruce anterior', async () => {
    component.cruceRealizado = true;
    component.conciliados = [
      {
        fecha: '2026-08-01',
        concepto_banco: 'X',
        concepto_xubio: 'Y',
        debe: 1,
        haber: 0,
        saldo: 1,
        importe: -1,
        manual: true,
      },
    ];
    component.ultimoPareoManual = { banco: {}, xubio: {} };

    elegirMayor('mayor.xlsx');
    http.expectOne(`${API}/conciliacion/mayor`).flush({
      exito: true,
      cantidad_movimientos: 1,
      datos: [FILA_MAYOR],
    });
    await fixture.whenStable();

    expect(component.cruceRealizado).toBe(false);
    expect(component.conciliados).toEqual([]);
    expect(component.ultimoPareoManual).toBeNull();
  });

  it('Autoconciliar manda los dos lados en el cuerpo', () => {
    const banco = { fecha: '2026-09-01', concepto: 'COBRO', debe: 0, haber: 100, saldo: 100 };
    component.movimientosBanco = [banco];
    component.movimientosMayor = [FILA_MAYOR];

    component.ejecutarAutoconciliacion();

    const req = http.expectOne(`${API}/conciliacion/cruzar`);
    expect(req.request.body.movimientos_banco).toEqual([banco]);
    expect(req.request.body.movimientos_xubio).toEqual([FILA_MAYOR]);
    req.flush({
      exito: true,
      tablas: {
        conciliados: [
          {
            fecha: '2026-09-01',
            concepto_banco: 'COBRO',
            concepto_xubio: 'Cobro cliente',
            debe: 0,
            haber: 100,
            saldo: 100,
            importe: 100,
          },
        ],
        pendientes_banco: [],
        pendientes_xubio: [],
      },
    });

    expect(component.cruceRealizado).toBe(true);
    expect(component.conciliados.length).toBe(1);
    expect(component.infoMensaje).toContain('1 pares encontrados');
  });

  it('un cruce sin Libro Mayor no sale al backend y dice que falta', () => {
    component.movimientosBanco = [{ fecha: '2026-09-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];

    component.ejecutarAutoconciliacion();

    http.expectNone(`${API}/conciliacion/cruzar`);
    expect(component.errorMensaje).toContain('Libro Mayor');
  });

  it('con el archivo cargado el boton del Libro Mayor muestra cuantas filas trajo', async () => {
    elegirMayor('mayor.xlsx');
    http.expectOne(`${API}/conciliacion/mayor`).flush({
      exito: true,
      cantidad_movimientos: 1,
      datos: [FILA_MAYOR],
    });
    // En zoneless mutar a mano no repinta: hace falta un evento real del DOM.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    expect(fixture.nativeElement.textContent).toContain('Libro Mayor: 1');
  });

  // ------------------------------------------------------------------
  // Que se vea de verdad
  //
  // Los tests de arriba mueven el estado del componente a mano, asi que no
  // renderizan. Con el builder zoneless de Angular 22, mutar una propiedad y
  // llamar a detectChanges() no repinta: hace falta un evento real del DOM, que si
  // es un origen de notificacion. Por eso estos tests clickean la pantalla como
  // lo haria el usuario. Tambien es lo que atrapa un error de template (un
  // ng-container sin cerrar, un *ngIf al reves) que si no revienta recien al
  // abrir la aplicacion.
  // ------------------------------------------------------------------

  /** Click en el boton cuyo texto empiece con el texto buscado. */
  function clickEnTexto(texto: string): boolean {
    const botones = Array.from(document.querySelectorAll('button')) as HTMLButtonElement[];
    const boton = botones.find((b) => b.textContent?.trim().startsWith(texto));
    if (!boton) return false;
    boton.click();
    return true;
  }

  async function abrirMenuImportar() {
    expect(clickEnTexto('Importar')).toBe(true);
    await fixture.whenStable();
  }

  // ------------------------------------------------------------------
  // Exportar: el papel de trabajo FO 02-03
  // ------------------------------------------------------------------

  const URL_EXPORTAR = `${API}/exportar/conciliacion`;

  /** jsdom no implementa createObjectURL, que es lo que usa la descarga. */
  function conDescargaEspiada() {
    const original = URL.createObjectURL;
    const revocarOriginal = URL.revokeObjectURL;
    const clickOriginal = HTMLAnchorElement.prototype.click;
    URL.createObjectURL = () => 'blob:mock';
    URL.revokeObjectURL = () => {};
    HTMLAnchorElement.prototype.click = () => {};

    return () => {
      URL.createObjectURL = original;
      URL.revokeObjectURL = revocarOriginal;
      HTMLAnchorElement.prototype.click = clickOriginal;
    };
  }

  it('antes del cruce no hay nada que exportar y el boton queda apagado', () => {
    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];

    // El extracto del banco sin cruzar no es una conciliacion: bajarlo seria
    // entregar un papel de trabajo con cero partidas conciliadas.
    expect(component.puedeExportar).toBe(false);
    expect(component.motivoExportBloqueado).toContain('no hay');
  });

  it('con las bandejas llenas el boton se puede usar', () => {
    conBandejasListas();

    expect(component.puedeExportar).toBe(true);
    expect(component.motivoExportBloqueado).toBe('');
  });

  it('sin nada que exportar avisa y no sale al backend', () => {
    component.exportarPapelDeTrabajo();

    http.expectNone(URL_EXPORTAR);
    expect(component.errorMensaje).toContain('conciliación');
  });

  it('el payload manda las tres bandejas y el membrete', () => {
    conBandejasListas();
    component.bancoSeleccionado = 'SANT';
    component.fechaDesde = '2026-07-01';
    component.fechaHasta = '2026-07-31';

    const payload = component.payloadDeExportacion();

    expect(payload.conciliados).toEqual([]);
    expect(payload.pendientes_banco.length).toBe(2);
    expect(payload.pendientes_xubio.length).toBe(2);
    expect(payload.encabezado.banco).toBe('SANT');
  });

  // El papel de trabajo tiene que mostrar lo que el usuario acaba de revisar.
  // Un par armado a mano no lo conoce el backend, asi que si el payload no lo
  // incluye, el archivo sale con la conciliacion a medias.
  it('el payload incluye los pares armados a mano con su diferencia', () => {
    conBandejasListas();
    component.emparejar(component.pendientesBanco[0], component.pendientesXubio[1]);

    const payload = component.payloadDeExportacion();

    expect(payload.conciliados.length).toBe(1);
    expect(payload.conciliados[0].manual).toBe(true);
    expect(payload.conciliados[0].diferencia).toBe(300);
    expect(payload.pendientes_banco.length).toBe(1);
    expect(payload.pendientes_xubio.length).toBe(1);
  });

  it('el periodo sale del rango de fechas de los filtros', () => {
    conBandejasListas();
    component.fechaDesde = '2026-07-01';
    component.fechaHasta = '2026-07-31';

    // La celda del periodo en la plantilla tiene formato 'mmmm yyyy': por eso
    // va solo el anio y el mes, no la fecha entera.
    expect(component.encabezadoDelPapel().periodo).toBe('2026-07');
  });

  it('sin rango de fechas el periodo queda en null, no inventado', () => {
    conBandejasListas();

    expect(component.encabezadoDelPapel().periodo).toBeNull();
  });

  it('la empresa queda vacia hasta que haya un dato real', () => {
    conBandejasListas();

    // No hay endpoint de empresa y no hay dato hardcodeado en el proyecto.
    // Poner un nombre inventado en un papel de trabajo firmado es peor que
    // dejarlo en blanco.
    expect(component.encabezadoDelPapel().empresa).toBe('');
  });

  // El membrete se arma con la seleccion del flujo de importacion, que
  // ngOnInit vacia del servicio. Sin guardarla antes, la cuenta elegida en
  // /importar-pdf se perdia y el papel salia sin numero de cuenta.
  it('la cuenta y el banco elegidos en /importar-pdf llegan al membrete', () => {
    importacion.guardar({
      cuentaId: '1105',
      cuentaNombre: 'Caja',
      banco: 'SANT',
      archivo: archivoConNombre('julio.pdf'),
    });
    importacion.setMovimientos([
      { fecha: '2026-07-01', concepto: 'COBRO', debe: 0, haber: 5, saldo: 5 },
    ] as any);

    const recienCreado = TestBed.createComponent(ConciliacionComponent);
    recienCreado.componentInstance.ngOnInit();
    // SANT va el ultimo a proposito: si la precarga del primer banco pisara
    // la seleccion del flujo, el membrete diria ICBC.
    http.expectOne(`${API}/extractos/bancos`).flush({
      bancos: ['ICBC', 'SANT'],
      formatos: [],
    });

    const encabezado = recienCreado.componentInstance.encabezadoDelPapel();

    // numero_cuenta y no numeroCuenta: Pydantic tira las claves que no
    // reconoce, asi que con el nombre en camelCase la cuenta nunca llegaba.
    expect(encabezado.numero_cuenta).toBe('1105');
    expect(encabezado.banco).toBe('SANT');
    // El servicio se vacia igual que antes: los movimientos no resucitan.
    expect(importacion.movimientos().length).toBe(0);
  });

  it('exportar baja el archivo y avisa con el conteo', async () => {
    const restaurar = conDescargaEspiada();
    conBandejasListas();

    try {
      component.exportarPapelDeTrabajo();
      const peticion = http.expectOne(URL_EXPORTAR);
      expect(peticion.request.method).toBe('POST');
      peticion.flush(new Blob(['xlsx']), {
        headers: { 'Content-Disposition': 'attachment; filename="FO 02-03 algo.xlsx"' },
      });
      await fixture.whenStable();

      expect(component.exportando).toBe(false);
      expect(component.infoMensaje).toContain('0 conciliados');
      expect(component.errorMensaje).toBe('');
    } finally {
      restaurar();
    }
  });

  it('mientras arma el archivo el boton queda deshabilitado y no se repregunta', () => {
    conBandejasListas();

    component.exportarPapelDeTrabajo();
    http.expectOne(URL_EXPORTAR);

    expect(component.exportando).toBe(true);
    expect(component.puedeExportar).toBe(false);

    // Tres clicks seguidos tienen que ser un solo archivo, no tres.
    component.exportarPapelDeTrabajo();
    component.exportarPapelDeTrabajo();
    http.expectNone(URL_EXPORTAR);
  });

  // Con responseType 'blob', el body del error llega como Blob: el motivo real
  // esta adentro y hay que abrirlo. Si no se abre, el usuario lee "no se pudo
  // generar el Excel" en lugar de "no hay nada conciliado para exportar".
  it('si el backend falla se muestra el motivo real y se vuelve a habilitar', async () => {
    conBandejasListas();

    component.exportarPapelDeTrabajo();
    http.expectOne(URL_EXPORTAR).flush(
      new Blob([JSON.stringify({ detail: 'No hay nada conciliado para exportar.' })]),
      { status: 400, statusText: 'Bad Request' },
    );
    await fixture.whenStable();
    // El mensaje se resuelve en una promesa y leer un Blob pasa por
    // text(), asi que hacen falta dos turnos de macrotarea antes de que
    // aparezca en pantalla.
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    await fixture.whenStable();

    expect(component.exportando).toBe(false);
    expect(component.errorMensaje).toBe('No hay nada conciliado para exportar.');
  });

  it('si el backend no esta, el error no deja el boton trabado', async () => {
    conBandejasListas();

    component.exportarPapelDeTrabajo();
    http.expectOne(URL_EXPORTAR).error(new ProgressEvent('error'), { status: 0 });
    await fixture.whenStable();

    expect(component.exportando).toBe(false);
    expect(component.puedeExportar).toBe(true);
  });

  it('el motivo del boton apagado se escribe en pantalla, no solo en el title', async () => {
    component.movimientosBanco = [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }];
    fixture.detectChanges();
    await fixture.whenStable();

    // Un boton deshabilitado sin explicacion deja al usuario buscando que le
    // falta. Ademas el title no se ve en un celular.
    expect(fixture.nativeElement.textContent).toContain('Todavía no hay una conciliación');
  });
});
