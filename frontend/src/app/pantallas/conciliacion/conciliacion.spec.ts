import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { ConciliacionComponent } from './conciliacion';

describe('ConciliacionComponent', () => {
  let component: ConciliacionComponent;
  let fixture: ComponentFixture<ConciliacionComponent>;
  let http: HttpTestingController;

  /** Arma un File con el nombre que se le pida (el constructor no acepta props). */
  function archivoConNombre(nombre: string): File {
    return new File([new Uint8Array([37, 80, 68, 70])], nombre);
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConciliacionComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ConciliacionComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    await fixture.whenStable();
    // El componente pide la lista de bancos al arrancar.
    http.expectOne('http://127.0.0.1:8000/api/extractos/bancos').flush({
      bancos: ['SANT', 'ICBC', 'GENERICO'],
      formatos: ['pdf', 'tabla']
    });
  });

  afterEach(() => http.verify());

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ------------------------------------------------------------------
  // Las dos vias de importacion
  // ------------------------------------------------------------------

  it('arranca en la pantalla de conciliacion, no en el apartado de carga', () => {
    expect(component.modoImportacion).toBeNull();
    expect(component.enApartadoDeImportacion).toBe(false);
  });

  it('ofrece exactamente dos vias, PDF y Excel', () => {
    expect(component.opcionesImportacion.map((o) => o.modo)).toEqual(['pdf', 'tabla']);
    expect(component.opcionesImportacion[0].acepta).toBe('.pdf');
    expect(component.opcionesImportacion[1].acepta).toBe('.xlsx,.xls,.csv');
  });

  it('elegir una via abre el apartado de carga de esa via', () => {
    component.elegirModo('tabla');

    expect(component.modoImportacion).toBe('tabla');
    expect(component.enApartadoDeImportacion).toBe(true);
    expect(component.opcionActiva?.acepta).toBe('.xlsx,.xls,.csv');
  });

  it('elegir una via cierra el menu', () => {
    component.menuImportarAbierto = true;
    component.elegirModo('pdf');

    expect(component.menuImportarAbierto).toBe(false);
  });

  it('volver cierra el apartado y limpia los mensajes', () => {
    component.elegirModo('pdf');
    component.archivoSeleccionado = archivoConNombre('extracto.pdf');
    component.errorMensaje = 'algo';

    component.cerrarApartadoImportacion();

    expect(component.modoImportacion).toBeNull();
    expect(component.archivoSeleccionado).toBeNull();
    expect(component.errorMensaje).toBe('');
  });

  it('cambiar de via descarta el archivo que se habia elegido', () => {
    // Si no, el PDF queda elegido al pasar a la via Excel y se manda con el
    // filtro equivocado.
    component.elegirModo('pdf');
    component.archivoSeleccionado = archivoConNombre('extracto.pdf');

    component.elegirModo('tabla');

    expect(component.archivoSeleccionado).toBeNull();
  });

  // ------------------------------------------------------------------
  // El filtro por extension
  // ------------------------------------------------------------------

  it('deja elegir un PDF en la via PDF', () => {
    component.elegirModo('pdf');
    const input = document.createElement('input');
    input.type = 'file';
    Object.defineProperty(input, 'files', { value: [archivoConNombre('julio.pdf')] });

    component.capturarArchivo({ target: input });

    expect(component.archivoSeleccionado?.name).toBe('julio.pdf');
    expect(component.errorMensaje).toBe('');
  });

  it('rechaza un Excel en la via PDF y dice cual es la otra via', () => {
    component.elegirModo('pdf');
    const input = document.createElement('input');
    input.type = 'file';
    Object.defineProperty(input, 'files', { value: [archivoConNombre('julio.xlsx')] });

    component.capturarArchivo({ target: input });

    expect(component.archivoSeleccionado).toBeNull();
    expect(component.errorMensaje).toContain('Excel');
  });

  it('acepta los tres formatos de tabla en la via Excel', () => {
    component.elegirModo('tabla');

    for (const nombre of ['julio.xlsx', 'julio.xls', 'julio.CSV']) {
      const input = document.createElement('input');
      input.type = 'file';
      Object.defineProperty(input, 'files', { value: [archivoConNombre(nombre)] });

      component.capturarArchivo({ target: input });

      expect(component.archivoSeleccionado?.name).toBe(nombre);
      expect(component.errorMensaje).toBe('');
    }
  });

  it('rechaza un PDF en la via Excel', () => {
    component.elegirModo('tabla');
    const input = document.createElement('input');
    input.type = 'file';
    Object.defineProperty(input, 'files', { value: [archivoConNombre('julio.pdf')] });

    component.capturarArchivo({ target: input });

    expect(component.archivoSeleccionado).toBeNull();
    expect(component.errorMensaje).toContain('PDF');
  });

  it('un archivo sin extension no pasa', () => {
    component.elegirModo('pdf');
    const input = document.createElement('input');
    input.type = 'file';
    Object.defineProperty(input, 'files', { value: [archivoConNombre('extracto')] });

    component.capturarArchivo({ target: input });

    expect(component.archivoSeleccionado).toBeNull();
    expect(component.errorMensaje).not.toBe('');
  });

  // ------------------------------------------------------------------
  // Drag and drop usa el mismo camino que el click
  // ------------------------------------------------------------------

  it('soltar un archivo lo elige igual que hacer clic', () => {
    component.elegirModo('pdf');

    component.alSoltarArchivo({
      preventDefault: () => {},
      stopPropagation: () => {},
      dataTransfer: { files: [archivoConNombre('arrastrado.pdf')] }
    } as any);

    expect(component.archivoSeleccionado?.name).toBe('arrastrado.pdf');
  });

  it('arrastrar sobre la zona la marca, salir la desmarca', () => {
    component.elegirModo('pdf');
    const evento = { preventDefault: () => {}, stopPropagation: () => {} };

    component.alArrastrarSobre(evento as any);
    expect(component.arrastrandoArchivo).toBe(true);

    component.alArrastrarSalir(evento as any);
    expect(component.arrastrandoArchivo).toBe(false);
  });

  it('mientras esta cargando no acepta archivos', () => {
    component.elegirModo('pdf');
    component.cargando = true;

    component.alSoltarArchivo({
      preventDefault: () => {},
      stopPropagation: () => {},
      dataTransfer: { files: [archivoConNombre('tarde.pdf')] }
    } as any);

    expect(component.archivoSeleccionado).toBeNull();
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

/** Click en el boton cuyo texto contenga el texto buscado. */
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

async function elegirVia(titulo: string) {
  await abrirMenuImportar();
  expect(clickEnTexto(titulo)).toBe(true);
  await fixture.whenStable();
}

it('el menu muestra las dos vias en pantalla', async () => {
  await abrirMenuImportar();

  const opciones = fixture.nativeElement.querySelectorAll('.pi-file-pdf, .pi-table');
  expect(opciones.length).toBe(2);
  expect(fixture.nativeElement.textContent).toContain('Vía PDF');
  expect(fixture.nativeElement.textContent).toContain('Vía Excel o CSV');
});

it('al elegir una via se ve el apartado de carga y no las tablas', async () => {
  await elegirVia('Vía Excel o CSV');

  const texto = fixture.nativeElement.textContent;
  expect(texto).toContain('Subir extracto');
  expect(texto).toContain('Arrastrá el archivo');

  // La pantalla de conciliacion no esta montada mientras se importa: el
  // apartado tiene que ser una pantalla aparte, no un cartel arriba.
  expect(fixture.nativeElement.querySelector('table')).toBeNull();
});

it('la via PDF pide el banco y la via Excel no', async () => {
  await elegirVia('Vía PDF');
  expect(fixture.nativeElement.textContent).toContain('Banco del extracto');

  await clickEnTexto('Volver');
  await fixture.whenStable();

  await elegirVia('Vía Excel o CSV');
  expect(fixture.nativeElement.textContent).not.toContain('Banco del extracto');
  expect(fixture.nativeElement.textContent).toContain('no hace falta elegir el banco');
});

it('el input de archivo solo acepta el formato de la via elegida', async () => {
  await elegirVia('Vía PDF');
  expect(fixture.nativeElement.querySelector('#subirArchivoExtracto').getAttribute('accept'))
    .toBe('.pdf');

  await clickEnTexto('Volver');
  await fixture.whenStable();

  await elegirVia('Vía Excel o CSV');
  expect(fixture.nativeElement.querySelector('#subirArchivoExtracto').getAttribute('accept'))
    .toBe('.xlsx,.xls,.csv');
});

it('el boton de leer arranca deshabilitado y se habilita al elegir archivo', async () => {
  await elegirVia('Vía PDF');

  const leer = () => {
    const botones = fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    return Array.from(botones).find((b) => b.textContent?.trim() === 'Leer extracto')!;
  };

  expect(leer().disabled).toBe(true);

  // Se dispara el change del input real, no se mueve el estado a mano: asi
  // tambien se prueba que el input este bien enlazado al handler.
  const input = fixture.nativeElement.querySelector('#subirArchivoExtracto');
  Object.defineProperty(input, 'files', { value: [archivoConNombre('julio.pdf')] });
  input.dispatchEvent(new Event('change'));
  await fixture.whenStable();

  expect(leer().disabled).toBe(false);
  expect(fixture.nativeElement.textContent).toContain('julio.pdf');
});

it('volver deja la pantalla de conciliacion como estaba', async () => {
  await elegirVia('Vía PDF');
  await clickEnTexto('Volver');
  await fixture.whenStable();

  expect(fixture.nativeElement.textContent).not.toContain('Subir extracto');
  expect(fixture.nativeElement.textContent).toContain('Movimientos bancarios');
});

// ------------------------------------------------------------------
// Ir al backend
// ------------------------------------------------------------------

  it('manda el archivo al backend con el banco elegido', () => {
    component.elegirModo('pdf');
    component.bancoSeleccionado = 'ICBC';
    component.archivoSeleccionado = archivoConNombre('julio.pdf');

    component.procesarArchivo();
    const req = http.expectOne('http://127.0.0.1:8000/api/extractos/procesar');

    expect(req.request.body.get('banco')).toBe('ICBC');
    expect(req.request.body.get('archivo') instanceof File).toBe(true);

    req.flush({ exito: true, banco: 'ICBC', datos: [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }] });
  });

  it('la via Excel manda GENERICO como etiqueta y no exige banco', () => {
    // Ahi las columnas se reconocen por el encabezado: el banco no cambia el
    // resultado, solo aparece en los logs del backend.
    component.elegirModo('tabla');
    component.bancoSeleccionado = '';
    component.archivoSeleccionado = archivoConNombre('julio.xlsx');

    component.procesarArchivo();
    const req = http.expectOne('http://127.0.0.1:8000/api/extractos/procesar');

    expect(req.request.body.get('banco')).toBe('GENERICO');

    req.flush({ exito: true, banco: 'GENERICO', datos: [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }] });
  });

  it('la via PDF sin banco no manda nada y avisa', () => {
    component.elegirModo('pdf');
    component.bancoSeleccionado = '';
    component.archivoSeleccionado = archivoConNombre('julio.pdf');

    component.procesarArchivo();

    http.expectNone('http://127.0.0.1:8000/api/extractos/procesar');
    expect(component.errorMensaje).toContain('banco');
  });

  it('leer bien el archivo vuelve a la pantalla de conciliacion', () => {
    component.elegirModo('tabla');
    component.archivoSeleccionado = archivoConNombre('julio.xlsx');

    component.procesarArchivo();
    http.expectOne('http://127.0.0.1:8000/api/extractos/procesar').flush({
      exito: true,
      banco: 'GENERICO',
      datos: [{ fecha: '2026-07-01', concepto: 'X', debe: 1, haber: 0, saldo: 1 }]
    });

    // No te deja atrapado en la pantalla de carga.
    expect(component.enApartadoDeImportacion).toBe(false);
    expect(component.movimientosBanco.length).toBe(1);
    expect(component.infoMensaje).toContain('1 movimientos');
  });

  it('si el archivo no trae movimientos se queda en el apartado para corregirlo', () => {
    component.elegirModo('tabla');
    component.archivoSeleccionado = archivoConNombre('julio.xlsx');

    component.procesarArchivo();
    http.expectOne('http://127.0.0.1:8000/api/extractos/procesar').flush({
      exito: true,
      banco: 'GENERICO',
      datos: []
    });

    // Acá sí conviene quedarse: el mensaje dice que hay que elegir otro archivo.
    expect(component.enApartadoDeImportacion).toBe(true);
    expect(component.errorMensaje).not.toBe('');
  });
});