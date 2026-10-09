import { CommonModule } from '@angular/common';
import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';

import { ImportacionService, MovimientoImportado } from '../../servicios/importacion.service';

/**
 * Destino del enlace de ayuda.
 *
 * A proposito va sin destinatario: mandar el reporte a una direccion inventada
 * es peor que abrir el cliente de correo con el asunto ya puesto. Cuando exista
 * el canal de soporte se completa el CORREO y el reporte llega solo.
 */
const CORREO_SOPORTE = '';

/** Columnas de la tabla. El orden es el de la pantalla. */
type ClaveColumna = 'fecha' | 'concepto' | 'credito' | 'debito';

interface Columna {
  clave: ClaveColumna;
  titulo: string;
  /** Como se ordena de menor a mayor: 'texto' o 'numero'. */
  orden: 'texto' | 'numero';
}

/** Campo que se esta editando y con que valor crudo, antes de validarlo. */
interface Borrador {
  id: string;
  campo: ClaveColumna;
  valor: string;
}

const COLUMNAS: Columna[] = [
  { clave: 'fecha', titulo: 'Fecha', orden: 'texto' },
  { clave: 'concepto', titulo: 'Concepto', orden: 'texto' },
  { clave: 'credito', titulo: 'Crédito', orden: 'numero' },
  { clave: 'debito', titulo: 'Débito', orden: 'numero' },
];

/**
 * Parte 4 del flujo: la pantalla de verificacion (/verificar-importacion).
 *
 * Es la unica pantalla donde el usuario puede corregir el extracto antes de que
 * exista: de este lado todavia no se guardo nada, asi que un importe mal leido
 * se corrige escribiendo el numero. Despues de confirmar, la conciliacion
 * recibe los movimientos ya revisados.
 *
 * La edicion es en linea y en vivo: cada celda es un input que escribe en el
 * servicio al confirmar con Enter o al salir con Tab o clic. No hay un boton de
 * "guardar" por fila porque un boton por fila es un boton que alguien va a
 * olvidar, y lo que se guardaria es la mitad de la correccion.
 */
@Component({
  selector: 'app-verificar-importacion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './verificar-importacion.html',
})
export class VerificarImportacionComponent {
  // El servicio va primero a proposito: los signals de abajo leen de el, y en
  // JavaScript una referencia a un campo que todavia no se inicializo es
  // undefined, no un error visible.
  private readonly router = inject(Router);
  private readonly importacion = inject(ImportacionService);

  readonly columnas = COLUMNAS;
  readonly totalCreditos = this.importacion.totalCreditos;
  readonly totalDebitos = this.importacion.totalDebitos;
  readonly diferencia = this.importacion.diferencia;
  readonly saldoInicial = this.importacion.saldoInicial;
  readonly saldoFinal = this.importacion.saldoFinal;
  readonly destino = this.importacion.destino;
  readonly hayCambios = this.importacion.hayCambios;

  /** Texto de la barra de busqueda: filtra las filas sin tocar los datos. */
  readonly busqueda = signal('');

  /**
   * Filtros por valor al estilo Excel: por cada columna, el conjunto de valores
   * marcados en el embudo. La clave es el valor tal como se ve en la celda
   * ("1.000,00", "PAGO PROVEEDOR"), no el numero crudo: filtrar por lo que se
   * lee es mas facil de entender. Un set vacio no filtra nada.
   */
  private readonly filtros = signal<Partial<Record<ClaveColumna, Set<string>>>>({});

  /** Panel del embudo abierto de una columna, por clave. */
  readonly filtroAbierto = signal<ClaveColumna | null>(null);

  /** Orden activo de la tabla, si el usuario ordeno por alguna columna. */
  private readonly orden = signal<{ clave: ClaveColumna; descendente: boolean } | null>(null);

  /** Celda en edicion: id del movimiento, columna y valor crudo tipeado. */
  readonly borrador = signal<Borrador | null>(null);

  /** Error de la ultima celda confirmada, para mostrarlo en la fila. */
  readonly errorCelda = signal('');

  readonly movimientos = this.importacion.movimientos;

