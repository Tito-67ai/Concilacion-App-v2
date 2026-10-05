import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ImportacionService } from '../../servicios/importacion.service';
import { ImportarPdfComponent } from '../importar-pdf/importar-pdf';
import { VerificarImportacionComponent } from './verificar-importacion';

describe('VerificarImportacionComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [VerificarImportacionComponent],
      // Redirige a /importar-pdf si no hay nada seleccionado.
      providers: [provideRouter([{ path: 'importar-pdf', component: ImportarPdfComponent }])],
    }).compileComponents();
  });

  /** Deja el servicio con una selección válida (si no, el componente redirige). */
  function prepararConMovimientos() {
    const importacion = TestBed.inject(ImportacionService);
    importacion.guardar({
      cuentaId: '1105',
      cuentaNombre: '1105 - Banco Galicia CC$ 0001775-0 174-6',
      archivo: new File(['%PDF-1.4'], 'extracto.pdf', { type: 'application/pdf' }),
    });
    importacion.setMovimientos([
      { fecha: '2026-09-02', concepto: 'Transferencia de Sergio', credito: 1500.5, debito: null },
      { fecha: '2026-09-03', concepto: 'Pago de proveedores', credito: null, debito: 250.25 },
    ]);
    return importacion;
  }

  it('should create', () => {
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('suma créditos y débitos para las tarjetas de resumen', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;

    expect(component.totalCreditos()).toBe(1500.5);
    expect(component.totalDebitos()).toBe(250.25);
    expect(component.diferencia()).toBe(1250.25);
    expect(component.creditosFormateados()).toBe('1.500,50');
    expect(component.cantidadMovimientos()).toBe(2);
    expect(component.puedeConfirmar()).toBe(true);

    importacion.limpiarMovimientos();
  });

  it('recalcula los totales al editar en línea', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    component.cambiarImporte(primero, 'credito', '2000,25');

    expect(component.totalCreditos()).toBe(2000.25);
    importacion.limpiarMovimientos();
  });

  it('mantiene la identidad de la fila al editar (si no, el input pierde el foco)', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    // El *ngFor trackea por identidad: si la fila fuera otro objeto, Angular
    // recrearía el <tr> en cada tecla y solo se podría escribir un carácter.
    component.cambiarConcepto(primero, 'T');
    expect(component.movimientosOrdenados()[0]).toBe(primero);

    component.cambiarConcepto(primero, 'Trans');
    expect(component.movimientosOrdenados()[0]).toBe(primero);
    expect(component.movimientosOrdenados()[0].concepto).toBe('Trans');

    importacion.limpiarMovimientos();
  });

  it('no deja confirmar si algún movimiento tiene errores', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    // Vaciar el concepto deja la fila incompleta
    component.cambiarConcepto(primero, '   ');

    expect(component.hayErrores()).toBe(true);
    expect(component.puedeConfirmar()).toBe(false);
    expect(component.error(primero, 'concepto')).toBe('Cargá el concepto');

    importacion.limpiarMovimientos();
  });

  it('avisa si un movimiento tiene crédito y débito a la vez', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const conDebito = component.movimientosOrdenados()[1];

    component.cambiarImporte(conDebito, 'credito', '100');

    expect(component.error(conDebito, 'importe')).toBe('No puede tener crédito y débito a la vez');
    expect(component.puedeConfirmar()).toBe(false);

    importacion.limpiarMovimientos();
  });

  it('marca en amarillo los formatos dudosos sin bloquear la importación', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    // Más de 2 decimales: sospechoso de una mala lectura del PDF
    importacion.actualizarMovimiento(primero.id, { credito: 1234.567 });

    expect(component.aviso(primero, 'credito')).toBe('Tiene más de 2 decimales');
    expect(component.tieneAvisos(primero)).toBe(true);
    expect(component.tieneErrores(primero)).toBe(false);
    expect(component.estadoFila(primero)).toBe('aviso');
    // Amarillo es informativo: se puede confirmar igual
    expect(component.puedeConfirmar()).toBe(true);

    importacion.limpiarMovimientos();
  });

  it('avisa cuando el importe es cero', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    importacion.actualizarMovimiento(primero.id, { credito: 0 });

    expect(component.aviso(primero, 'credito')).toBe('El importe es cero, revisá el PDF');
    expect(component.estadoFila(primero)).toBe('aviso');

    importacion.limpiarMovimientos();
  });

  it('el error bloqueante pisa al aviso de formato', () => {
    const importacion = prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    importacion.actualizarMovimiento(primero.id, { credito: 0, concepto: '' });

    expect(component.tieneErrores(primero)).toBe(true);
    expect(component.estadoFila(primero)).toBe('error');

    importacion.limpiarMovimientos();
  });

  it('no deja confirmar una tabla sin movimientos', () => {
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;

    expect(component.cantidadMovimientos()).toBe(0);
    expect(component.puedeConfirmar()).toBe(false);
    expect(component.creditosFormateados()).toBe('0,00');
  });

  it('agrega y elimina movimientos', () => {
    prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;

    const nuevo = component.agregarMovimiento();
    expect(component.cantidadMovimientos()).toBe(3);
    expect(component.editandoId()).toBe(nuevo.id);

    component.eliminar(nuevo);
    expect(component.cantidadMovimientos()).toBe(2);

    TestBed.inject(ImportacionService).limpiarMovimientos();
  });

  it('"Cancelar edición" revierte los cambios de la fila', () => {
    prepararConMovimientos();
    const fixture = TestBed.createComponent(VerificarImportacionComponent);
    const component = fixture.componentInstance;
    const primero = component.movimientosOrdenados()[0];

    component.editar(primero);
    component.cambiarConcepto(primero, 'Texto a medias');
    expect(component.totalCreditos()).toBe(1500.5);

    component.cancelarEdicion();

    expect(component.editandoId()).toBe(null);
    // Vuelve el concepto original y los totales no se mueven
    expect(component.movimientosOrdenados()[0].concepto).toBe('Transferencia de Sergio');

    TestBed.inject(ImportacionService).limpiarMovimientos();
  });
});
