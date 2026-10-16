import { Component } from '@angular/core';
import { ShellComponent } from './componentes/shell/shell';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [ShellComponent],
  templateUrl: './app.html'
})
export class AppComponent {
  title = 'frontend';
}