  /** La celda en edicion, para enfocarla y seleccionar el valor a reemplazar. */
  private readonly celdaEnEdicion = viewChild<ElementRef<HTMLInputElement>>('celdaEnEdicion');

  constructor() {
    // Si se entra por la URL no hay nada que verificar: la seleccion vive en
    // memoria y se pierde al recargar.
    if (!this.importacion.tieneSeleccion()) {
      this.router.navigate(['/importar-pdf']);
    }

    // Recien aparece el input cuando hay borrador, asi que el autofocus del
    // markup no alcanza: hay que enfocarlo despues de que se creo. Y se
    // selecciona el contenido para que escribir pise el valor viejo en vez de
    // agregarse al final.
    effect(() => {
      const celda = this.celdaEnEdicion();
      if (!celda) return;
      queueMicrotask(() => {
        celda.nativeElement.focus();
        celda.nativeElement.select();
      });
    });
  }

  /**
   * El panel del embudo se abre hacia los lados: las columnas de la mitad
   * izquierda hacia la derecha (left-0) y las de la mitad derecha hacia la
   * izquierda (right-0). Asi ninguna queda recortada contra el borde de la
   * seccion, como pasaba con la columna Fecha (angosta y pegada a la
   * izquierda) con el right-0 fijo.
   */
  alinearPanelDerecha(columna: ClaveColumna): boolean {
    const indice = this.columnas.findIndex((col) => col.clave === columna);
    return indice >= this.columnas.length / 2;
  }

  /**
   * Un movimiento es un credito O un debito, no puede ser las dos cosas a la
   * vez. Si la fila ya tiene un importe cargado del otro lado, la celda vacia
   * queda bloqueada: sin boton de edicion, sin input, sin por donde entrar.
   *
   * La regla solo se aplica cuando el otro lado tiene valor y esta celda esta
   * vacia; si una fila vino con ambos importes (el extractor leyo de mas), las
   * dos quedan editables para que se pueda corregir borrando la que sobra.
   */
  celdaBloqueada(mov: MovimientoImportado, columna: ClaveColumna): boolean {
    if (columna === 'credito') {
      return (Number(mov.debe) || 0) > 0 && (Number(mov.haber) || 0) <= 0;
    }
    if (columna === 'debito') {
      return (Number(mov.haber) || 0) > 0 && (Number(mov.debe) || 0) <= 0;
    }
    return false;
  }

  /**
   * Filas de la tabla: filtradas por los embudos y la busqueda, y ordenadas si
   * el usuario ordeno alguna columna.
   *
   * Los filtros no borran datos: el total de la tarjeta, el pie "Movimientos a
   * importar" y la validacion siguen contando todas las filas, solo deja de
   * pintarse lo que no coincide.
   */
  readonly filasVisibles = computed(() => {
    const texto = this.busqueda().trim().toLowerCase();
    const filtros = this.filtros();
    let filas = this.movimientos();

    // Embudos por columna: solo pasan las filas cuyo valor de esa columna esta
    // marcado. Un set vacio (o ausente) no filtra nada, asi la tabla nunca se
    // queda sin filas por desmarcar todo a mano.
    const columnasFiltradas = Object.entries(filtros).filter(
      ([, valores]) => valores.size > 0,
    );
    if (columnasFiltradas.length) {
      filas = filas.filter((mov) =>
        columnasFiltradas.every(([clave, valores]) =>
          valores.has(this.valorFiltrable(mov, clave as ClaveColumna)),
        ),
      );
    }

    if (texto) {
      filas = filas.filter((mov) =>
        [mov.fecha, mov.concepto, mov.referencia]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(texto),
      );
    }

    const orden = this.orden();
    filas = [...filas];
    if (!orden) return filas;

    return filas.sort((a, b) => this.comparar(this.valorDe(a, orden.clave), this.valorDe(b, orden.clave), orden.clave) * (orden.descendente ? -1 : 1));
  });

