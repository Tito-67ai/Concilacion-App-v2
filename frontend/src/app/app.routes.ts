import { Routes } from '@angular/router';
import { ConciliacionComponent } from './pantallas/conciliacion/conciliacion';
import { ImportarPdfComponent } from './pantallas/importar-pdf/importar-pdf';
import { ProcesandoPdfComponent } from './pantallas/procesando-pdf/procesando-pdf';
import { VerificarImportacionComponent } from './pantallas/verificar-importacion/verificar-importacion';

export const routes: Routes = [
  {
    path: '',
    component: ConciliacionComponent,
    title: 'Conciliación Bancaria Automática',
  },
  {
    path: 'importar-pdf',
    component: ImportarPdfComponent,
    title: 'Importación vía PDF',
  },
  {
    path: 'procesando-pdf',
    component: ProcesandoPdfComponent,
    title: 'Analizando tu PDF',
  },
  {
    path: 'verificar-importacion',
    component: VerificarImportacionComponent,
    title: 'Verificación de la importación',
  },
  { path: '**', redirectTo: '' },
];
