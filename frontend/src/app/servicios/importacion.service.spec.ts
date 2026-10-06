import { TestBed } from '@angular/core/testing';

import { ImportacionService } from './importacion.service';

describe('ImportacionService', () => {
  let servicio: ImportacionService;

  const archivo = new File([new Uint8Array([37, 80, 68, 70])], 'julio.pdf', {
    type: 'application/pdf',
  });

  beforeEach(() => {
    TestBed.configureTestingModule({});
    servicio = TestBed.inject(ImportacionService);
    servicio.limpiar();
  });

  it('arranca sin nada: ni seleccion ni movimientos', () => {
    expect(servicio.tieneSeleccion()).toBe(false);
    expect(servicio.movimientos()).toEqual([]);
    expect(servicio.archivoNombre()).toBe('');
    expect(servicio.cuentaNombre()).toBe('');
    expect(servicio.banco()).toBe('');
  });

  it('guardar la seleccion deja leer cuenta, banco y archivo', () => {
    servicio.guardar({
      cuentaId: '1105',
      cuentaNombre: '1105 - Banco BBVA',
      banco: 'SANTANDER',
      archivo,
    });

    expect(servicio.tieneSeleccion()).toBe(true);
    expect(servicio.archivoNombre()).toBe('julio.pdf');
    expect(servicio.cuentaNombre()).toBe('1105 - Banco BBVA');
    expect(servicio.banco()).toBe('SANTANDER');
  });

  it('las tarjetas de resumen suman la tabla y un NaN no las arruina', () => {
    servicio.setMovimientos([
      { fecha: '2026-07-01', debe: 0, haber: 1000, saldo: 1000 },
      { fecha: '2026-07-02', debe: 250, haber: 0, saldo: 750 },
    ] as any);

    expect(servicio.totalCreditos()).toBe(1000);
    expect(servicio.totalDebitos()).toBe(250);
    expect(servicio.diferencia()).toBe(750);

    // Number(NaN) || 0 es 0: el total se muestra y el error se avisa en la fila.
    servicio.editarMovimiento(servicio.movimientos()[0].id, { haber: NaN });
    expect(servicio.totalCreditos()).toBe(0);
  });

  it('el destino junta el banco con la cuenta para el badge del encabezado', () => {
    expect(servicio.destino()).toBe('');

    servicio.guardar({
      cuentaId: '1105',
      cuentaNombre: '1105 - Banco Galicia',
      banco: 'GAL',
      archivo,
    });

    expect(servicio.destino()).toBe('GAL · 1105 - Banco Galicia');
  });

  it('agregar un movimiento lo pone al final con la fecha de hoy', () => {
    const id = servicio.agregarMovimiento();

    const nuevo = servicio.movimientos().find((mov) => mov.id === id)!;
    expect(nuevo.concepto).toBe('');
    expect(nuevo.debe).toBe(0);
    expect(nuevo.haber).toBe(0);
    // Sin categoria: un movimiento agregado a mano todavia no fue clasificado.
    expect(nuevo.categoria).toBeNull();
    expect(nuevo.fecha).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it('editar un importe rehace la cadena de saldos', () => {
    servicio.setMovimientos([
      { fecha: '2026-07-01', debe: 0, haber: 1000, saldo: 1000 },
      { fecha: '2026-07-02', debe: 400, haber: 0, saldo: 600 },
      { fecha: '2026-07-03', debe: 150, haber: 0, saldo: 450 },
    ] as any);

    servicio.editarMovimiento(servicio.movimientos()[1].id, { debe: 500 });

    // La cadena entera corre 100 para abajo. Si el saldo se deja como venia del
    // extractor, la conciliacion despues muestra una cadena que no cierra con
    // los numeros que el usuario acaba de ver en esta pantalla.
    expect(servicio.movimientos().map((mov) => mov.saldo)).toEqual([1000, 500, 350]);
  });

  it('la cadena de saldos no arrastra errores de coma flotante', () => {
    servicio.setMovimientos([
      { fecha: '2026-07-01', debe: 0, haber: 0.1, saldo: 0.1 },
      { fecha: '2026-07-02', debe: 0, haber: 0.2, saldo: 0.3 },
    ] as any);

    // Sin redondear, 0.1 + 0.2 deja 0.30000000000000004 en pantalla y el usuario
    // cree que el extractor calculo mal.
    expect(servicio.movimientos()[1].saldo).toBe(0.3);
  });

  it('editar o quitar un id que no existe no rompe la tabla', () => {
    servicio.setMovimientos([{ fecha: '2026-07-01', debe: 0, haber: 100, saldo: 100 }] as any);

    servicio.editarMovimiento('mov-inexistente', { haber: 999 });
    servicio.quitarMovimiento('mov-inexistente');

    expect(servicio.movimientos().length).toBe(1);
    expect(servicio.movimientos()[0].haber).toBe(100);
  });

  it('quitar un movimiento rehace los saldos de los que quedan', () => {
    servicio.setMovimientos([
      { fecha: '2026-07-01', debe: 0, haber: 1000, saldo: 1000 },
      { fecha: '2026-07-02', debe: 400, haber: 0, saldo: 600 },
    ] as any);

    servicio.quitarMovimiento(servicio.movimientos()[1].id);

    expect(servicio.movimientos().length).toBe(1);
    expect(servicio.movimientos()[0].saldo).toBe(1000);
    expect(servicio.totalDebitos()).toBe(0);
  });

  it('guardar una seleccion nueva borra los movimientos de la anterior', () => {
    servicio.guardar({ cuentaId: '1', cuentaNombre: 'A', banco: 'X', archivo });
    servicio.setMovimientos([{ fecha: '2026-07-01', debe: 1, haber: 0, saldo: 1 } as any]);

    servicio.guardar({ cuentaId: '2', cuentaNombre: 'B', banco: 'Y', archivo });

    expect(servicio.movimientos()).toEqual([]);
  });

  it('setMovimientos agrega un id sin pisar los datos del extractor', () => {
    servicio.setMovimientos([
      { fecha: '2026-07-01', concepto: 'COBRO', debe: 0, haber: 100, saldo: 100 },
      { fecha: '2026-07-02', concepto: 'PAGO', debe: 40, haber: 0, saldo: 60 },
    ] as any);

    const [primero, segundo] = servicio.movimientos();
    // El id se genera aca porque el extractor no lo manda, y el *ngFor
    // trackea por identidad: sin el, Angular recrea el <tr> en cada cambio.
    expect(primero.id).toBeTruthy();
    expect(segundo.id).toBeTruthy();
    expect(primero.id).not.toBe(segundo.id);
    expect(primero.concepto).toBe('COBRO');
    expect(segundo.saldo).toBe(60);
    expect(servicio.cantidadMovimientos()).toBe(2);
  });

  it('limpiar borra la seleccion y los movimientos', () => {
    servicio.guardar({ cuentaId: '1', cuentaNombre: 'A', banco: 'X', archivo });
    servicio.setMovimientos([{ fecha: '2026-07-01', debe: 1, haber: 0, saldo: 1 } as any]);

    servicio.limpiar();

    expect(servicio.tieneSeleccion()).toBe(false);
    expect(servicio.movimientos()).toEqual([]);
    expect(servicio.cantidadMovimientos()).toBe(0);
  });

  it('formatearImporte muestra los centavos con el signo adelante', () => {
    expect(servicio.formatearImporte(1234567.891)).toBe('1.234.567,89');
    expect(servicio.formatearImporte(-250.5)).toBe('-250,50');
    expect(servicio.formatearImporte(0)).toBe('');
    expect(servicio.formatearImporte(null)).toBe('');
  });
});
