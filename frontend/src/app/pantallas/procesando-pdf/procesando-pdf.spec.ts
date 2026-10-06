import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { ProcesandoPdfComponent } from './procesando-pdf';
import { ImportacionService } from '../../servicios/importacion.service';

const API = 'http://127.0.0.1:8000/api';

/**
 * Estos tests miran los estados del stepper, no el reloj: el reloj real hace
 * esperar tres minutos, y lo que importa aca es que cada paso se mueva por un
 * evento de la request y no por un timer.
 */
describe('ProcesandoPdfComponent', () => {
  let http: HttpTestingController;
  let router: Router;
  let importacion: ImportacionService;

  beforeEach(async () => {
    // El componente usa setInterval para el cronometro. Con timers reales cada
    // test tendria que esperar un segundo por tick, y el unico reloj que
    // importa aca es el estado del stepper.
    vi.useFakeTimers();

    await TestBed.configureTestingModule({
      imports: [ProcesandoPdfComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    }).compileComponents();

    importacion = TestBed.inject(ImportacionService);
    importacion.limpiar();
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Guarda una seleccion en el servicio y crea el componente que la consume. */
  function armarConArchivo(): { fixture: any; component: ProcesandoPdfComponent } {
    importacion.guardar({
      cuentaId: '1105',
      cuentaNombre: '1105 - Banco BBVA',
      banco: 'SANTANDER',
      archivo: new File([new Uint8Array([37, 80, 68, 70])], 'julio.pdf', {
        type: 'application/pdf',
      }),
    });
    vi.spyOn(router, 'navigate').mockResolvedValue(true);
    const fixture = TestBed.createComponent(ProcesandoPdfComponent);
    return { fixture, component: fixture.componentInstance };
  }

  it('sin seleccion previa manda a /importar-pdf y no pide nada', () => {
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    const fixture = TestBed.createComponent(ProcesandoPdfComponent);

    expect(navegar).toHaveBeenCalledWith(['/importar-pdf']);
    http.expectNone(`${API}/extractos/procesar`);
    fixture.destroy();
  });

  it('arranca con el primer paso en curso y los otros pendientes', () => {
    const { fixture, component } = armarConArchivo();

    expect(component.estados()).toEqual(['cargando', 'pendiente', 'pendiente']);
    expect(component.pasoEnCurso()).toBe(0);
    expect(component.finalizado()).toBe(false);

    const req = http.expectOne(`${API}/extractos/procesar`);
    expect(req.request.body.get('banco')).toBe('SANTANDER');
    expect(req.request.body.get('archivo') instanceof File).toBe(true);
    req.flush({ exito: true, datos: [] });
    fixture.destroy();
  });

  it('el primer paso se completa cuando el cuerpo finished de subirse', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    // Subida a medias: el paso 1 sigue en curso.
    req.event({ type: 1, loaded: 1024, total: 2048 });
    fixture.detectChanges();
    expect(component.envioProgreso()).toBe(50);
    expect(component.estados()[0]).toBe('cargando');

    // Cuerpo completo: ahora si, el servidor arranco a abrir el PDF.
    req.event({ type: 1, loaded: 2048, total: 2048 });
    fixture.detectChanges();
    expect(component.envioProgreso()).toBe(100);
    expect(component.estados()[0]).toBe('completado');
    expect(component.estados()[1]).toBe('cargando');
    expect(component.progreso()).toBe(33);

    req.flush({ exito: true, datos: [] });
    fixture.destroy();
  });

  it('la respuesta deja los tres pasos en verde y pasa los movimientos al servicio', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    req.flush({
      exito: true,
      banco: 'SANTANDER',
      datos: [
        { fecha: '2026-07-01', concepto: 'COBRO A', debe: 0, haber: 100, saldo: 100 },
        { fecha: '2026-07-02', concepto: 'PAGO B', debe: 40, haber: 0, saldo: 60 },
      ],
    });
    fixture.detectChanges();

    expect(component.finalizado()).toBe(true);
    expect(component.progreso()).toBe(100);
    expect(importacion.movimientos().length).toBe(2);
    // No va directo a la conciliacion: antes hay que dejar revisar lo leido.
    expect(router.navigate).toHaveBeenCalledWith(['/verificar-importacion']);
    fixture.destroy();
  });

  it('una respuesta 200 sin movimientos deja el paso en rojo con el motivo', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    req.flush({ exito: true, banco: 'SANTANDER', datos: [] });
    fixture.detectChanges();

    // El fallo tiene que sobrevivir al complete de la request: sin el chequeo,
    // el paso volvia a verde y el mensaje de error quedaba pegado abajo.
    expect(component.fallo()).toBe(true);
    expect(component.finalizado()).toBe(false);
    expect(component.errorMensaje()).toBe('El archivo se leyó pero no tiene movimientos.');
    expect(router.navigate).not.toHaveBeenCalled();
    fixture.destroy();
  });

  it('un error del backend se muestra el motivo que mando, no un generico', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    req.flush(
      { detail: 'El PDF no se pudo leer: está protegido con contraseña.' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    fixture.detectChanges();

    expect(component.fallo()).toBe(true);
    expect(component.errorMensaje()).toContain('contraseña');
    fixture.destroy();
  });

  it('un error sin mensaje usa un texto que dice que se revise el backend', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    req.error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect(component.fallo()).toBe(true);
    expect(component.errorMensaje()).toBe('No se pudo procesar el PDF.');
    fixture.destroy();
  });

  it('el cronometro corre mientras espera al backend', () => {
    const { fixture, component } = armarConArchivo();
    const req = http.expectOne(`${API}/extractos/procesar`);

    expect(component.tiempoTranscurrido()).toBe('00:00');
    vi.advanceTimersByTime(65000);

    expect(component.segundosTranscurridos()).toBe(65);
    expect(component.tiempoTranscurrido()).toBe('01:05');

    req.flush({ exito: true, datos: [] });
    fixture.destroy();
  });

  it('cancelar limpia la seleccion y vuelve a la conciliacion', () => {
    const { fixture, component } = armarConArchivo();
    http.expectOne(`${API}/extractos/procesar`);

    component.cancelar();

    expect(importacion.tieneSeleccion()).toBe(false);
    expect(router.navigate).toHaveBeenCalledWith(['/']);
    // Cancelar abandona la pantalla sin dejar el stepper en "procesando" para
    // siempre: si el usuario vuelve, arranca de cero.
    expect(component.finalizado()).toBe(false);
    fixture.destroy();
  });

  it('reintentar manda a /importar-pdf para elegir el archivo otra vez', () => {
    const { fixture, component } = armarConArchivo();
    http.expectOne(`${API}/extractos/procesar`).flush({ exito: true, datos: [] });

    component.reintentar();

    expect(importacion.tieneSeleccion()).toBe(false);
    expect(router.navigate).toHaveBeenCalledWith(['/importar-pdf']);
    fixture.destroy();
  });

  it('el cronometro se detiene al salir de la pantalla', () => {
    const { fixture, component } = armarConArchivo();
    http.expectOne(`${API}/extractos/procesar`).flush({ exito: true, datos: [] });

    fixture.destroy();
    vi.advanceTimersByTime(5000);

    expect(component.segundosTranscurridos()).toBe(0);
  });
});
