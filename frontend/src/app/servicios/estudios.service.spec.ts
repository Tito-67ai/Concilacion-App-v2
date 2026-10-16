import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { EstudiosService, Estudio, RespuestaEstudios } from './estudios.service';

const API = 'http://127.0.0.1:8000/api';
const URL_ESTUDIOS = `${API}/xubio/estudios`;
const URL_ESTUDIO = `${API}/xubio/estudio`;
const URL_SINCRONIZAR = `${API}/xubio/estudios/sincronizar`;

function estudio(extra: Partial<Estudio> = {}): Estudio {
  return {
    clave: 'empresa:tnt_100001',
    nombre: 'ALFA S.A.',
    origen: 'empresa',
    tenant: 'tnt_100001',
    organizacion_id: null,
    cuit: null,
    es_actual: false,
    activo: true,
    ...extra,
  };
}

function respuesta(extra: Partial<RespuestaEstudios> = {}): RespuestaEstudios {
  return {
    exito: true,
    configurada: true,
    catalogo_cargado: true,
    empresa_en_sesion: 'ALFA S.A.',
    actual: null,
    estudios: [estudio()],
    aviso: null,
    ...extra,
  };
}

describe('EstudiosService', () => {
  let servicio: EstudiosService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    servicio = TestBed.inject(EstudiosService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('arranca vacio y sin cargar', () => {
    expect(servicio.estudios()).toEqual([]);
    expect(servicio.actual()).toBeNull();
    expect(servicio.cargando()).toBe(false);
  });

  it('cargar lee el catalogo y guarda el aviso', () => {
    servicio.cargar();

    expect(servicio.cargando()).toBe(true);
    http
      .expectOne(URL_ESTUDIOS)
      .flush(
        respuesta({
          configurada: false,
          aviso: 'Sin sesion de Xubio',
          catalogo_cargado: false,
          estudios: [],
        }),
      );

    expect(servicio.cargando()).toBe(false);
    expect(servicio.estudios()).toEqual([]);
    expect(servicio.aviso()).toBe('Sin sesion de Xubio');
    expect(servicio.configurada()).toBe(false);
  });

  it('cargar guarda los estudios y el elegido', () => {
    const alfa = estudio({ es_actual: true });
    servicio.cargar();
    http.expectOne(URL_ESTUDIOS).flush(respuesta({ actual: alfa, estudios: [alfa] }));

    expect(servicio.hayEstudios()).toBe(true);
    expect(servicio.actual()?.clave).toBe('empresa:tnt_100001');
    expect(servicio.empresaEnSesion()).toBe('ALFA S.A.');
    expect(servicio.aviso()).toBeNull();
  });

  it('cargar con error deja un mensaje para la pantalla', () => {
    servicio.cargar();
    http.expectOne(URL_ESTUDIOS).error(new ProgressEvent('error'), { status: 0 });

    expect(servicio.cargando()).toBe(false);
    expect(servicio.error()).toContain('FastAPI');
  });

  it('elegir hace PUT y marca el estudio como actual en la lista', () => {
    const alfa = estudio();
    const beta = estudio({ clave: 'empresa:tnt_100002', nombre: 'BETA S.R.L.', tenant: 'tnt_100002' });
    servicio.cargar();
    http.expectOne(URL_ESTUDIOS).flush(respuesta({ estudios: [alfa, beta] }));

    servicio.elegir('empresa:tnt_100002');

    const peticion = http.expectOne(URL_ESTUDIO);
    expect(peticion.request.method).toBe('PUT');
    expect(peticion.request.body).toEqual({ clave: 'empresa:tnt_100002' });
    peticion.flush({ ...beta, es_actual: true });

    expect(servicio.actual()?.clave).toBe('empresa:tnt_100002');
    expect(servicio.estudios().find((e) => e.clave === 'empresa:tnt_100002')?.es_actual).toBe(true);
    expect(servicio.estudios().find((e) => e.clave === 'empresa:tnt_100001')?.es_actual).toBe(false);
  });

  it('elegir un estudio que no existe deja el motivo del 404', () => {
    servicio.elegir('empresa:tnt_999999');
    http
      .expectOne(URL_ESTUDIO)
      .flush({ detail: 'El estudio no está en el catálogo.' }, { status: 404, statusText: 'Not Found' });

    expect(servicio.error()).toBe('El estudio no está en el catálogo.');
  });

  it('olvidar hace DELETE y limpia la eleccion', () => {
    const alfa = estudio({ es_actual: true });
    servicio.cargar();
    http.expectOne(URL_ESTUDIOS).flush(respuesta({ actual: alfa, estudios: [alfa] }));

    servicio.olvidar();

    const peticion = http.expectOne(URL_ESTUDIO);
    expect(peticion.request.method).toBe('DELETE');
    peticion.flush({ estudio: null });

    expect(servicio.actual()).toBeNull();
    expect(servicio.estudios()[0].es_actual).toBe(false);
  });

  it('sincronizar hace POST y aplica el catalogo nuevo', () => {
    servicio.sincronizar();

    expect(servicio.sincronizando()).toBe(true);
    const peticion = http.expectOne(URL_SINCRONIZAR);
    expect(peticion.request.method).toBe('POST');
    peticion.flush(respuesta({ estudios: [estudio(), estudio({ clave: 'cliente:2' })] }));

    expect(servicio.sincronizando()).toBe(false);
    expect(servicio.estudios().length).toBe(2);
  });

  it('sincronizar dos veces seguidas no dispara dos viajes', () => {
    servicio.sincronizar();
    servicio.sincronizar();

    const peticion = http.expectOne(URL_SINCRONIZAR);
    peticion.flush(respuesta());
  });
});
