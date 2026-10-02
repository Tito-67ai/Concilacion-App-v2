import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';

// 1. Corregimos la importación para usar el nombre real de tu clase principal
import { AppComponent } from './app/app'; 

// 2. Le indicamos a Angular que arranque usando AppComponent
bootstrapApplication(AppComponent, appConfig)
  .catch((err) => console.error(err));