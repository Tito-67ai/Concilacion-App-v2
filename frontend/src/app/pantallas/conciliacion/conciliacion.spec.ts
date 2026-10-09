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
    // Tambien pide los afiliados para el panel derecho. Se responde vacio:
    // asi el resto de los tests no tiene que saber nada de Xubio ni del cruce
    // de afiliados, que solo sale si hay lista.
    http.expectOne(`${API}/xubio/afiliados`).flush({ exito: true, cantidad: 0, datos: [] });
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
    http.expectOne(`${API}/xubio/afiliados`).flush({ exito: true, cantidad: 0, datos: [] });

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
    http.expectOne(`${API}/xubio/afiliados`).flush({ exito: true, cantidad: 0, datos: [] });

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

  /** Escribe en un input como lo haria el usuario (modelo y DOM en sincronia). */
  function escribirEnInput(selector: string, valor: string) {
    const input = fixture.nativeElement.querySelector(selector) as HTMLInputElement;
    input.value = valor;
    input.dispatchEvent(new Event('input'));
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
    http.expectOne(`${API}/xubio/afiliados`).flush({ exito: true, cantidad: 0, datos: [] });

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

  // ------------------------------------------------------------------
  // Afiliados de la web de Xubio en el inicio del panel derecho
  // ------------------------------------------------------------------

  const AFILIADO_2GTECH = {
    id: 1,
    organizacionId: 10,
    organizacionNombre: '2GTECH ELECTRONICA S.A.',
    cuit: '30-71234567-8',
    categoriaFiscal: 'Responsable Inscripto',
    activo: 1,
    esProveedor: 0,
  };
  const AFILIADO_LIBRERIA = {
    id: 2,
    organizacionId: 20,
    organizacionNombre: 'LIBRERIA EL FARO',
    cuit: '20-12345678-9',
    categoriaFiscal: 'Monotributista',
    activo: 1,
    esProveedor: 1,
  };

  /** Pide la lista de afiliados y el backend la manda con estos datos. */
  function descargarAfiliados(datos: any[]) {
    component.cargarAfiliados();
    http.expectOne(`${API}/xubio/afiliados`).flush({
      exito: true,
      cantidad: datos.length,
      datos,
    });
  }

  it('al entrar carga los afiliados y el panel derecho muestra su IVA', async () => {
    descargarAfiliados([AFILIADO_2GTECH, AFILIADO_LIBRERIA]);
    await fixture.whenStable();

    // Zoneless: mutar el estado y llamar a detectChanges no repinta; hace
    // falta un evento real del DOM (misma convencion que el resto del spec).
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('2GTECH ELECTRONICA');
    expect(texto).toContain('LIBRERIA EL FARO');
    // El IVA de cada empresa: la categoria fiscal que le pone Xubio.
    expect(texto).toContain('Responsable Inscripto');
    expect(texto).toContain('Monotributista');
    expect(texto).toContain('Proveedor');
    // El resumen de cuantos facturan IVA.
    expect(texto).toContain('1 con IVA');
  });

  it('sin cookie los afiliados no se inventan y queda el motivo con reintentar', async () => {
    component.cargarAfiliados();
    http.expectOne(`${API}/xubio/afiliados`).flush(
      { detail: 'XUBIO_WEB_COOKIE no está configurada. Pegá la cookie de la sesión de Xubio en backend/.env.' },
      { status: 503, statusText: 'Service Unavailable' }
    );
    await fixture.whenStable();

    expect(component.afiliados).toEqual([]);
    expect(component.afiliadosError).toContain('XUBIO_WEB_COOKIE');

    // Zoneless: un evento real del DOM repinta (ver convencion arriba).
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('Reintentar');
    // El 503 por falta de sesion ademas ofrece el login de Xubio en el mismo
    // panel, para renovar la sesion sin tocar el .env a mano.
    expect(component.xubioSesionRequerida).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión en Xubio');

    // Reintentar vuelve a pedir la lista, sin recargar la pagina.
    expect(clickEnTexto('Reintentar')).toBe(true);
    http.expectOne(`${API}/xubio/afiliados`).flush({
      exito: true,
      cantidad: 1,
      datos: [AFILIADO_2GTECH],
    });
    await fixture.whenStable();

    expect(component.afiliados.length).toBe(1);
    expect(component.afiliadosError).toBe('');
    expect(component.xubioSesionRequerida).toBe(false);
  });

  it('completar el login de Xubio renueva la sesión y recarga los afiliados solo', async () => {
    component.cargarAfiliados();
    http.expectOne(`${API}/xubio/afiliados`).flush(
      { detail: 'XUBIO_WEB_TOKEN no está configurada. Pegá el token de la sesión de Xubio en backend/.env.' },
      { status: 503, statusText: 'Service Unavailable' }
    );
    await fixture.whenStable();
    expect(component.xubioSesionRequerida).toBe(true);

    // Zoneless: el formulario aparece despues de un evento real del DOM.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión en Xubio');

    escribirEnInput('input[name="xubioEmail"]', 'tito.rodriguez@estudiopiccinini.com.ar');
    escribirEnInput('input[name="xubioPassword"]', 'contraseña');
    expect(clickEnTexto('Iniciar sesión')).toBe(true);
    await fixture.whenStable();

    const login = http.expectOne(`${API}/xubio/login`);
    expect(login.request.method).toBe('POST');
    expect(login.request.body).toEqual({
      email: 'tito.rodriguez@estudiopiccinini.com.ar',
      password: 'contraseña',
    });
    login.flush({ exito: true, sesion: { token: true, cookie: false } });
    await fixture.whenStable();

    // El login termino (el bot guardo el token): la lista se vuelve a pedir sola.
    http.expectOne(`${API}/xubio/afiliados`).flush({
      exito: true,
      cantidad: 1,
      datos: [AFILIADO_2GTECH],
    });
    await fixture.whenStable();

    expect(component.afiliados.length).toBe(1);
    expect(component.xubioSesionRequerida).toBe(false);
    // La contrasena no queda dando vueltas en el estado del componente.
    expect(component.xubioPassword).toBe('');
  });

  it('si el bot no puede renovar la sesión, el motivo queda en el formulario para reintentar', async () => {
    component.cargarAfiliados();
    http.expectOne(`${API}/xubio/afiliados`).flush(
      { detail: 'XUBIO_WEB_TOKEN no está configurada. Pegá el token de la sesión de Xubio en backend/.env.' },
      { status: 503, statusText: 'Service Unavailable' }
    );
    await fixture.whenStable();

    // Zoneless: el formulario aparece despues de un evento real del DOM.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    escribirEnInput('input[name="xubioEmail"]', 'a@b.com');
    escribirEnInput('input[name="xubioPassword"]', 'secreta');
    expect(clickEnTexto('Iniciar sesión')).toBe(true);
    await fixture.whenStable();

    const login = http.expectOne(`${API}/xubio/login`);
    login.flush(
      { detail: 'No se pudo renovar la sesión de Xubio: el login pidió un link por email.' },
      { status: 502, statusText: 'Bad Gateway' }
    );
    await fixture.whenStable();

    expect(component.xubioLoginError).toContain('No se pudo renovar la sesión de Xubio');
    expect(component.xubioRenovando).toBe(false);
    expect(component.xubioSesionRequerida).toBe(true);

    // El formulario sigue en pantalla para corregir y reintentar.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión en Xubio');
  });

  // ------------------------------------------------------------------
  // Salir de Xubio / Cerrar sesión desde la barra superior
  // ------------------------------------------------------------------

  it('con sesión la barra superior ofrece Salir de Xubio y Cerrar sesión', async () => {
    // El beforeEach respondio los afiliados con exito: hay sesion, aunque la
    // lista este vacia, y la barra ofrece los dos botones.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Salir de Xubio');
    expect(texto).toContain('Cerrar sesión');
  });

  it('Salir de Xubio borra la sesión y el panel vuelve al login', async () => {
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    expect(clickEnTexto('Salir de Xubio')).toBe(true);
    await fixture.whenStable();

    const salida = http.expectOne(`${API}/xubio/sesion`);
    expect(salida.request.method).toBe('DELETE');
    salida.flush({ exito: true, configurada: false, credenciales: true });
    await fixture.whenStable();

    // Sin token el backend responde 503: la lista se pide sola de nuevo y el
    // panel derecho muestra el login de Xubio, sin los botones de la barra.
    http.expectOne(`${API}/xubio/afiliados`).flush(
      { detail: 'XUBIO_WEB_TOKEN no está configurada. Pegá el token de la sesión de Xubio en backend/.env.' },
      { status: 503, statusText: 'Service Unavailable' }
    );
    await fixture.whenStable();

    expect(component.xubioSesionRequerida).toBe(true);
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('Iniciar sesión en Xubio');
    expect(fixture.nativeElement.textContent).not.toContain('Salir de Xubio');
    expect(fixture.nativeElement.textContent).not.toContain('Cerrar sesión');
  });

  it('Cerrar sesión borra también las credenciales guardadas', async () => {
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    expect(clickEnTexto('Cerrar sesión')).toBe(true);
    await fixture.whenStable();

    const salida = http.expectOne(`${API}/xubio/sesion?olvidar_credenciales=true`);
    expect(salida.request.method).toBe('DELETE');
    salida.flush({ exito: true, configurada: false, credenciales: false });
    await fixture.whenStable();

    http.expectOne(`${API}/xubio/afiliados`).flush(
      { detail: 'XUBIO_WEB_TOKEN no está configurada. Pegá el token de la sesión de Xubio en backend/.env.' },
      { status: 503, statusText: 'Service Unavailable' }
    );
    await fixture.whenStable();

    expect(component.xubioSesionRequerida).toBe(true);
    // El aviso distingue el cierre total del que conserva las credenciales.
    expect(component.infoMensaje).toContain('se borraron las credenciales');
  });

  it('cruza los movimientos del banco contra los afiliados ya descargados', async () => {
    const movimiento = {
      fecha: '2026-09-01',
      concepto: 'PAGO 2GTECH ELECTRONICA',
      debe: 1000,
      haber: 0,
      saldo: 9000,
    };
    component.movimientosBanco = [movimiento];

    descargarAfiliados([AFILIADO_2GTECH]);

    const peticion = http.expectOne(`${API}/xubio/cruzar-afiliados`);
    expect(peticion.request.body.movimientos).toEqual([movimiento]);
    // Los afiliados van en el cuerpo: el cruce no vuelve a la web de Xubio.
    expect(peticion.request.body.afiliados.length).toBe(1);
    peticion.flush({
      exito: true,
      resumen: { afiliados_reconocidos: 1, sin_reconocer: 0 },
      datos: [{ indice: 0, afiliado: AFILIADO_2GTECH, metodo: 'nombre' }],
    });
    await fixture.whenStable();

    expect(component.totalMovimientosConPosibleConciliacion).toBe(1);
    expect(component.cruceConAfiliados[0].afiliado.organizacionNombre).toBe('2GTECH ELECTRONICA S.A.');
  });

  it('cuenta las posibles conciliaciones por afiliado y deja los demas al final', async () => {
    component.movimientosBanco = [
      { fecha: '2026-09-01', concepto: 'PAGO 2GTECH', debe: 100, haber: 0, saldo: 100 },
      { fecha: '2026-09-02', concepto: '2GTECH S.A.', debe: 200, haber: 0, saldo: 200 },
    ];
    descargarAfiliados([AFILIADO_2GTECH, AFILIADO_LIBRERIA]);
    http.expectOne(`${API}/xubio/cruzar-afiliados`).flush({
      exito: true,
      resumen: { afiliados_reconocidos: 2, sin_reconocer: 0 },
      datos: [
        { indice: 0, afiliado: AFILIADO_2GTECH, metodo: 'nombre' },
        { indice: 1, afiliado: AFILIADO_2GTECH, metodo: 'nombre' },
      ],
    });
    await fixture.whenStable();

    const ordenados = component.afiliadosConPosiblesConciliaciones;
    expect(ordenados.length).toBe(2);
    // El que acumula movimientos va primero con el conteo; el otro al final.
    expect(ordenados[0].afiliado.organizacionNombre).toBe('2GTECH ELECTRONICA S.A.');
    expect(ordenados[0].movimientos).toBe(2);
    expect(ordenados[1].afiliado.organizacionNombre).toBe('LIBRERIA EL FARO');
    expect(ordenados[1].movimientos).toBe(0);
  });

  it('despues del cruce con el mayor la bandeja reemplaza a la lista de afiliados', async () => {
    // Los afiliados llegan antes que los movimientos: no hay cruce todavia.
    descargarAfiliados([AFILIADO_2GTECH]);
    await fixture.whenStable();

    component.movimientosBanco = [{ fecha: '2026-09-01', concepto: 'COBRO', debe: 0, haber: 100, saldo: 100 }];
    component.movimientosMayor = [{ fecha: '2026-09-01', concepto: 'Cobro cliente', debe: 100, haber: 0 }];
    component.ejecutarAutoconciliacion();
    http.expectOne(`${API}/conciliacion/cruzar`).flush({
      exito: true,
      tablas: {
        conciliados: [],
        pendientes_banco: [],
        pendientes_xubio: [{ fecha: '2026-09-01', concepto: 'Cobro cliente', debe: 100, haber: 0 }],
      },
    });
    await fixture.whenStable();

    // Apenas se arma la bandeja se la clasifica por empresa para el filtro del
    // panel derecho: esta respuesta viaja sola, no bloquea al cruce.
    const clasificar = http.expectOne(`${API}/xubio/clasificar-mayor`);
    expect(clasificar.request.body.movimientos.length).toBe(1);
    clasificar.flush({
      exito: true,
      resumen: { afiliados_reconocidos: 0, sin_reconocer: 1 },
      datos: [{ indice: 0, afiliado: null, metodo: null }],
    });
    await fixture.whenStable();

    expect(component.cruceRealizado).toBe(true);
    expect(component.filasXubio.length).toBe(1);

    // La bandeja de pendientes vuelve a ser lo que se muestra, no los afiliados.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();
    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Cobro cliente');
    // La tabla de afiliados (con su columna de posible conciliacion) ya no se
    // dibuja despues del cruce: la bandeja la reemplazo. El nombre de la
    // empresa solo sobrevive ahora en el filtro "Empresa" de la bandeja.
    expect(texto).not.toContain('Posible conciliación');
    expect(texto).toContain('Todas las empresas');
  });

  // ------------------------------------------------------------------
  // Filtro por empresa de la bandeja del mayor
  // ------------------------------------------------------------------

  it('la bandeja del mayor se filtra por empresa con la clasificacion del backend', async () => {
    component.cruceRealizado = true;
    component.pendientesXubio = [
      { fecha: '2026-09-01', concepto: 'Cobro a 2GTECH ELECTRONICA', comprobante: 'FCA-0001-00000001', debe: 100, haber: 0, importe: 100 },
      { fecha: '2026-09-02', concepto: 'Pago a LIBRERIA', comprobante: null, debe: 0, haber: 40, importe: -40 },
    ];
    component.afiliados = [AFILIADO_2GTECH, AFILIADO_LIBRERIA];

    // El backend decide de que afiliado es cada fila (reusa el cruce de
    // nombres/CUIT) y el componente muestra todo hasta que llega.
    component.clasificarFilasXubio();
    http.expectOne(`${API}/xubio/clasificar-mayor`).flush({
      exito: true,
      resumen: { afiliados_reconocidos: 1, sin_reconocer: 1 },
      datos: [
        { indice: 0, afiliado: AFILIADO_2GTECH, metodo: 'nombre' },
        { indice: 1, afiliado: null, metodo: null },
      ],
    });
    await fixture.whenStable();

    expect(component.filasXubioFiltradas.length).toBe(2);

    component.empresaFiltro = AFILIADO_2GTECH.id;
    expect(component.filasXubioFiltradas.length).toBe(1);
    expect(component.filasXubioFiltradas[0].comprobante).toBe('FCA-0001-00000001');
  });

  it('sin clasificacion (aun no llego) el filtro no esconde filas', async () => {
    component.cruceRealizado = true;
    component.pendientesXubio = [
      { fecha: '2026-09-01', concepto: 'Cobro a 2GTECH ELECTRONICA', comprobante: 'FCA-0001-00000001', debe: 100, haber: 0, importe: 100 },
    ];
    component.afiliados = [AFILIADO_2GTECH];

    component.empresaFiltro = AFILIADO_2GTECH.id;
    // La clasificacion no esta alineada con la bandeja (0 vs 1 filas): el
    // filtro no se aplica a medias, se muestra todo.
    expect(component.filasXubioFiltradas.length).toBe(1);
  });

  it('el filtro y las columnas de la bandeja aparecen en pantalla', async () => {
    component.cruceRealizado = true;
    component.pendientesXubio = [
      { fecha: '2026-09-01', concepto: 'Cobro a 2GTECH ELECTRONICA', comprobante: 'FCA-0001-00000001', debe: 100, haber: 0, importe: 100 },
    ];
    component.afiliados = [AFILIADO_2GTECH];
    component.clasificarFilasXubio();
    http.expectOne(`${API}/xubio/clasificar-mayor`).flush({
      exito: true,
      resumen: { afiliados_reconocidos: 1, sin_reconocer: 0 },
      datos: [{ indice: 0, afiliado: AFILIADO_2GTECH, metodo: 'nombre' }],
    });
    await fixture.whenStable();

    // Zoneless: un evento real del DOM repinta la bandeja.
    expect(clickEnTexto('Movimientos a conciliar')).toBe(true);
    await fixture.whenStable();

    const texto = fixture.nativeElement.textContent;
    // El desplegable del filtro listando las empresas ya descargadas.
    expect(texto).toContain('Empresa');
    expect(texto).toContain('Todas las empresas');
    expect(texto).toContain('2GTECH ELECTRONICA');
    // Las columnas de la bandeja: Fecha, Comprobante, Detalle, Importe.
    expect(texto).toContain('Comprobante');
    expect(texto).toContain('Detalle');
    expect(texto).toContain('FCA-0001-00000001');
  });

  // ------------------------------------------------------------------
  // Zoneless: el estado repinta solo, sin esperar un click
  //
  // El resto del spec clickea la pantalla para repintar porque el builder
  // zoneless no repinta al mutar una propiedad y llamar a detectChanges()
  // (convencion de arriba). En produccion nadie clickea para ver los
  // afiliados: los setters del componente tienen que notificar solos.
  // Estas dos pruebas documentan ese comportamiento. Si vuelven a rojo es
  // porque el repintado automatico (notificar() en conciliacion.ts) se rompio.
  // ------------------------------------------------------------------

  it('los afiliados se dibujan apenas llegan, sin ningun click', async () => {
    descargarAfiliados([AFILIADO_2GTECH]);
    await fixture.whenStable();

    // Sin clickEnTexto: la lista tiene que estar en pantalla solita.
    expect(fixture.nativeElement.textContent).toContain('2GTECH ELECTRONICA');
  });

  it('asignar movimientos a mano repinta la tabla sin esperar un click', async () => {
    component.movimientosBanco = [
      { fecha: '2026-07-01', concepto: 'COBRO DE PRUEBA', debe: 0, haber: 5, saldo: 5 },
    ];
    await fixture.whenStable();

    // Sin clickEnTexto: la fila tiene que aparecer en la tabla del banco.
    expect(fixture.nativeElement.textContent).toContain('COBRO DE PRUEBA');
  });
});
