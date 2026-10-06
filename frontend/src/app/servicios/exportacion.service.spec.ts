import { TestBed } from '@angular/core/testing';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

import { ArchivoExportado, ExportacionService } from './exportacion.service';
import { SolicitudExportacion } from '../modelos/conciliacion';

const API = 'http://127.0.0.1:8000/api';
const URL_EXPORTAR = `${API}/exportar/conciliacion`;

function solicitud(extra: Partial<SolicitudExportacion> = {}): SolicitudExportacion {
  return {
    conciliados: [
      {
        fecha: '2026-07-01',
        concepto_banco: 'COBRO',
        concepto_xubio: 'Factura 1',
        debe: 0,
        haber: 1000,
        saldo: 1000,
        importe: 1000,
        categoria: 'operativo',
      },
    ],
    pendientes_banco: [],
    pendientes_xubio: [],
    encabezado: {
      empresa: 'ACME S.A.',
      banco: 'SANT',
      numeroCuenta: '0001234',
      periodo: '2026-07',
    },
    ...extra,
  };
}

describe('ExportacionService', () => {
  let servicio: ExportacionService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    servicio = TestBed.inject(ExportacionService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('le pega al endpoint de exportacion con las tres bandejas y el membrete', async () => {
    const pedido = firstValueFrom(servicio.exportar(solicitud()));

    const peticion = http.expectOne(URL_EXPORTAR);
    expect(peticion.request.method).toBe('POST');
    expect(peticion.request.body.conciliados.length).toBe(1);
    expect(peticion.request.body.pendientes_banco).toEqual([]);
    expect(peticion.request.body.encabezado.banco).toBe('SANT');

    peticion.flush(new Blob(['xlsx']));
    await expect(pedido).resolves.toBeTruthy();
  });

  // El cuerpo de la respuesta es un .xlsx, no un objeto: si el servicio pidiera
  // 'json' (o nada), Angular intenta parsear el binario y la descarga falla con
  // un error de sintaxis que no dice nada de Excel.
  it('pide la respuesta como blob, no como json', () => {
    servicio.exportar(solicitud()).subscribe();

    const peticion = http.expectOne(URL_EXPORTAR);
    expect(peticion.request.responseType).toBe('blob');

    peticion.flush(new Blob(['xlsx']));
  });

  // observe 'response' ademas de responseType 'blob': si solo se pidiera el
  // blob, no habria forma de leer el Content-Disposition y el archivo bajaria
  // como "download".
  it('conserva los headers de la respuesta para poder nombrar el archivo', async () => {
    const pedido = firstValueFrom(
      servicio.exportar(solicitud()),
    );

    http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']), {
      headers: {
        'Content-Disposition': 'attachment; filename="FO 02-03 ACME S.A. SANT 06-07-2026.xlsx"',
      },
    });

    const archivo = await pedido;
    expect(archivo.nombre).toBe('FO 02-03 ACME S.A. SANT 06-07-2026.xlsx');
    expect(archivo.blob).toBeTruthy();
  });

  // Con acentos en el nombre de la empresa, el filename= a secas llega con la
  // tilde mojada en varios navegadores. Por eso el backend manda tambien
  // filename*, y es ese el que hay que leer primero.
  it('prefiere el nombre codificado cuando hay acentos', async () => {
    const pedido = firstValueFrom(servicio.exportar(solicitud()));

    http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']), {
      headers: {
        'Content-Disposition':
          "attachment; filename=\"FO 02-03 Piccinini estudio S.A 06-07-2026.xlsx\"; " +
          "filename*=UTF-8''FO%2002-03%20Piccinini%20estudio%20S.A%20%E2%80%A6%20conciliaci%C3%B3n.xlsx",
      },
    });

    const archivo = await pedido;
    expect(archivo.nombre).toBe('FO 02-03 Piccinini estudio S.A … conciliación.xlsx');
  });

  it('si no viene Content-Disposition usa un nombre por defecto que igual es xlsx', async () => {
    const pedido = firstValueFrom(servicio.exportar(solicitud()));

    http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']));

    const archivo = await pedido;
    expect(archivo.nombre.endsWith('.xlsx')).toBe(true);
  });

  it('un filename* mal codificado no rompe: cae al filename simple', async () => {
    const pedido = firstValueFrom(servicio.exportar(solicitud()));

    http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']), {
      headers: {
        'Content-Disposition':
          "attachment; filename=\"FO 02-03 simple.xlsx\"; filename*=UTF-8''%E0%A4%A",
      },
    });

    const archivo = await pedido;
    expect(archivo.nombre).toBe('FO 02-03 simple.xlsx');
  });

  it('exportarYDescargar dispara la descarga con el nombre del backend', async () => {
    const descargas: string[] = [];
    const urlOriginal = URL.createObjectURL;
    const revocarOriginal = URL.revokeObjectURL;
    const clickOriginal = HTMLAnchorElement.prototype.click;

    URL.createObjectURL = () => 'blob:mock';
    URL.revokeObjectURL = () => {};
    HTMLAnchorElement.prototype.click = function () {
      descargas.push(this.download);
    };

    try {
      const pedido = firstValueFrom(servicio.exportarYDescargar(solicitud()));

      http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']), {
        headers: {
          'Content-Disposition': 'attachment; filename="FO 02-03 ACME S.A. SANT 06-07-2026.xlsx"',
        },
      });

      await pedido;
      expect(descargas).toEqual(['FO 02-03 ACME S.A. SANT 06-07-2026.xlsx']);
    } finally {
      URL.createObjectURL = urlOriginal;
      URL.revokeObjectURL = revocarOriginal;
      HTMLAnchorElement.prototype.click = clickOriginal;
    }
  });

  // Sin revocar, cada exportacion deja el blob colgado en memoria hasta que se
  // recargue la pagina. Con un extracto grande, uno por exportacion pesa.
  it('limpia el <a> temporal del body y revoca la URL del objeto', () => {
    const revocadas: string[] = [];
    const urlOriginal = URL.createObjectURL;
    const revocarOriginal = URL.revokeObjectURL;
    const clickOriginal = HTMLAnchorElement.prototype.click;

    URL.createObjectURL = () => 'blob:mock';
    URL.revokeObjectURL = (url: string) => revocadas.push(url);
    HTMLAnchorElement.prototype.click = () => {};

    const antes = document.body.querySelectorAll('a[download]').length;

    try {
      servicio.descargar({ blob: new Blob(['xlsx']), nombre: 'a.xlsx' });

      // El <a> queda colgado en el body y el click de cada exportacion nueva
      // vuelve a disparar el anterior.
      expect(document.body.querySelectorAll('a[download]').length).toBe(antes);
      expect(revocadas).toEqual(['blob:mock']);
    } finally {
      URL.createObjectURL = urlOriginal;
      URL.revokeObjectURL = revocarOriginal;
      HTMLAnchorElement.prototype.click = clickOriginal;
    }
  });

  it('el archivo que devuelve trae el cuerpo binario intacto y un nombre', async () => {
    const pedido = firstValueFrom(servicio.exportar(solicitud()));
    http.expectOne(URL_EXPORTAR).flush(new Blob(['xlsx']));

    const archivo: ArchivoExportado = await pedido;
    // El body llega sin convertir: si el servicio lo pasara por JSON.parse, del
    // binario saldria un error de sintaxis y el archivo bajaria vacio.
    expect(archivo.blob).toBeInstanceOf(Blob);
    expect(await archivo.blob.text()).toBe('xlsx');
    expect(archivo.nombre).toBeTruthy();
  });

  it('lee el motivo real de un 400 del backend', async () => {
    const mensaje = await servicio.mensajeDeError({ error: { detail: 'No hay nada conciliado.' } });

    expect(mensaje).toBe('No hay nada conciliado.');
  });

  it('lee la lista de errores de un 422', async () => {
    const mensaje = await servicio.mensajeDeError({
      error: { detail: [{ msg: 'debe no es un numero' }] },
    });

    expect(mensaje).toBe('debe no es un numero');
  });

  // Con responseType 'blob' el body de un error tambien llega como blob. Sin
  // abrirlo, error.error.detail es undefined y la pantalla muestra siempre el
  // mensaje por defecto, perdiendo el motivo que el backend si sabia.
  it('abre el blob del error y saca el motivo de adentro', async () => {
    const mensaje = await servicio.mensajeDeError({
      error: new Blob([JSON.stringify({ detail: 'No hay nada conciliado para exportar.' })]),
    });

    expect(mensaje).toBe('No hay nada conciliado para exportar.');
  });

  it('una lista de errores de pydantic tambien sale del blob', async () => {
    const mensaje = await servicio.mensajeDeError({
      error: new Blob([JSON.stringify({ detail: [{ msg: 'debe no es un numero' }] })]),
    });

    expect(mensaje).toBe('debe no es un numero');
  });

  it('un blob que no es JSON no rompe: cae al mensaje por defecto', async () => {
    const mensaje = await servicio.mensajeDeError({ error: new Blob(['<html>502</html>']) });

    expect(typeof mensaje).toBe('string');
    expect(mensaje).toContain('backend');
  });

  it('un blob vacio tampoco rompe', async () => {
    const mensaje = await servicio.mensajeDeError({ error: new Blob([]) });

    expect(typeof mensaje).toBe('string');
  });

  it('con un error sin cuerpo da un mensaje que menciona el backend', async () => {
    const mensaje = await servicio.mensajeDeError({ status: 0 });

    expect(mensaje).toContain('backend');
  });
});