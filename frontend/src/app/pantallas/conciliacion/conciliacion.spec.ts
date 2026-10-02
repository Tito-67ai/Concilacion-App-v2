import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

// Aquí está la corrección: importamos ConciliacionComponent
import { ConciliacionComponent } from './conciliacion'; 

describe('ConciliacionComponent', () => {
  let component: ConciliacionComponent;
  let fixture: ComponentFixture<ConciliacionComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConciliacionComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting()
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ConciliacionComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});