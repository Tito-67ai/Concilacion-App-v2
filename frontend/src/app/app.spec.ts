import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
// 1. Importamos AppComponent con su nombre real
import { AppComponent } from './app'; 

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([])],
    })
      .compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  // 2. Eliminamos la prueba del título porque ya no existe en tu HTML
});