  /**
   * Parte el texto de una celda para pintar en amarillo la parte que coincide
   * con la busqueda: al escribir una letra o una palabra, la celda la muestra
   * remarcada y se ve de un vistazo por que esa fila quedo visible.
   *
   * Usa la misma regla que el filtro (minusculas, sin recortar): si la fila
   * paso por "pago", es "pago" lo que se remarca, no otra grafia. Sin busqueda
   * (o sin coincidencia) devuelve el texto entero sin remarcar, para que el
   * amarillo no ensucie la tabla cuando no se esta buscando nada.
   */
  partesResaltadas(texto: string | null | undefined): { texto: string; esCoincidencia: boolean }[] {
    const termino = this.busqueda().trim().toLowerCase();
    const crudo = String(texto ?? '');
    if (!termino || !crudo) return [{ texto: crudo, esCoincidencia: false }];

    const origen = crudo.toLowerCase();
    const partes: { texto: string; esCoincidencia: boolean }[] = [];
    let desde = 0;
    let indice = origen.indexOf(termino);
    while (indice !== -1) {
      if (indice > desde) {
        partes.push({ texto: crudo.slice(desde, indice), esCoincidencia: false });
      }
      partes.push({ texto: crudo.slice(indice, indice + termino.length), esCoincidencia: true });
      desde = indice + termino.length;
      indice = origen.indexOf(termino, desde);
    }
    if (desde < crudo.length) {
      partes.push({ texto: crudo.slice(desde), esCoincidencia: false });
    }
    return partes;
  }

  /**
   * Errores por movimiento, para pintar la fila en rojo y bloquear el boton de
   * confirmar. Son datos, no texto: el mensaje concreto se arma en el template.
   */
  readonly errores = computed(() => {
    const mapa = new Map<string, string[]>();
    for (const mov of this.movimientos()) {
      const problemas: string[] = [];

      if (!this.fechaValida(mov.fecha)) problemas.push('La fecha no es válida.');
      if (!String(mov.concepto ?? '').trim()) problemas.push('El concepto está vacío.');

      for (const campo of ['debe', 'haber'] as const) {
        const valor = mov[campo];
        if (!Number.isFinite(Number(valor))) problemas.push('Hay un importe que no es un número.');
        else if (Number(valor) < 0) problemas.push('Un importe no puede ser negativo.');
      }

      // Un movimiento sin credito ni debito no es un movimiento: es una fila de
      // relleno que el usuario agrego y se olvido de completar, o un importe
      // que el extractor no pudo leer. Sin importe no hay nada para cruzar.
      if ((Number(mov.debe) || 0) <= 0 && (Number(mov.haber) || 0) <= 0) {
        problemas.push('Falta un importe: completá crédito o débito.');
      }

      if (problemas.length) mapa.set(mov.id, problemas);
    }
    return mapa;
  });

  readonly hayErrores = computed(() => this.errores().size > 0);

  /** Sin filas no hay nada que importar, y con errores no se debe importar. */
  readonly puedeConfirmar = computed(() => this.movimientos().length > 0 && !this.hayErrores());

  // ------------------------------------------------------------------
  // Lectura de valores
  // ------------------------------------------------------------------

  valorDe(mov: MovimientoImportado, columna: ClaveColumna): string | number {
    if (columna === 'credito') return Number(mov.haber) || 0;
    if (columna === 'debito') return Number(mov.debe) || 0;
    return mov[columna] ?? '';
  }

  /** El importe se muestra en formato argentino, con el signo adelante. */
  formatear(valor: string | number): string {
    return this.importacion.formatearImporte(Number(valor));
  }

  /**
   * La fecha se muestra como se lee acá (dd/mm/aaaa), no como la entrega el
   * extractor (AAAA-MM-DD). Se arma con las partes del string y no con Date a
   * proposito: parsear "2026-09-01" como UTC y mostrarlo en hora argentina
   * retrocede un dia.
   */
  fechaLegible(fecha: string | null | undefined): string {
    if (!fecha) return '—';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return fecha;
    const [anio, mes, dia] = fecha.split('-');
    return `${dia}/${mes}/${anio}`;
  }

  /**
   * Lo que se ve mientras se edita un importe: el numero plano, sin separador
   * de miles. Editar "1.234,56" es mas comodo que editar "1234,56" y el input
   * type text con inputMode numeric acepta punto y coma.
   */
  valorEditable(valor: string | number): string {
    const numero = Number(valor);
    return Number.isFinite(numero) ? String(numero) : '';
  }

