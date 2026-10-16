// Configuracion de despliegue del frontend.
//
// Este archivo se copia tal cual a la raiz del build (queda junto a
// index.html) y se puede EDITAR EN EL SERVIDOR sin recompilar el frontend.
//
// Cambia la URL por la del backend real (FastAPI):
//   window.__API_BASE__ = "https://midominio.com/api";
//   window.__API_BASE__ = "http://123.45.67.89:8000/api";
//
// Si el frontend y la API se sirven bajo el mismo dominio con un proxy inverso
// que manda /api al backend, alcanza con "/api".
//
// El valor por defecto apunta al backend local (desarrollo).
window.__API_BASE__ = "http://127.0.0.1:8000/api";
