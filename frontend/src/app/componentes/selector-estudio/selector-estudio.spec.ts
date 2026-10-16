import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Estudio, RespuestaEstudios } from '../../servicios/estudios.service';
import { SelectorEstudioComponent } from './selector-estudio';

const API = 'http://127.0.0.1:8000/api';
const URL_ESTUDIOS = `${API}/xubio/estudios`;
const URL_ESTUDIO = `${API}/xubio/estudio`;
const URL_SINCRONIZAR = `${API}/xubio/estudios/sincronizar`;

const ALFA: Estudio = {
  clave: 'empresa:tnt_100001',
  nombre: 'ALFA S.A.',
  origen: 'empresa',
  tenant: 'tnt_100001',
  organizacion_id: 5001,
  cuit: '30-11111111-1',
  es_actual: false,
  activo: true,
};

const BETA: Estudio = {
  clave: 'empresa:tnt_100002',
  nombre: 'BETA Y ASOCIADOS',
  origen: 'ambos',
  tenant: 'tnt_100002',
  organizacion_id: 5002,
  cuit: '30-22222222-2',
  es_actual: true,
  activo: true,
};

function respuesta(extra: Partial<RespuestaEstudios> = {}): RespuestaEstudios {
  return {
    exito: true,
    configurada: true,
    catalogo_cargado: true,
    empresa_en_sesion: 'BETA Y ASOCIADOS',
    actual: BETA,
    estudios: [ALFA, BETA],
    aviso: null,
    ...extra,
  };
}

describe('SelectorEstudioComponent', () => {
  let fixture: ComponentFixture<SelectorEstudioComponent>;
  let selector: SelectorEstudioComponent;
  let http: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SelectorEstudioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    fixture = TestBed.createComponent(SelectorEstudioComponent);
    fixture.detectChanges();
    selector = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  /** Responde al GET que dispara ngOnInit. */
  function responderCatalogo(cuerpo = respuesta()): void {
    http.expectOne(URL_ESTUDIOS).flush(cuerpo);
    fixture.detectChanges();
  }

  function botonToggle(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  function abrirMenu(): void {
    botonToggle().click();
    fixture.detectChanges();
    // Abrir refresca el catalogo: hay un segundo GET.
    http.expectOne(URL_ESTUDIOS).flush(respuesta());
    fixture.detectChanges();
  }

  function items(): HTMLButtonElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('ul li button'));
  }

  it('lee el catalogo al arrancar y muestra el estudio elegido', () => {
    // ngOnInit ya disparo el GET.
    expect(selector.abierto()).toBe(false);
    responderCatalogo();

    expect(botonToggle().textContent).toContain('BETA Y ASOCIADOS');
  });

  it('sin estudio elegido invita a elegir uno', () => {
    responderCatalogo(respuesta({ actual: null, estudios: [] }));

    expect(botonToggle().textContent).toContain('Elegí un estudio');
  });

  it('al abrir lista los estudios y refresca', () => {
    responderCatalogo();
    abrirMenu();

    expect(selector.abierto()).toBe(true);
    expect(items().length).toBe(2);
    expect(fixture.nativeElement.textContent).toContain('ALFA S.A.');
  });

  it('el buscador filtra por nombre sin acentos ni mayusculas', () => {
    responderCatalogo();
    abrirMenu();

    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    input.value = 'beta';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    expect(items().length).toBe(1);
    expect(items()[0].textContent).toContain('BETA Y ASOCIADOS');
  });

  it('elegir un estudio hace PUT y cierra el menu', () => {
    responderCatalogo();
    abrirMenu();

    items()[0].click();
    fixture.detectChanges();

    const peticion = http.expectOne(URL_ESTUDIO);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ clave: 'empresa:tnt_100001' });
    peticion.flush({ ...ALFA, es_actual: true });
    fixture.detectChanges();

    expect(selector.abierto()).toBe(false);
    expect(botonToggle().textContent).toContain('ALFA S.A.');
  });

  it('"Actualizar desde Xubio" hace POST al endpoint del bot', () => {
    responderCatalogo();
    abrirMenu();

    const botonActualizar = Array.from(
      fixture.nativeElement.querySelectorAll('button'),
    ).find((b) => (b as HTMLButtonElement).textContent?.includes('Actualizar')) as HTMLButtonElement;

    botonActualizar.click();
    fixture.detectChanges();

    const peticion = http.expectOne(URL_SINCRONIZAR);
    expect(peticion.request.method).toBe('POST');
    peticion.flush(respuesta());
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Actualizar desde Xubio');
  });

  it('"Quitar" hace DELETE y deja de mostrar el estudio', () => {
    responderCatalogo();
    abrirMenu();

    const botonQuitar = Array.from(
      fixture.nativeElement.querySelectorAll('button'),
    ).find((b) => (b as HTMLButtonElement).textContent?.trim() === 'Quitar') as HTMLButtonElement;

    botonQuitar.click();
    fixture.detectChanges();

    const peticion = http.expectOne(URL_ESTUDIO);
    expect(peticion.request.method).toBe('DELETE');
    peticion.flush({ estudio: null });
    fixture.detectChanges();

    expect(botonToggle().textContent).toContain('Elegí un estudio');
  });

  it('un clic afuera cierra el menu', () => {
    responderCatalogo();
    abrirMenu();

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();

    expect(selector.abierto()).toBe(false);
  });

  it('muestra el aviso del backend cuando no hay sesion', () => {
    responderCatalogo(
      respuesta({ configurada: false, catalogo_cargado: false, estudios: [], actual: null, aviso: 'Sin sesion de Xubio' }),
    );
    abrirMenuCon(respuesta({ configurada: false, catalogo_cargado: false, estudios: [], actual: null, aviso: 'Sin sesion de Xubio' }));

    expect(fixture.nativeElement.textContent).toContain('Sin sesion de Xubio');
  });

  function abrirMenuCon(cuerpo: RespuestaEstudios): void {
    botonToggle().click();
    fixture.detectChanges();
    http.expectOne(URL_ESTUDIOS).flush(cuerpo);
    fixture.detectChanges();
  }
});
