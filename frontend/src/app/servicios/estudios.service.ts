import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';

const API = 'http://127.0.0.1:8000/api';

/** De dónde salió la entrada: del selector superior, del catálogo, o de ambos. */
export type OrigenEstudio = 'empresa' | 'cliente' | 'ambos';

/**
 * Un estudio/empresa al que puede entrar la cuenta de Xubio logueada.
 *
 * Son los mismos campos que devuelve el backend (schema Estudio): `tenant` para
 * cambiar de estudio en la web de Xubio y `organizacion_id` para que el Libro
 * Mayor salga filtrado por esa empresa (p_OrganizacionReportCode).
 */
export interface Estudio {
  clave: string;
  nombre: string;
  origen: OrigenEstudio;
  tenant: string | null;
  organizacion_id: number | null;
  cuit: string | null;
  es_actual: boolean;
  activo: boolean;
}

/** Lo que devuelve GET /xubio/estudios. */
export interface RespuestaEstudios {
  exito: boolean;
  configurada: boolean;
  catalogo_cargado: boolean;
  empresa_en_sesion: string | null;
  actual: Estudio | null;
  estudios: Estudio[];
  aviso: string | null;
}

/**
 * Estado compartido del selector de Estudio/Empresa de la barra superior.
 *
 * El catálogo se baja una vez (el bot lo arma al loguearse) y queda guardado en
 * el backend; este servicio solo lo lee y recuerda qué estudio está elegido, así
 * el selector de la barra y cualquier pantalla que lo consulte ven lo mismo.
 */
@Injectable({ providedIn: 'root' })
export class EstudiosService {
  private readonly http = inject(HttpClient);

  private readonly _estudios = signal<Estudio[]>([]);
  private readonly _actual = signal<Estudio | null>(null);
  private readonly _configurada = signal(false);
  private readonly _empresaEnSesion = signal<string | null>(null);
  private readonly _aviso = signal<string | null>(null);
  private readonly _cargando = signal(false);
  private readonly _sincronizando = signal(false);
  private readonly _error = signal('');

  readonly estudios = this._estudios.asReadonly();
  readonly actual = this._actual.asReadonly();
  readonly configurada = this._configurada.asReadonly();
  readonly empresaEnSesion = this._empresaEnSesion.asReadonly();
  readonly aviso = this._aviso.asReadonly();
  readonly cargando = this._cargando.asReadonly();
  readonly sincronizando = this._sincronizando.asReadonly();
  readonly error = this._error.asReadonly();

  readonly hayEstudios = computed(() => this._estudios().length > 0);
  readonly nombreActual = computed(() => this._actual()?.nombre ?? '');

  /**
   * Lee el catálogo guardado. NO abre el navegador: si todavía no hay catálogo,
   * el backend devuelve un `aviso` y el selector lo muestra.
   */
  cargar(): void {
    this._cargando.set(true);
    this._error.set('');
    this.http.get<RespuestaEstudios>(`${API}/xubio/estudios`).subscribe({
      next: (respuesta) => {
        this._cargando.set(false);
        this.aplicar(respuesta);
      },
      error: (error: HttpErrorResponse) => {
        this._cargando.set(false);
        this._error.set(
          this.mensajeDeError(
            error,
            'No se pudo leer el catálogo de estudios. Revisá que FastAPI esté corriendo en el puerto 8000.',
          ),
        );
      },
    });
  }

  /**
   * Vuelve a bajar el catálogo corriendo el bot de Xubio (con las credenciales
   * guardadas). Abre el navegador visible y puede pedir un captcha, así que es
   * una acción explícita del usuario, no algo que se dispare solo.
   */
  sincronizar(): void {
    if (this._sincronizando()) return;
    this._sincronizando.set(true);
    this._error.set('');
    this.http.post<RespuestaEstudios>(`${API}/xubio/estudios/sincronizar`, {}).subscribe({
      next: (respuesta) => {
        this._sincronizando.set(false);
        this.aplicar(respuesta);
      },
      error: (error: HttpErrorResponse) => {
        this._sincronizando.set(false);
        this._error.set(
          this.mensajeDeError(
            error,
            'No se pudieron actualizar los estudios. Fijate si quedó un paso a mano en la ventana del navegador y reintentá.',
          ),
        );
      },
    });
  }

  /** Elige el estudio activo: es el que filtra el Libro Mayor. */
  elegir(clave: string): void {
    this._error.set('');
    this.http.put<Estudio>(`${API}/xubio/estudio`, { clave }).subscribe({
      next: (elegido) => {
        // El backend ya lo guardó; se refleja en la lista sin volver a pedirla.
        this._actual.set(elegido);
        this._estudios.update((lista) =>
          lista.map((estudio) => ({ ...estudio, es_actual: estudio.clave === elegido.clave })),
        );
      },
      error: (error: HttpErrorResponse) => {
        this._error.set(this.mensajeDeError(error, 'No se pudo elegir el estudio.'));
      },
    });
  }

  /** Quita el estudio elegido: el selector vuelve a "elegí un estudio". */
  olvidar(): void {
    this._error.set('');
    this.http.delete<{ estudio: Estudio | null }>(`${API}/xubio/estudio`).subscribe({
      next: () => {
        this._actual.set(null);
        this._estudios.update((lista) =>
          lista.map((estudio) => ({ ...estudio, es_actual: false })),
        );
      },
      error: (error: HttpErrorResponse) => {
        this._error.set(this.mensajeDeError(error, 'No se pudo quitar el estudio.'));
      },
    });
  }

  private aplicar(respuesta: RespuestaEstudios): void {
    this._estudios.set(respuesta.estudios ?? []);
    this._actual.set(respuesta.actual ?? null);
    this._configurada.set(respuesta.configurada);
    this._empresaEnSesion.set(respuesta.empresa_en_sesion ?? null);
    this._aviso.set(respuesta.aviso ?? null);
  }

  private mensajeDeError(error: HttpErrorResponse, porDefecto: string): string {
    const detalle = error?.error?.detail;
    return typeof detalle === 'string' && detalle.trim() ? detalle : porDefecto;
  }
}
