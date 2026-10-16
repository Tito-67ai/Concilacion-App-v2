// Tipos de cosas que se inyectan en runtime desde `public/config.js`
// (URL de la API editable en el servidor sin recompilar).

export {};

declare global {
  // La define `config.js`; si falta, cada consumidor cae al backend local.
  var __API_BASE__: string | undefined;
}
