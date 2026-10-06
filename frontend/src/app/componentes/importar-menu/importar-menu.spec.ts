import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { Component } from '@angular/core';

import { ImportarMenuComponent } from './importar-menu';

/** Envoltorio minimo para poder escuchar el output del menu. */
@Component({
  standalone: true,
  imports: [ImportarMenuComponent],
  template: '<app-importar-menu (excelSeleccionado)="recibido = $event" />',
})
class Contenedor {
  recibido: File | null = null;
}

describe('ImportarMenuComponent', () => {
  let fixture: ComponentFixture<Contenedor>;
  let menu: ImportarMenuComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [Contenedor],
      providers: [provideRouter([])],
    }).compileComponents();

    fixture = TestBed.createComponent(Contenedor);
    fixture.detectChanges();
    menu = fixture.debugElement.children[0].componentInstance;
  });

  function botonImportar(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  function opciones(): HTMLElement[] {
    return Array.from(fixture.nativeElement.querySelectorAll('[role="menuitem"]'));
  }

  function elegirExcelEnElInput(nombre: string): void {
    const input = fixture.nativeElement.querySelector('#importarExcel');
    // configurable: el TestBed reutiliza el elemento raiz entre tests, y sin
    // esto el segundo test que redefine "files" revienta.
    Object.defineProperty(input, 'files', {
      value: [new File([new Uint8Array([80, 75, 3, 4])], nombre)],
      configurable: true,
    });
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  }

  it('nace con el menu cerrado', () => {
    expect(menu.menuAbierto()).toBe(false);
    expect(opciones().length).toBe(0);
  });

  it('el click en Importar abre y cierra el menu', () => {
    botonImportar().click();
    fixture.detectChanges();
    expect(menu.menuAbierto()).toBe(true);

    botonImportar().click();
    fixture.detectChanges();
    expect(menu.menuAbierto()).toBe(false);
  });

  it('el menu ofrece Excel y PDF, y marca PDF como nuevo', () => {
    botonImportar().click();
    fixture.detectChanges();

    expect(opciones().length).toBe(2);
    const texto = fixture.nativeElement.textContent;
    expect(texto).toContain('Importar vía Excel');
    expect(texto).toContain('Importar vía PDF');
    expect(texto).toContain('Nuevo');
  });

  it('el input de Excel solo acepta los tres formatos de tabla', () => {
    expect(fixture.nativeElement.querySelector('#importarExcel').getAttribute('accept')).toBe(
      '.xlsx,.xls,.csv',
    );
  });

  it('elegir Excel emite el archivo y cierra el menu', () => {
    botonImportar().click();
    fixture.detectChanges();

    elegirExcelEnElInput('julio.xlsx');

    expect(fixture.componentInstance.recibido?.name).toBe('julio.xlsx');
    expect(menu.menuAbierto()).toBe(false);
  });

  it('elegir Excel dos veces el mismo archivo vuelve a disparar el change', () => {
    botonImportar().click();
    fixture.detectChanges();
    elegirExcelEnElInput('julio.xlsx');

    botonImportar().click();
    fixture.detectChanges();
    elegirExcelEnElInput('julio.xlsx');

    expect(fixture.componentInstance.recibido?.name).toBe('julio.xlsx');
  });

  it('elegir PDF va a /importar-pdf y no emite el archivo', () => {
    const router = TestBed.inject(Router);
    const navegar = vi.spyOn(router, 'navigate').mockResolvedValue(true);

    botonImportar().click();
    fixture.detectChanges();
    opciones()[1].click();
    fixture.detectChanges();

    expect(navegar).toHaveBeenCalledWith(['/importar-pdf']);
    expect(fixture.componentInstance.recibido).toBeNull();
    expect(menu.menuAbierto()).toBe(false);
  });

  it('un clic afuera cierra el menu', () => {
    botonImportar().click();
    fixture.detectChanges();

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();

    expect(menu.menuAbierto()).toBe(false);
  });

  it('el Escape cierra el menu', () => {
    botonImportar().click();
    fixture.detectChanges();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();

    expect(menu.menuAbierto()).toBe(false);
  });
});