  fechaValida(fecha: string | null | undefined): boolean {
    if (!fecha) return false;
    // El extractor entrega ISO (YYYY-MM-DD). Se valida el formato y que la fecha
    // exista de verdad: 2026-02-31 no es una fecha.
    if (!/^\d{4}-\d{2}-\d{2}$/.test(fecha)) return false;
    const [anio, mes, dia] = fecha.split('-').map(Number);
    const fechaReal = new Date(anio, mes - 1, dia);
    return (
      fechaReal.getFullYear() === anio &&
      fechaReal.getMonth() === mes - 1 &&
      fechaReal.getDate() === dia
    );
  }

  // ------------------------------------------------------------------
  // Filtros estilo Excel
  // ------------------------------------------------------------------

  /** True cuando alguna columna esta filtrando (para el chip "Quitar filtros"). */
  readonly hayFiltros = computed(() =>
    Object.values(this.filtros()).some((valores) => valores.size > 0),
  );

  /** Cuantas columnas estan filtrando. */
  readonly cantidadFiltros = computed(
    () => Object.values(this.filtros()).filter((valores) => valores.size > 0).length,
  );

  /**
   * El valor de la celda tal como se ve en pantalla: es la clave con la que se
   * filtra. Filtrar por "1.000,00" es mas facil de entender que por 1000, y el
   * set del embudo muestra exactamente lo que el usuario vio en la tabla.
   */
  valorFiltrable(mov: MovimientoImportado, columna: ClaveColumna): string {
    if (columna === 'credito') return this.formatear(mov.haber);
    if (columna === 'debito') return this.formatear(mov.debe);
    const crudo = String(mov[columna] ?? '');
    return columna === 'fecha' ? (crudo ? this.fechaLegible(crudo) : '') : crudo.trim();
  }

  /** El valor vacio no puede quedar en blanco dentro de la lista del embudo. */
  etiquetaValor(columna: ClaveColumna, valor: string): string {
    if (valor) return valor;
    return columna === 'concepto' || columna === 'fecha' ? '(Vacío)' : '(Sin importe)';
  }

  /**
   * Los valores unicos de la columna, ordenados como ordena la tabla: antes de
   * marcar, el usuario ve la lista completa. Los importes se ordenan por su
   * valor y las fechas por su fecha, no por como se escriben en pantalla.
   */
  valoresUnicos(columna: ClaveColumna): string[] {
    const sortKey = new Map<string, string>();
    for (const mov of this.movimientos()) {
      const valor = this.valorFiltrable(mov, columna);
      if (sortKey.has(valor)) continue;
      let orden: string;
      if (columna === 'fecha') {
        orden = mov.fecha || '';
      } else if (columna === 'credito' || columna === 'debito') {
        // Centavos con ceros adelante: el string ordena como numero.
        const importe = columna === 'credito' ? mov.haber : mov.debe;
        orden = String(Math.round((Number(importe) || 0) * 100)).padStart(14, '0');
      } else {
        orden = String(mov.concepto ?? '').toLowerCase();
      }
      sortKey.set(valor, orden);
    }
    return [...sortKey.keys()].sort((a, b) => sortKey.get(a)!.localeCompare(sortKey.get(b)!, 'es'));
  }

  /** True cuando la columna esta filtrando: pinta el embudo lleno y en azul. */
  tieneFiltro(columna: ClaveColumna): boolean {
    const valores = this.filtros()[columna];
    return !!valores && valores.size > 0;
  }

  /** True cuando el valor esta marcado en el embudo de esa columna. */
  valorSeleccionado(columna: ClaveColumna, valor: string): boolean {
    return this.filtros()[columna]?.has(valor) ?? false;
  }

  /** Cierra el borrador y abre/cierra el panel del embudo. */
  abrirFiltro(columna: ClaveColumna, event: MouseEvent): void {
    event.stopPropagation();
    this.borrador.set(null);
    this.errorCelda.set('');
    this.filtroAbierto.update((abierta) => (abierta === columna ? null : columna));
  }

