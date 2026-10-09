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

  it('las tarjetas muestran el saldo inicial y el saldo final del extracto', async () => {
    armar([
      { fecha: '2026-07-01', concepto: 'COBRO CLIENTE A', debe: 0, haber: 1000, saldo: 1500 },
      { fecha: '2026-07-02', concepto: 'PAGO PROVEEDOR', debe: 400, haber: 0, saldo: 1100 },
    ]);

    expect(component.saldoInicial()).toBe(500);
    expect(component.saldoFinal()).toBe(1100);

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Saldo inicial');
    expect(texto).toContain('Saldo final');
    expect(texto).toContain('500,00');
    expect(texto).toContain('1.100,00');
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
  // Busqueda
  // ------------------------------------------------------------------

  it('la barra de busqueda filtra las filas sin tocar los totales', async () => {
    armar();

    component.busqueda.set('proveedor');
    fixture.detectChanges();

    expect(component.filasVisibles().length).toBe(1);
    expect(component.filasVisibles()[0].concepto).toBe('PAGO PROVEEDOR');
    // La fila que no coincide no se pinta, pero los totales siguen contando todo.
    expect(fixture.nativeElement.textContent).not.toContain('COBRO CLIENTE A');
    expect(component.totalCreditos()).toBe(1000);
    expect(fixture.nativeElement.textContent).toContain('1 de 3 movimientos coinciden');
  });

  it('la barra de busqueda encuentra por fecha tambien', async () => {
    armar();

    component.busqueda.set('2026-07-02');
    fixture.detectChanges();

    expect(component.filasVisibles().map((m) => m.concepto)).toEqual(['PAGO PROVEEDOR']);
  });

  it('limpiar la busqueda devuelve todas las filas', async () => {
    armar();

    component.busqueda.set('proveedor');
    component.busqueda.set('');
    fixture.detectChanges();

    expect(component.filasVisibles().length).toBe(3);
  });

  // ------------------------------------------------------------------
  // Filtros estilo Excel
  // ------------------------------------------------------------------

  it('el embudo lista los valores unicos de la columna, ordenados', async () => {
    armar();

    expect(component.valoresUnicos('concepto')).toEqual([
      'COBRO CLIENTE A',
      'COMISION',
      'PAGO PROVEEDOR',
    ]);
    // Los importes se ordenan por su valor, no por su texto, y el cero se
    // agrupa como "(Sin importe)".
    expect(component.valoresUnicos('credito')).toEqual(['', '1.000,00']);
    expect(component.valoresUnicos('fecha')).toEqual(['01/07/2026', '02/07/2026', '03/07/2026']);
  });

  it('marcar un valor filtra las filas sin tocar los totales', async () => {
    armar();

    component.alternarValor('concepto', 'PAGO PROVEEDOR');
    fixture.detectChanges();

    expect(component.filasVisibles().map((m) => m.concepto)).toEqual(['PAGO PROVEEDOR']);
    expect(component.hayFiltros()).toBe(true);
    expect(component.tieneFiltro('concepto')).toBe(true);
    // Filtrar no es borrar: la tarjeta sigue contando los 1000 del credito.
    expect(component.totalCreditos()).toBe(1000);
  });

  it('desmarcar todos los valores vuelve a mostrar todo', async () => {
    armar();

    const valores = component.valoresUnicos('concepto');
    for (const valor of valores) component.alternarValor('concepto', valor);
    expect(component.filasVisibles().length).toBe(3);

    for (const valor of valores) component.alternarValor('concepto', valor);
    expect(component.hayFiltros()).toBe(false);
    expect(component.filasVisibles().length).toBe(3);
  });

  it('seleccionar todo marca y desmarca el conjunto entero', async () => {
    armar();

    component.alternarValor('concepto', 'PAGO PROVEEDOR');
    component.alternarTodos('concepto');
    expect(component.todosSeleccionados('concepto')).toBe(true);
    expect(component.filasVisibles().length).toBe(3);

    component.alternarTodos('concepto');
    expect(component.todosSeleccionados('concepto')).toBe(true); // sin filtro = todo
    expect(component.hayFiltros()).toBe(false);
    expect(component.filasVisibles().length).toBe(3);
  });

  it('el filtro y la busqueda se combinan', async () => {
    armar();

    component.alternarValor('concepto', 'COBRO CLIENTE A');
    component.alternarValor('concepto', 'PAGO PROVEEDOR');
    component.busqueda.set('CLIENTE');
    fixture.detectChanges();

    expect(component.filasVisibles().map((m) => m.concepto)).toEqual(['COBRO CLIENTE A']);
  });

  it('el resaltado parte el texto en coincidencias y resto', () => {
    armar();
    component.busqueda.set('PAGO');

    expect(component.partesResaltadas('PAGO PROVEEDOR')).toEqual([
      { texto: 'PAGO', esCoincidencia: true },
      { texto: ' PROVEEDOR', esCoincidencia: false },
    ]);
    // Las partes siempre recomponen el texto original, no se pierde nada.
    expect(component.partesResaltadas('PAGO PROVEEDOR').map((p) => p.texto).join('')).toBe('PAGO PROVEEDOR');
  });

  it('el resaltado marca todas las apariciones, sin importar mayusculas', () => {
    armar();
    component.busqueda.set('o');

    const partes = component.partesResaltadas('PAGO PROVEEDOR');
    const coincidencias = partes.filter((p) => p.esCoincidencia);
    // Las tres letras "o" de "PAGO PROVEEDOR" quedan remarcadas por separado,
    // conservando la grafia original del texto ("O" en mayusculas).
    expect(coincidencias.length).toBe(3);
    expect(coincidencias.every((p) => p.texto.toLowerCase() === 'o')).toBe(true);
  });

  it('sin busqueda o sin coincidencia el texto queda entero y sin remarcar', () => {
    armar();

    expect(component.partesResaltadas('PAGO PROVEEDOR')).toEqual([
      { texto: 'PAGO PROVEEDOR', esCoincidencia: false },
    ]);

    component.busqueda.set('INEXISTENTE');
    expect(component.partesResaltadas('PAGO PROVEEDOR')).toEqual([
      { texto: 'PAGO PROVEEDOR', esCoincidencia: false },
    ]);
  });

  it('la palabra buscada se ve remarcada en amarillo en la celda', async () => {
    armar();
    component.busqueda.set('PROVEEDOR');
    fixture.detectChanges();

    const remarcados = fixture.nativeElement.querySelectorAll('mark');
    expect(remarcados.length).toBe(1);
    expect(remarcados[0].textContent).toBe('PROVEEDOR');

    // Sin busqueda no hay remarcado: el amarillo no ensucia la tabla en reposo.
    component.busqueda.set('');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('mark').length).toBe(0);
  });

  it('limpiar todos los filtros restaura la tabla', async () => {
    armar();

    component.alternarValor('concepto', 'PAGO PROVEEDOR');
    component.alternarValor('credito', '');
    expect(component.cantidadFiltros()).toBe(2);

    component.limpiarFiltros();
    expect(component.hayFiltros()).toBe(false);
    expect(component.filasVisibles().length).toBe(3);
  });

  it('deshacer tambien limpia los filtros', async () => {
    armar();

    importacion.editarMovimiento(importacion.movimientos()[0].id, { concepto: 'COBRO EDITADO' });
    component.alternarValor('concepto', 'PAGO PROVEEDOR');

    component.deshacer();

    expect(component.hayFiltros()).toBe(false);
    expect(component.filasVisibles().length).toBe(3);
  });

  it('el embudo abre el panel con orden, seleccionar todo y valores', async () => {
    armar();

    const embudos = fixture.nativeElement.querySelectorAll('thead button[aria-label^="Filtrar por"]');
    expect(embudos.length).toBe(4);
    embudos[0].click();
    fixture.detectChanges();

    expect(component.filtroAbierto()).toBe('fecha');
    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('A→Z');
    expect(texto).toContain('Seleccionar todo');
    expect(texto).toContain('01/07/2026');
  });

  it('con filtros el pie cuenta las coincidencias y aparece el chip de quitar', async () => {
    armar();

    component.alternarValor('concepto', 'PAGO PROVEEDOR');
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('1 de 3 movimientos coinciden');
    expect(fixture.nativeElement.textContent).toContain('Quitar filtros (1)');

    component.limpiarFiltros();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Quitar filtros');
  });

  // ------------------------------------------------------------------
  // Orden segun el tipo de columna
  // ------------------------------------------------------------------

  it('el embudo de una columna numerica dice menor a mayor y ordena de verdad', async () => {
    armar();

    const embudos = fixture.nativeElement.querySelectorAll('thead button[aria-label^="Filtrar por"]');
    embudos[2].click(); // credito
    fixture.detectChanges();

    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Menor a mayor');
    expect(texto).toContain('Mayor a menor');

    component.ordenarDescendente('credito');
    fixture.detectChanges();

    expect(component.sentidoOrden('credito')).toBe('desc');
    expect(component.filasVisibles()[0].concepto).toBe('COBRO CLIENTE A'); // el mayor credito queda arriba

    component.ordenarAscendente('credito');
    expect(component.sentidoOrden('credito')).toBe('asc');
    expect(component.filasVisibles()[2].concepto).toBe('COBRO CLIENTE A'); // y el menor credito termina abajo
  });

  it('el orden del embudo queda fijo: A→Z no alterna con Z→A', async () => {
    armar();

    component.ordenarDescendente('concepto');
    expect(component.sentidoOrden('concepto')).toBe('desc');

    component.ordenarAscendente('concepto');
    component.ordenarAscendente('concepto');
    expect(component.sentidoOrden('concepto')).toBe('asc');
    expect(component.filasVisibles().map((m) => m.concepto)).toEqual([
      'COBRO CLIENTE A',
      'COMISION',
      'PAGO PROVEEDOR',
    ]);
  });

  it('el embudo de concepto y fecha usa A→Z, no menor a mayor', async () => {
    armar();

    const embudos = fixture.nativeElement.querySelectorAll('thead button[aria-label^="Filtrar por"]');
    embudos[1].click(); // concepto
    fixture.detectChanges();
    const textoConcepto = fixture.nativeElement.textContent;
    expect(textoConcepto).toContain('A→Z');
    expect(textoConcepto).not.toContain('Menor a mayor');

    embudos[0].click(); // fecha
    fixture.detectChanges();
    expect(component.filtroAbierto()).toBe('fecha');
    expect(component.esTexto('fecha')).toBe(true);
    expect(component.esTexto('credito')).toBe(false);
  });

  // ------------------------------------------------------------------
  // Paneles del embudo: interactuables y visibles
  // ------------------------------------------------------------------

  it('los paneles se alinean hacia el centro: fecha/concepto a la izquierda, credito/debito a la derecha', () => {
    armar();

    expect(component.alinearPanelDerecha('fecha')).toBe(false);
    expect(component.alinearPanelDerecha('concepto')).toBe(false);
    expect(component.alinearPanelDerecha('credito')).toBe(true);
    expect(component.alinearPanelDerecha('debito')).toBe(true);
  });

  it('el embudo de fecha abre hacia la derecha y el de debito hacia la izquierda', async () => {
    armar();

    const abrir = (titulo: string) => {
      const embudos = Array.from(
        fixture.nativeElement.querySelectorAll('thead button[aria-label^="Filtrar por"]'),
      ) as HTMLButtonElement[];
      return embudos.find((b) => b.getAttribute('aria-label') === 'Filtrar por ' + titulo) as HTMLButtonElement;
    };

    abrir('Fecha').click();
    fixture.detectChanges();
    let panel = Array.from(
      fixture.nativeElement.querySelectorAll('.animate-aparecer-pop'),
    ) as HTMLElement[];
    let panelAbierto = panel.find((p) => p.textContent?.includes('Seleccionar todo')) as HTMLElement;
    expect(panelAbierto).toBeTruthy();
    expect(panelAbierto.classList.contains('left-0')).toBe(true);
    expect(panelAbierto.classList.contains('right-0')).toBe(false);

    component.filtroAbierto.set(null);
    abrir('Débito').click();
    fixture.detectChanges();
    panel = Array.from(fixture.nativeElement.querySelectorAll('.animate-aparecer-pop')) as HTMLElement[];
    panelAbierto = panel.find((p) => p.textContent?.includes('Seleccionar todo')) as HTMLElement;
    expect(panelAbierto.classList.contains('right-0')).toBe(true);
    expect(panelAbierto.classList.contains('left-0')).toBe(false);
  });

  it('el encabezado queda sobre la capa que cierra menus: los clics llegan al panel', async () => {
    armar();

    // El th debe estar por encima de la capa invisible z-30 (z-40), si no la
    // capa se traga todos los clics dentro de los paneles.
    const th = fixture.nativeElement.querySelector('thead tr th');
    expect(th.className).toContain('z-40');
    expect(th.className).not.toContain('z-30');

    component.filtroAbierto.set('fecha');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.fixed.inset-0.z-30')).toBeTruthy();

    const aZ = (
      Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[]
    ).find((b) => b.textContent?.trim() === 'A→Z') as HTMLButtonElement;
    aZ.click();
    fixture.detectChanges();

    expect(component.sentidoOrden('fecha')).toBe('asc');
    expect(component.filtroAbierto()).toBe('fecha');
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

  it('el movimiento nuevo muestra credito y debito con lugar para el clic, no un blanco de 8px', async () => {
    armar();

    component.agregarMovimiento();
    fixture.detectChanges();

    // La fila nueva es la que tiene el input de concepto abierto.
    const filas = fixture.nativeElement.querySelectorAll('tbody tr') as NodeListOf<HTMLElement>;
    const filaNueva = Array.from(filas).find((tr) => tr.querySelector('input')) as HTMLElement;
    const botones = Array.from(filaNueva.querySelectorAll('td button')) as HTMLButtonElement[];

    // Crédito y débito vacíos se ven como "0,00" (no texto vacío que colapsa
    // el botón a 8px de alto) y tienen altura mínima para acertarles el clic.
    const vacios = botones.filter((b) => b.textContent?.trim() === '0,00');
    expect(vacios.length).toBe(2);
    for (const vacio of vacios) expect(vacio.className).toContain('min-h-');

    // Y el clic en ese crédito abre el editor de la celda.
    const credito = botones.find((b) => b.textContent?.trim() === '0,00') as HTMLButtonElement;
    credito.click();
    fixture.detectChanges();
    expect(component.borrador()?.campo).toBe('credito');
    expect(component.borrador()?.valor).toBe('0');
  });

  it('quitar un movimiento lo saca de la tabla y recalcula los totales', async () => {
    armar();

    component.quitarMovimiento(importacion.movimientos()[1].id);
    fixture.detectChanges();

    expect(importacion.movimientos().length).toBe(2);
    expect(component.totalDebitos()).toBe(150);
  });

  // ------------------------------------------------------------------
  // Credito o debito, no los dos
  // ------------------------------------------------------------------

  it('con un credito cargado la celda de debito queda bloqueada', async () => {
    armar();
    const mov = importacion.movimientos()[0]; // haber 1000, debe 0

    expect(component.celdaBloqueada(mov, 'debito')).toBe(true);
    expect(component.celdaBloqueada(mov, 'credito')).toBe(false);

    // Ni abriendo la edicion por codigo se pasa: la celda bloqueada no existe.
    component.editar(mov, 'debito', '50');
    expect(component.borrador()).toBeNull();
    expect(importacion.movimientos()[0].debe).toBe(0);
  });

  it('con un debito cargado la celda de credito queda bloqueada', async () => {
    armar();
    const mov = importacion.movimientos()[1]; // debe 400, haber 0

    expect(component.celdaBloqueada(mov, 'credito')).toBe(true);
    expect(component.celdaBloqueada(mov, 'debito')).toBe(false);
  });

  it('vaciar el credito desbloquea la celda de debito', async () => {
    armar();
    const mov = importacion.movimientos()[0];

    importacion.editarMovimiento(mov.id, { haber: 0 });
    fixture.detectChanges();

    expect(component.celdaBloqueada(importacion.movimientos()[0], 'debito')).toBe(false);
  });

  it('la celda bloqueada se pinta sin boton de edicion', async () => {
    armar();
    fixture.detectChanges();

    // Fila 1 (COBRO): el debito esta bloqueado porque ya hay un credito.
    const celdaDebito = fixture.nativeElement.querySelectorAll('tbody tr')[0].querySelectorAll('td')[3];
    expect(celdaDebito.querySelector('button')).toBeNull();
    expect(celdaDebito.textContent).toContain('—');
    // La de credito sigue con su boton.
    const celdaCredito = fixture.nativeElement.querySelectorAll('tbody tr')[0].querySelectorAll('td')[2];
    expect(celdaCredito.querySelector('button')).not.toBeNull();
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

  it('una fila sin credito ni debito no deja confirmar', async () => {
    armar([{ fecha: '2026-07-01', concepto: 'SIN IMPORTE', debe: 0, haber: 0, saldo: 0 }]);

    expect(component.hayErrores()).toBe(true);
    expect(component.puedeConfirmar()).toBe(false);
    expect(component.errores().get(importacion.movimientos()[0].id)?.join(' ')).toContain(
      'Falta un importe',
    );
  });

  it('deshacer vuelve la tabla a lo que trajo el extracto', async () => {
    armar();

    importacion.editarMovimiento(importacion.movimientos()[0].id, { haber: 2500 });
    importacion.quitarMovimiento(importacion.movimientos()[1].id);
    const agregado = importacion.agregarMovimiento();
    fixture.detectChanges();

    expect(importacion.hayCambios()).toBe(true);

    component.deshacer();
    fixture.detectChanges();

    expect(importacion.movimientos().length).toBe(3);
    expect(importacion.movimientos()[0].haber).toBe(1000);
    expect(importacion.movimientos().some((m) => m.id === agregado)).toBe(false);
    expect(importacion.hayCambios()).toBe(false);
  });

  it('el boton deshacer aparece deshabilitado sin cambios', async () => {
    armar();

    const botones = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    const deshacer = botones.find((b) => b.textContent?.includes('Deshacer cambios'))!;

    expect(deshacer).toBeTruthy();
    expect(deshacer.disabled).toBe(true);
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
