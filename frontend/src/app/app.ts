import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet], // <-- Las pantallas se resuelven en app.routes.ts
  templateUrl: './app.html'
})
export class AppComponent {
  title = 'frontend';
}