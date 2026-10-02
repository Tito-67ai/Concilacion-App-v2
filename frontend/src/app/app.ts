import { Component } from '@angular/core';
import { ConciliacionComponent } from './pantallas/conciliacion/conciliacion';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [ConciliacionComponent], // <-- Esto es lo que inyecta tu pantalla
  templateUrl: './app.html'
})
export class AppComponent {
  title = 'frontend';
}