  /** Marca o desmarca un valor de la lista del embudo. */
  alternarValor(columna: ClaveColumna, valor: string): void {
    this.filtros.update((filtros) => {
      const proximo = new Set(filtros[columna] ?? []);
      if (proximo.has(valor)) proximo.delete(valor);
      else proximo.add(valor);
      return { ...filtros, [columna]: proximo };
    });
  }

  /**
   * "Seleccionar todo": con algo desmarcado, marca todos los valores; con todo
   * marcado, desmarca. Un set vacio no filtra, asi la tabla nunca queda sin
   * filas por desmarcar todo a mano.
   */
  alternarTodos(columna: ClaveColumna): void {
    const seleccionaTodo = !this.todosSeleccionados(columna);
    this.filtros.update((filtros) => ({
      ...filtros,
      [columna]: seleccionaTodo ? new Set(this.valoresUnicos(columna)) : new Set<string>(),
    }));
  }

  /** Sin filtro (o con un set vacio) todo esta seleccionado. */
  todosSeleccionados(columna: ClaveColumna): boolean {
    const valores = this.filtros()[columna];
    if (!valores || valores.size === 0) return true;
    return valores.size >= this.valoresUnicos(columna).length;
  }

  /** "Limpiar filtro de la columna": borra solo el de esa columna. */
  limpiarFiltro(columna: ClaveColumna): void {
    this.filtros.update((filtros) => {
      if (!filtros[columna]) return filtros;
      const copia = { ...filtros };
      delete copia[columna];
      return copia;
    });
  }

  /** El chip "Quitar filtros" de la barra de busqueda: los borra todos. */
  limpiarFiltros(): void {
    this.filtros.set({});
  }

  // ------------------------------------------------------------------
  // Edicion en linea
  // ------------------------------------------------------------------

  /** La celda tiene el foco: se muestra el valor crudo para editarlo. */
  editar(mov: MovimientoImportado, columna: ClaveColumna, valor: string): void {
    // Bloqueo por si llega un click o un foco de una celda que no deberia
    // poder editarse: un debito en una fila que ya tiene credito, o al reves.
    if (this.celdaBloqueada(mov, columna)) return;

    this.errorCelda.set('');
    this.borrador.set({ id: mov.id, campo: columna, valor });
  }

  /**
   * Confirma la celda (Enter, Tab o clic afuera).
   *
   * Se parsea segun como escribe un usuario argentino: "1.234,56" son mil
   * doscientos treinta y cuatro con cincuenta y seis, no 1.234. Un input
   * type=number no acepta esa coma y obliga a tipear el numero a la inversa.
   */
  confirmarBorrador(): void {
    const borrador = this.borrador();
    if (!borrador) return;

    const { id, campo, valor } = borrador;
    const limpio = valor.trim();

    if (campo === 'credito' || campo === 'debito') {
      const numero = this.parsearImporte(limpio);
      if (limpio !== '' && !Number.isFinite(numero)) {
        this.errorCelda.set(`"${limpio}" no es un importe válido.`);
        return;
      }
      this.importacion.editarMovimiento(id, campo === 'credito' ? { haber: numero } : { debe: numero });
    } else if (campo === 'fecha') {
      if (!this.fechaValida(limpio)) {
        this.errorCelda.set('La fecha tiene que ser válida (AAAA-MM-DD).');
        return;
      }
      this.importacion.editarMovimiento(id, { fecha: limpio });
    } else {
      this.importacion.editarMovimiento(id, { concepto: limpio });
    }

    this.borrador.set(null);
    this.errorCelda.set('');
  }

  /** Escape: la celda vuelve a lo que estaba. */
  cancelarBorrador(): void {
    this.borrador.set(null);
    this.errorCelda.set('');
  }

  /**
   * Interpreta un importe tipeado.
   *
   * Con coma, los puntos son separadores de miles ("1.234,56" -> 1234.56). Sin
   * coma, el punto es decimal ("1234.56" -> 1234.56). Es la lectura que espera
   * alguien que escribe en es-AR; el caso "1.234" queriendo decir 1234 queda
   * ambiguo y se interpreta como 1.234.
   */
  parsearImporte(texto: string): number {
    const limpio = texto.replace(/\s/g, '');
    if (limpio === '') return 0;
    const normalizado = limpio.includes(',') ? limpio.replace(/\./g, '').replace(',', '.') : limpio;
    return Number(normalizado);
  }

