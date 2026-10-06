import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { VerificarImportacionComponent } from './verificar-importacion';
import { ImportacionService } from '../../servicios/importacion.service';

describe('VerificarImportacionComponent', () => {
  let fixture: any;
  let component: VerificarImportacionComponent;
  let importacion: ImportacionService;
  let router: Router;

  function archivo(): File {
    return new File([new Uint8Array([37, 80, 68, 70])], 'julio.pdf', { type: 'application/pdf' });
  }

  /** Siembra el servicio con una seleccion y unos movimientos, y crea la pantalla. */
  function armar(movimientos?: any[]): void {
    importacion.guardar({
      cuentaId: '1105',
      cuentaNombre: '1105 - Banco Galicia - 0001775-0 174-6',
      banco: 'GAL',
      archivo: archivo(),
    });
    importacion.setMovimientos(
      movimientos ?? [
        { fecha: '2026-07-01', concepto: 'COBRO CLIENTE A', debe: 0, haber: 1000, saldo: 1000 },
        { fecha: '2026-07-02', concepto: 'PAGO PROVEEDOR', debe: 400, haber: 0, saldo: 600 },
        { fecha: '2026-07-03', concepto: 'COMISION', debe: 150, haber: 0, saldo: 450 },
      ],
    );

    vi.spyOn(router, 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(VerificarImportacionComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  beforeEach(async () => {
    // El modulo se configura una sola vez, acá: configurar despues de haber
    // inyectado algo tira "the test module has already been instantiated".
    await TestBed.configureTestingModule({
      imports: [VerificarImportacionComponent],
      providers: [provideRouter([])],
    }).compileComponents();

    importacion = TestBed.inject(ImportacionService);
    importacion.limpiar();
    router = TestBed.inject(Router);
  });

  // ------------------------------------------------------------------
  // Entrada a la pantalla
  // ------------------------------------------------------------------

  it('sin seleccion previa manda a /importar-pdf y no muestra nada', () => {
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    const recienCreado = TestBed.createComponent(VerificarImportacionComponent);
    recienCreado.detectChanges();

    expect(navegar).toHaveBeenCalledWith(['/importar-pdf']);
    expect(recienCreado.componentInstance.movimientos().length).toBe(0);
    recienCreado.destroy();
  });

  it('muestra el destino del import en el badge del encabezado', () => {
    armar();

    expect(component.destino()).toBe('GAL · 1105 - Banco Galicia - 0001775-0 174-6');
    expect(fixture.nativeElement.textContent).toContain('Se va a importar en');
  });

  it('el enlace de ayuda esta y no rompe sin destinatario', async () => {
    armar();

    const enlace = fixture.nativeElement.querySelector('a[href^="mailto:"]');
    expect(enlace.textContent).toContain('¿Algo no se leyó bien? Contanos');
    expect(enlace.getAttribute('href')).toContain('subject=');
  });

  // ------------------------------------------------------------------
  // Tarjetas de resumen
  // ------------------------------------------------------------------

  it('las tarjetas suman los importes de la tabla', async () => {
    armar();

    expect(component.totalCreditos()).toBe(1000);
    expect(component.totalDebitos()).toBe(550);
    expect(component.diferencia()).toBe(450);
  });

  it('las tarjetas se actualizan al editar un importe', async () => {
    armar();
    const id = importacion.movimientos()[0].id;

    component.editar(importacion.movimientos()[0], 'credito', '2500');
    component.confirmarBorrador();
    fixture.detectChanges();

    expect(importacion.movimientos()[0].haber).toBe(2500);
    expect(component.totalCreditos()).toBe(2500);
    expect(component.diferencia()).toBe(1950);
    expect(id).toBeTruthy();
  });

  it('un importe no numerico no arruina el total', async () => {
    armar();

    importacion.editarMovimiento(importacion.movimientos()[0].id, { haber: NaN });

    // Number(NaN) || 0 es 0: el total se muestra, y el error se avisa en la fila.
    expect(component.totalCreditos()).toBe(0);
    expect(component.hayErrores()).toBe(true);
  });

  // ------------------------------------------------------------------
  // Estado vacio y pie de tabla
  // ------------------------------------------------------------------

  it('sin movimientos muestra el estado vacio y el pie en cero', async () => {
    armar([]);

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('No hay registros para mostrar.');
    expect(texto).toContain('Movimientos a importar: 0');
  });

  it('el pie dice cuantos movimientos se van a importar', async () => {
    armar();

    expect(fixture.nativeElement.textContent).toContain('Movimientos a importar: 3');
  });

  // ------------------------------------------------------------------
  // Edicion en linea
  // ------------------------------------------------------------------

  it('escribir sobre una celda la deja lista para editar', async () => {
    armar();
    const mov = importacion.movimientos()[0];

    fixture.nativeElement.querySelectorAll('tbody tr')[0].querySelectorAll('td button')[1].click();
    fixture.detectChanges();

    expect(component.borrador()).toEqual({ id: mov.id, campo: 'concepto', valor: 'COBRO CLIENTE A' });
    expect(fixture.nativeElement.querySelector('input')).toBeTruthy();
  });

  it('un importe con punto de miles y coma se lee como 1234.56', async () => {
    armar();

    expect(component.parsearImporte('1.234,56')).toBe(1234.56);
    expect(component.parsearImporte('1234.56')).toBe(1234.56);
    expect(component.parsearImporte('1.234,56')).toBe(1234.56);
    expect(component.parsearImporte('')).toBe(0);
  });

  it('confirma un importe escrito a la argentina', async () => {
    armar();
    const mov = importacion.movimientos()[1];

    component.editar(mov, 'debito', '1.234,56');
    component.confirmarBorrador();
    fixture.detectChanges();

    expect(importacion.movimientos()[1].debe).toBe(1234.56);
    expect(component.totalDebitos()).toBe(1384.56);
  });

  it('un importe que no es numero no se guarda y avisa en la celda', async () => {
    armar();
    const mov = importacion.movimientos()[0];
    const antes = mov.haber;

    component.editar(mov, 'credito', 'mil');
    component.confirmarBorrador();
    fixture.detectChanges();

    expect(importacion.movimientos()[0].haber).toBe(antes);
    expect(component.errorCelda()).toContain('no es un importe válido');
    // La celda sigue abierta para corregir, no se pierde lo tipeado.
    expect(component.borrador()?.valor).toBe('mil');
  });

  it('una fecha imposible no se guarda', async () => {
    armar();
    const mov = importacion.movimientos()[0];

    component.editar(mov, 'fecha', '2026-02-31');
    component.confirmarBorrador();

    expect(importacion.movimientos()[0].fecha).toBe('2026-07-01');
    expect(component.errorCelda()).toContain('válida');
  });

  it('Escape deja el valor como estaba', async () => {
    armar();
    const mov = importacion.movimientos()[0];

    component.editar(mov, 'concepto', 'OTRO COSA');
    component.cancelarBorrador();

    expect(importacion.movimientos()[0].concepto).toBe('COBRO CLIENTE A');
    expect(component.borrador()).toBeNull();
    expect(component.errorCelda()).toBe('');
  });

  it('el saldo de la cadena se rehace al editar un importe', async () => {
    armar();

    component.editar(importacion.movimientos()[1], 'debito', '500');
    component.confirmarBorrador();

    // El extractor cerro en 450 con un debito de 400 en la segunda fila. Si ese
    // debito pasa a 500, la cadena entera corre 100 para abajo y la ultima fila
    // tiene que quedar en 350, no en el 450 viejo.
    expect(importacion.movimientos()[2].saldo).toBe(350);
    // Y el saldo de la fila editada tampoco puede quedar en el 600 viejo.
    expect(importacion.movimientos()[1].saldo).toBe(500);
  });

  // ------------------------------------------------------------------
  // Agregar y quitar
  // ------------------------------------------------------------------

  it('agregar un movimiento lo suma a la tabla, a los totales y al pie', async () => {
    armar();

    component.agregarMovimiento();
    fixture.detectChanges();

    expect(importacion.movimientos().length).toBe(4);
    expect(component.totalCreditos()).toBe(1000);
    expect(fixture.nativeElement.textContent).toContain('Movimientos a importar: 4');
    // La celda del concepto queda lista para escribir.
    expect(component.borrador()?.campo).toBe('concepto');
  });

  it('quitar un movimiento lo saca de la tabla y recalcula los totales', async () => {
    armar();

    component.quitarMovimiento(importacion.movimientos()[1].id);
    fixture.detectChanges();

    expect(importacion.movimientos().length).toBe(2);
    expect(component.totalDebitos()).toBe(150);
  });

  // ------------------------------------------------------------------
  // Menu de columna y columnas ocultas
  // ------------------------------------------------------------------

  it('los tres puntitos abren el menu de la columna', async () => {
    armar();

    const puntitos = fixture.nativeElement.querySelectorAll('thead button[aria-label]');
    puntitos[0].click();
    fixture.detectChanges();

    expect(component.menuAbierto()).toBe('fecha');
    expect(fixture.nativeElement.textContent).toContain('Ordenar de menor a mayor');
    expect(fixture.nativeElement.textContent).toContain('Ocultar columna');
  });

  it('ordenar por columna ordena de verdad, y el segundo click da vuelta', async () => {
    armar();

    component.ordenarPor('concepto');
    fixture.detectChanges();
    expect(component.filasVisibles().map((m) => m.concepto)[0]).toBe('COBRO CLIENTE A');

    component.ordenarPor('concepto');
    fixture.detectChanges();
    expect(component.sentidoOrden('concepto')).toBe('desc');
    expect(component.filasVisibles().map((m) => m.concepto)[0]).toBe('PAGO PROVEEDOR');
  });

  it('ordenar por importe ordena por numero, no por texto', async () => {
    armar([{ fecha: '2026-07-01', concepto: 'A', debe: 0, haber: 90, saldo: 90 },
                { fecha: '2026-07-02', concepto: 'B', debe: 1000, haber: 0, saldo: -910 }]);

    component.ordenarPor('debito');
    fixture.detectChanges();

    expect(component.filasVisibles().map((m) => m.debe)).toEqual([0, 1000]);
  });

  it('ocultar una columna la saca de la tabla pero no de los totales', async () => {
    armar();

    component.ocultarColumna('concepto');
    fixture.detectChanges();

    expect(component.columnasVisibles().length).toBe(3);
    expect(component.columnasVisibles().map((c) => c.clave)).not.toContain('concepto');
    // Ocultar no es borrar: el total sigue contando los 1000 del credito.
    expect(component.totalCreditos()).toBe(1000);
    expect(fixture.nativeElement.textContent).not.toContain('PAGO PROVEEDOR');
  });

  it('no se puede ocultar la ultima columna', async () => {
    armar();

    for (const columna of component.columnas) component.ocultarColumna(columna.clave);

    expect(component.columnasVisibles().length).toBe(1);
  });

  it('las columnas ocultas se pueden volver a mostrar', async () => {
    armar();

    component.ocultarColumna('fecha');
    component.mostrarColumna('fecha');
    fixture.detectChanges();

    expect(component.columnasVisibles().length).toBe(4);
  });

  // ------------------------------------------------------------------
  // Confirmar y cancelar
  // ------------------------------------------------------------------

  it('confirmar deja los movimientos en el servicio y va a la conciliacion', async () => {
    armar();

    component.confirmar();

    // No se limpia: ese limpiar es el gesto con el que la conciliacion los toma.
    expect(importacion.movimientos().length).toBe(3);
    expect(router.navigate).toHaveBeenCalledWith(['/']);
  });

  it('sin movimientos no se puede confirmar', async () => {
    armar([]);

    expect(component.puedeConfirmar()).toBe(false);
    component.confirmar();

    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('una fila con error no deja confirmar', async () => {
    armar();

    importacion.editarMovimiento(importacion.movimientos()[0].id, { concepto: '  ' });
    fixture.detectChanges();

    expect(component.hayErrores()).toBe(true);
    expect(component.puedeConfirmar()).toBe(false);

    component.confirmar();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('el boton confirmar aparece deshabilitado sin registros', async () => {
    armar([]);

    const botones = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    const confirmar = botones.find((b) => b.textContent?.trim() === 'Confirmar importación')!;

    expect(confirmar.disabled).toBe(true);
  });

  it('cancelar descarta todo lo leido y vuelve a la conciliacion', async () => {
    armar();

    component.cancelar();

    expect(importacion.tieneSeleccion()).toBe(false);
    expect(importacion.movimientos().length).toBe(0);
    expect(router.navigate).toHaveBeenCalledWith(['/']);
  });
});
