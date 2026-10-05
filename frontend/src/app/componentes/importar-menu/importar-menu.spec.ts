import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ImportarMenuComponent } from './importar-menu';

describe('ImportarMenuComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ImportarMenuComponent],
      providers: [provideRouter([])],
    }).compileComponents();
  });

  it('should create', () => {
    const fixture = TestBed.createComponent(ImportarMenuComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('abre y cierra el desplegable', () => {
    const fixture = TestBed.createComponent(ImportarMenuComponent);
    const component = fixture.componentInstance;

    expect(component.menuAbierto()).toBe(false);
    component.alternarMenu(new MouseEvent('click'));
    expect(component.menuAbierto()).toBe(true);
    component.cerrarMenu();
    expect(component.menuAbierto()).toBe(false);
  });
});