import { Routes } from '@angular/router';
import { ConciliacionComponent } from './pantallas/conciliacion/conciliacion';

export const routes: Routes = [
  {
    path: '',
    component: ConciliacionComponent,
    title: 'Conciliación Bancaria Automática',
  },
  { path: '**', redirectTo: '' },
];