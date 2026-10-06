import { HttpClient, HttpResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import { SolicitudExportacion } from '../modelos/conciliacion';

const API = 'http://127.0.0.1:8000/api';

// El backend arma el .xlsx en memoria con openpyxl y la plantilla de la
// auditoria. Para un extracto grande son decenas de miles de celdas: se tardan
// mas segundos que un cruce, asi que el timeout es holgado.
const TIMEOUT_EXPORTACION_MS = 120000;

/** Lo que hace falta para bajar el archivo una vez armado. */
export interface ArchivoExportado {
  /** El .xlsx como blob. */
  blob: Blob;
  /** El nombre que manda el backend en el Content-Disposition. */
  nombre: string;
}

const NOMBRE_POR_DEFECTO = 'FO 02-03 Conciliacion Bancaria.xlsx';

/**
 * Pide el papel de trabajo FO 02-03 y lo baja.
 *
 * El archivo se arma en el backend y no aca a proposito: el membrete, los
 * merges y los formatos de numero del formulario son del proceso de auditoria,
 * y recrearlos en el navegador es una segunda copia que se desactualiza sola.
 */
@Injectable({ providedIn: 'root' })
export class ExportacionService {
  private readonly http = inject(HttpClient);

  /** Pide el Excel y devuelve el blob con el nombre que puso el backend. */
  exportar(solicitud: SolicitudExportacion): Observable<ArchivoExportado> {
    // responseType 'blob' y observe 'response' juntos: el body llega como blob
    // y, al mismo tiempo, se conservan los headers. Sin lo segundo no hay forma
    // de saber como se llama el archivo y la descarga sale como "download".
    return this.http
      .post(`${API}/exportar/conciliacion`, solicitud, {
        responseType: 'blob',
        observe: 'response',
        timeout: TIMEOUT_EXPORTACION_MS,
      })
      .pipe(
        map((respuesta) => ({
          blob: (respuesta as HttpResponse<Blob>).body!,
          nombre: this.nombreDesde(respuesta),
        })),
      );
  }

  /** Pide el archivo y lo deja en la carpeta de descargas. */
  exportarYDescargar(solicitud: SolicitudExportacion): Observable<ArchivoExportado> {
    return this.exportar(solicitud).pipe(map((archivo) => {
      this.descargar(archivo);
      return archivo;
    }));
  }

  /**
   * Guarda el blob en la carpeta de descargas del navegador.
   *
   * Va con un <a> temporal y no con window.open: abrir una pestana con un blob
   * no tiene nombre de archivo y en Chrome la descarga ni siquiera arranca.
   */
  descargar(archivo: ArchivoExportado): void {
    const url = URL.createObjectURL(archivo.blob);
    const enlace = document.createElement('a');
    enlace.href = url;
    enlace.download = archivo.nombre;
    document.body.appendChild(enlace);
    enlace.click();
    document.body.removeChild(enlace);
    // El objeto se revoca despues del click, no antes: revocado antes de que
    // el navegador lea el blob, la descarga baja vacia sin avisar nada.
    URL.revokeObjectURL(url);
  }

  /**
   * El motivo de un error del backend.
   *
   * Con `responseType: 'blob'` el body de un error tambien llega como blob, no
   * como objeto. Si no se lee, `error.error.detail` es `undefined` y la
   * pantalla muestra siempre el mensaje por defecto: el usuario ve "no se pudo
   * generar el Excel" cuando el backend si sabia decir "no hay nada
   * conciliado". Por eso es asincrono y abre el blob antes de decidir.
   */
  async mensajeDeError(error: any): Promise<string> {
    const mensaje = this.mensajeDeDetalle(error?.error);
    if (mensaje) return mensaje;

    const cuerpo = error?.error;
    if (cuerpo instanceof Blob) {
      const mensajeDelBlob = this.mensajeDeDetalle(await this.jsonDe(cuerpo));
      if (mensajeDelBlob) return mensajeDelBlob;
    }

    return (
      'No se pudo generar el Excel. Revisá que el backend esté corriendo en el puerto 8000.'
    );
  }

  /** El texto de un `detail` de FastAPI: string o lista de errores de pydantic. */
  private mensajeDeDetalle(cuerpo: unknown): string | null {
    const detalle = (cuerpo as { detail?: unknown })?.detail;
    if (typeof detalle === 'string' && detalle.trim()) return detalle;
    if (Array.isArray(detalle) && detalle.length > 0) {
      return detalle.map((d: any) => d?.msg ?? JSON.stringify(d)).join('; ');
    }
    return null;
  }

  /** El JSON que viene dentro de un blob de error, o null si no es JSON. */
  private async jsonDe(blob: Blob): Promise<unknown> {
    try {
      const texto = await blob.text();
      return texto.trim() ? JSON.parse(texto) : null;
    } catch {
      // El backend puede responder con HTML (por ejemplo si se cae un proxy) y
      // eso no se puede parsear. No es un error de la funcion: se devuelve
      // null y sigue el mensaje por defecto.
      return null;
    }
  }

  private nombreDesde(respuesta: HttpResponse<unknown>): string {
    const disposicion = respuesta.headers.get('content-disposition') ?? '';

    // filename*=UTF-8'' va primero: con acentos, el filename= a secas llega con
    // la tilde mojada en varios navegadores.
    const extendido = disposicion.match(/filename\*=UTF-8''([^;]+)/i);
    if (extendido) {
      try {
        return decodeURIComponent(extendido[1]);
      } catch {
        // Un nombre mal codificado no puede romper la descarga: cae al
        // filename simple de abajo.
      }
    }

    const simple = disposicion.match(/filename="?([^";]+)"?/i);
    return simple ? simple[1] : NOMBRE_POR_DEFECTO;
  }
}