  // ------------------------------------------------------------------
  // Filas y columnas
  // ------------------------------------------------------------------

  agregarMovimiento(): void {
    const id = this.importacion.agregarMovimiento();
    // Se deja la celda de concepto lista para escribir: agregar la fila es
    // siempre para escribir algo.
    this.borrador.set({ id, campo: 'concepto', valor: '' });
  }

  quitarMovimiento(id: string): void {
    this.importacion.quitarMovimiento(id);
  }

  /**
   * Deshace todo lo editado y vuelve a la foto del extracto. Ademas cierra la
   * celda que se estuviera editando: un borrador a medio confirmar no tiene
   * sentido apilado encima de los valores restaurados.
   */
  deshacer(): void {
    this.borrador.set(null);
    this.errorCelda.set('');
    // Los valores que se estaban filtrando dejaron de existir: editar o quitar
    // filas cambia la lista del embudo, asi que volver al extracto tambien
    // quiere decir volver a ver todo.
    this.filtros.set({});
    this.filtroAbierto.set(null);
    this.importacion.deshacerCambios();
  }

  ordenarPor(columna: ClaveColumna): void {
    this.orden.update((orden) =>
      orden?.clave === columna ? { clave: columna, descendente: !orden.descendente } : { clave: columna, descendente: false },
    );
    this.filtroAbierto.set(null);
  }

  /** Si la columna ordena como texto (A→Z) o como numero (menor a mayor). */
  esTexto(columna: ClaveColumna): boolean {
    return COLUMNAS.find((col) => col.clave === columna)?.orden === 'texto';
  }

  /**
   * "A→Z" / "Menor a mayor": fija la direccion ascendente. No alterna: volver
   * a pedir asc cuando ya esta asc no da vuelta el orden, que era lo que hacia
   * parecer que el embudo no hacia nada.
   *
   * A proposito no se cierra el panel: se deja abierto para que la tabla se
   * reordene a la vista y el boton activo quede resaltado, la confirmacion
   * visible de que el filtro hizo algo.
   */
  ordenarAscendente(columna: ClaveColumna): void {
    this.orden.set({ clave: columna, descendente: false });
  }

  /** "Z→A" / "Mayor a menor": fija la direccion descendente. */
  ordenarDescendente(columna: ClaveColumna): void {
    this.orden.set({ clave: columna, descendente: true });
  }

  /** La flechita del encabezado dice en que sentido esta ordenado. */
  sentidoOrden(columna: ClaveColumna): 'asc' | 'desc' | null {
    const orden = this.orden();
    if (orden?.clave !== columna) return null;
    return orden.descendente ? 'desc' : 'asc';
  }

  private comparar(a: string | number, b: string | number, columna: ClaveColumna): number {
    const tipo = COLUMNAS.find((col) => col.clave === columna)?.orden;
    if (tipo === 'numero') return Number(a) - Number(b);
    // es-AR para que "á" y "a" no queden separadas por el acento.
    return String(a).localeCompare(String(b), 'es');
  }

  // ------------------------------------------------------------------
  // Cierre del flujo
  // ------------------------------------------------------------------

  /**
   * Confirma: los movimientos quedan en el servicio y la conciliacion los toma
   * al arrancar. No se limpia acá porque ese limpiar es justamente el gesto que
   * los entrega.
   */
  confirmar(): void {
    if (!this.puedeConfirmar()) return;
    this.router.navigate(['/']);
  }

  /** Cancela: se descarta todo lo leido y no se importa nada. */
  cancelar(): void {
    this.importacion.limpiar();
    this.router.navigate(['/']);
  }

  /** Enlace de ayuda. Con el destino vacio abre el cliente de correo sin receptor. */
  get correoSoporte(): string {
    const asunto = encodeURIComponent('No se leyó bien un extracto en la conciliación');
    return `mailto:${CORREO_SOPORTE}?subject=${asunto}`;
  }
}
