import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { ImportarPdfComponent } from './importar-pdf';
import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

describe('ImportarPdfComponent', () => {
  let component: ImportarPdfComponent;
  let http: HttpTestingController;
  let router: Router;
  let importacion: ImportacionService;

  function pdf(nombre = 'julio.pdf', bytes = 4): File {
    // Los bytes %PDF no importan para el validador del formulario (que mira
    // extension y tamaño), pero los cuatro de la cabecera %PDF se usan para que
    // el objeto sea creible.
    const contenido = new Uint8Array(bytes);
    contenido.set([37, 80, 68, 70], 0);
    return new File([contenido], nombre, { type: 'application/pdf' });
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ImportarPdfComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    importacion = TestBed.inject(ImportacionService);
    importacion.limpiar();
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    vi.spyOn(router, 'navigate').mockResolvedValue(true);

    component = TestBed.createComponent(ImportarPdfComponent).componentInstance;
    http.expectOne(`${API}/extractos/bancos`).flush({
      bancos: ['SANTANDER', 'ICBC', 'GENERICO'],
      formatos: ['pdf'],
    });
  });

  afterEach(() => http.verify());

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('preselecciona un banco de verdad y no el generico', () => {
    // El generico es el extractor de rescate: dejarlo por defecto seria
    // saltarse el parser del banco sin querer.
    expect(component.formulario.controls.banco.value).toBe('SANTANDER');
  });

  it('el CTA arranca deshabilitado: falta cuenta y archivo', () => {
    expect(component.habilitado).toBe(false);
  });

  it('con cuenta y PDF valido se habilita el CTA', () => {
    component.formulario.controls.cuentaId.setValue('1105');
    component.formulario.controls.archivo.setValue(pdf());

    expect(component.habilitado).toBe(true);
  });

  it('rechaza un archivo que no es PDF', () => {
    component.formulario.controls.cuentaId.setValue('1105');
    component.formulario.controls.archivo.setValue(new File([new Uint8Array([1, 2])], 'julio.xlsx'));

    expect(component.formulario.controls.archivo.hasError('formato')).toBe(true);
    expect(component.habilitado).toBe(false);
    expect(component.errorArchivo).toContain('PDF');
  });

  it('rechaza un PDF de mas de 10 MB', () => {
    component.formulario.controls.archivo.setValue(pdf('enorme.pdf', 11 * 1024 * 1024));

    expect(component.formulario.controls.archivo.hasError('tamano')).toBe(true);
    expect(component.errorArchivo).toContain('10 MB');
  });

  it('el tamano del archivo se muestra en KB y en MB', () => {
    component.formulario.controls.archivo.setValue(pdf('chico.pdf', 2048));
    expect(component.tamanoArchivo).toBe('2 KB');

    component.formulario.controls.archivo.setValue(pdf('grande.pdf', 3 * 1024 * 1024));
    expect(component.tamanoArchivo).toBe('3.0 MB');
  });

  it('soltar un archivo en la zona lo elige igual que hacer clic', () => {
    component.formulario.controls.archivo.setValue(pdf());
    expect(component.nombreArchivo).toBe('julio.pdf');

    component.formulario.controls.archivo.setValue(null);
    component.alArrastrarSobre({ preventDefault: () => {}, stopPropagation: () => {} } as any);
    expect(component.arrastrando()).toBe(true);
    component.alSalirZona({ preventDefault: () => {}, stopPropagation: () => {} } as any);
    expect(component.arrastrando()).toBe(false);

    component.alSoltar({
      preventDefault: () => {},
      stopPropagation: () => {},
      dataTransfer: { files: [pdf('agosto.pdf')] },
    } as any);
    expect(component.nombreArchivo).toBe('agosto.pdf');
  });

  it('quitar el archivo lo saca del formulario y del input', () => {
    component.formulario.controls.archivo.setValue(pdf());
    component.quitarArchivo({ stopPropagation: () => {} } as any);

    expect(component.nombreArchivo).toBeNull();
  });

  it('previsualizar guarda la seleccion y va a /procesando-pdf', () => {
    component.formulario.controls.cuentaId.setValue('1105');
    component.formulario.controls.archivo.setValue(pdf());

    component.previsualizar();

    const seleccion = importacion.seleccion();
    expect(seleccion?.banco).toBe('SANTANDER');
    expect(seleccion?.cuentaId).toBe('1105');
    expect(seleccion?.archivo.name).toBe('julio.pdf');
    expect(router.navigate).toHaveBeenCalledWith(['/procesando-pdf']);
  });

  it('previsualizar sin archivo no navega, solo toca los controles', () => {
    component.previsualizar();

    expect(router.navigate).not.toHaveBeenCalled();
    expect(component.formulario.controls.cuentaId.touched).toBe(true);
  });

  it('volver deja la conciliacion sin movimientos cargados', () => {
    component.volver();

    expect(router.navigate).toHaveBeenCalledWith(['/']);
    expect(importacion.tieneSeleccion()).toBe(false);
  });

  it('si los bancos no cargan avisa en pantalla y no habilita el CTA', () => {
    const recienCreado = TestBed.createComponent(ImportarPdfComponent).componentInstance;
    http.expectOne(`${API}/extractos/bancos`).flush('sin bancos', {
      status: 500,
      statusText: 'Server Error',
    });

    expect(recienCreado.errorBancos()).toContain('backend');
    expect(recienCreado.habilitado).toBe(false);
  });
});
