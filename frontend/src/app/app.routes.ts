import { Routes } from '@angular/router';
import { ConciliacionComponent } from './pantallas/conciliacion/conciliacion';

export const routes: Routes = [
  {
    path: '',
    component: ConciliacionComponent,
    title: 'Conciliación Bancaria Automática',
  },
  {
    path: 'importar-pdf',
    loadComponent: () =>
      import('./pantallas/importar-pdf/importar-pdf').then((m) => m.ImportarPdfComponent),
    title: 'Importación vía PDF',
  },
  {
    path: 'procesando-pdf',
    loadComponent: () =>
      import('./pantallas/procesando-pdf/procesando-pdf').then((m) => m.ProcesandoPdfComponent),
    title: 'Estamos analizando tu PDF',
  },
  {
    path: 'verificar-importacion',
    loadComponent: () =>
      import('./pantallas/verificar-importacion/verificar-importacion').then(
        (m) => m.VerificarImportacionComponent,
      ),
    title: 'Verificá la información extraída del PDF',
  },
  { path: '**', redirectTo: '' },
];