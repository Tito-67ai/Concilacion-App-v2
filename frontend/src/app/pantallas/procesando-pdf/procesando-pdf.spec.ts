import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ImportacionService } from '../../servicios/importacion.service';
import { ImportarPdfComponent } from '../importar-pdf/importar-pdf';
import { ProcesandoPdfComponent } from './procesando-pdf';

describe('ProcesandoPdfComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ProcesandoPdfComponent],
      // El componente redirige a /importar-pdf si no hay nada seleccionado,
      // así que la ruta tiene que existir para que la navegación no falle.
      providers: [provideRouter([{ path: 'importar-pdf', component: ImportarPdfComponent }])],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(ProcesandoPdfComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('arranca con el primer paso completo y el segundo en proceso', () => {
    const fixture = TestBed.createComponent(ProcesandoPdfComponent);
    const component = fixture.componentInstance;

    expect(component.estados()).toEqual(['completado', 'cargando', 'pendiente']);
    expect(component.progreso()).toBe(33);
    expect(component.finalizado()).toBe(false);
  });

  it('muestra el nombre del archivo que se eligió en la pantalla anterior', () => {
    const importacion = TestBed.inject(ImportacionService);
    importacion.guardar({
      cuentaId: '4301',
      cuentaNombre: '4301 - Clientes',
      archivo: new File(['%PDF-1.4'], 'extracto-bbva.pdf', { type: 'application/pdf' }),
    });

    const fixture = TestBed.createComponent(ProcesandoPdfComponent);

    expect(fixture.componentInstance.archivoNombre()).toBe('extracto-bbva.pdf');
    expect(fixture.componentInstance.cuentaNombre()).toBe('4301 - Clientes');
  });
});