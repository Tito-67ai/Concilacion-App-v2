import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ImportarPdfComponent } from './importar-pdf';

describe('ImportarPdfComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ImportarPdfComponent],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(ImportarPdfComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('mantiene deshabilitado el botón hasta tener cuenta y archivo', () => {
    const fixture = TestBed.createComponent(ImportarPdfComponent);
    const component = fixture.componentInstance;

    expect(component.habilitado).toBe(false);

    component.formulario.controls.cuentaId.setValue('4301');
    expect(component.habilitado).toBe(false);

    component.formulario.controls.archivo.setValue(
      new File(['%PDF-1.4 contenido'], 'extracto.pdf', { type: 'application/pdf' }),
    );
    expect(component.habilitado).toBe(true);
  });

  it('rechaza archivos que no son PDF', () => {
    const fixture = TestBed.createComponent(ImportarPdfComponent);
    const component = fixture.componentInstance;

    component.formulario.controls.archivo.setValue(
      new File(['contenido'], 'extracto.xlsx', {
        type: 'application/vnd.ms-excel',
      }),
    );

    expect(component.habilitado).toBe(false);
    expect(component.errorArchivo).toContain('PDF');
  });
});