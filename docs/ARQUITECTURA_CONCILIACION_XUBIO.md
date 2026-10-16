# Arquitectura y plan: conciliación bancaria + inyección en Xubio

> Documento de diseño técnico. Estado del repo al escribirlo: commit `37ebb10`
> más cambios locales sin commitear (preparación del pivote a estudios).

## 0. Punto de partida real (lo que ya existe)

Antes de agregar nada hay que reconocer qué está construido, porque la mitad del
spec ya vive en el repo:

| Pieza | Archivo | Estado |
|---|---|---|
| Extracción PDF/Excel por banco (11 bancos) | `services/bancos/*`, `services/procesador_central.py` | Implementado |
| Detección de descuadre por fila | `procesador_central._df_to_movimientos` (líneas 271-283, 309-316) | Parcial (por fila, no global) |
| Cruce simple + avanzado | `services/conciliador.py`, `services/conciliador_avanzado.py` | Implementado |
| Clasificación gasto/perc/impuesto | `services/clasificacion.py` | Implementado |
| Asientos de partida doble | `services/asientos_ajuste.py` | Implementado |
| Export FO 02-03 (4 hojas, colores) | `services/exportador.py` | Implementado |
| Cliente REST Xubio (lectura + `enviar_asiento`) | `services/xubio_client.py` | Parcial (`enviar_asiento` sin usar, endpoints sin confirmar) |
| Cliente web Xubio + bot Playwright | `services/xubio_web_client.py`, `bot_xubio.py` | Implementado |
| Endpoint vista previa asientos | `api/rutas/exportar.py` `POST /exportar/asientos` | Implementado |
| Pantalla de revisión/edición de asientos | — | **No existe** |
| Inyección real de asientos en Xubio | — | **No existe** |
| Base de datos | — | **No existe** (`db/session.py`, `models/entities.py` vacíos) |
| Auth (JWT/OAuth2) | — | **No existe** (`core/security.py` vacío) |
| Encriptación de credenciales | `.env` en texto plano | **No existe** |

Conclusión: el spec pide dos cosas bien distintas de tamaño. **Secciones 1, 2 y 4
son evolución** sobre lo existente. **Sección 3 (producción/seguridad) es una
capa nueva** que hoy no tiene ningún cimiento (ni BD ni auth).

---

## 1. Reglas de negocio: datos sin coincidencia

### 1.A Banco con movimiento pero sin contrapartida en contabilidad

Se genera **asiento de ajuste**, clasificado por reglas:

| `tipo` | Patrones (concepto normalizado) | Acción | Contracuenta |
|---|---|---|---|
| `gasto_bancario` | `COM`, `COMISION`, `MANTENIMIENTO`, `CHEQUERA`, `IVA`, `SELLAD`, `INTERES`, `IMP S/DEB`, `IMP S/CRED`, `IMPUESTO LEY 25413` | Asiento automático | `Comisiones` / `IVA` / `Impuestos` / `Sellado` (subcategoría) o `Gastos bancarios` |
| `retencion_impuesto` | `SIRCREB`, `RETENCION`, `PERCEP`, `ING BRUTOS PERCEP`, `RECAUDACION` | Asiento automático | `Ingresos Brutos` / `Impuestos y retenciones a favor` |
| `ingreso_no_registrado` | Acreditación (`haber > 0`) sin comprobante/comercial | **Revisión manual** (`revisar_manual = true`) | Cuenta de cliente **a asignar** por el usuario |
| `debito_automatico` | Débito (`debe > 0`) no comercial y no clasificado arriba | Asiento (marcado para revisar) | `Gastos bancarios` (provisoria) |

### 1.B Contabilidad con registro pero sin movimiento en el banco

- **NO** se genera asiento.
- Estado: **"Pendiente de Conciliación (Diferencia Temporal)"**.
- Se conserva para el período siguiente (cheques diferidos en tránsito,
  depósitos pendientes de acreditación).

> En el código actual esto ya es el grueso del comportamiento
> (`_clasificar_ajustes_y_pendientes`), pero hoy los "pendientes del banco" que
> no son gasto caen todos juntos. La spec pide **separar** `ingreso_no_registrado`
> (revisión) de `debito_automatico` (asiento) y de `pendiente temporal` (mayor).

### Tabla de decisión resumida

```
movimiento sin pareja
├── origen = banco (está en extracto, falta en contabilidad)
│   ├── gasto/impuesto del banco ............ asiento automático
│   ├── retención/percepción ................ asiento automático
│   ├── acreditación comercial .............. marcar "revisar" (sin asiento auto)
│   └── débito no clasificado ............... asiento provisorio (revisar)
└── origen = mayor (está en contabilidad, falta en extracto)
    └── SIEMPRE ............................. "Pendiente de Conciliación" (sin asiento)
```

---

## 2. Contrato JSON del backend para los asientos de ajuste

### 2.1 Asiento individual (extendido sobre `AsientoRespuesta`)

```json
{
  "numero": 1,
  "fecha": "2026-09-30",
  "origen": "banco",
  "tipo": "gasto_bancario",
  "regla": "Comisiones",
  "estado": "propuesto",
  "revisar_manual": false,
  "concepto": "COM MANT CT",
  "referencia": "00012345",
  "cuit": "30712345678",
  "importe": 1500.00,
  "debe": 1500.00,
  "haber": 1500.00,
  "balancea": true,
  "lineas": [
    { "rol": "contracuenta", "cuenta_codigo": "5.1.03", "cuenta": "Comisiones",        "detalle": "COM MANT CT", "debe": 1500.00, "haber": 0.00 },
    { "rol": "banco",        "cuenta_codigo": "1.1.01", "cuenta": "Banco",             "detalle": "COM MANT CT", "debe": 0.00, "haber": 1500.00 }
  ]
}
```

`estado`: `propuesto` | `editado` | `aprobado` | `inyectado` | `error`.

### 2.2 Respuesta de la pantalla de revisión

```json
{
  "periodo": { "desde": "2026-09-01", "hasta": "2026-09-30" },
  "asientos": [ /* 2.1 */ ],
  "pendientes_temporales": [
    { "origen": "mayor", "estado": "pendiente_conciliacion",
      "fecha": "2026-09-29", "concepto": "CHEQUE DIFERIDO", "referencia": "CHQ 001",
      "importe": 80000.00, "nota": "Se conserva para el período siguiente" }
  ],
  "totales": { "cantidad": 12, "debe": 154321.00, "haber": 154321.00 },
  "cuentas_disponibles": [
    { "codigo": "5.1.03", "nombre": "Comisiones", "imputable": true },
    { "codigo": "1.1.01", "nombre": "Banco",      "imputable": true }
  ]
}
```

### 2.3 Payload hacia la API de Xubio (a confirmar contra la documentación)

```json
{
  "fecha": "2026-09-30",
  "descripcion": "Ajuste conciliación bancaria - COM MANT CT",
  "detalle": [
    { "cuentaCodigo": "5.1.03", "debe": 1500.00, "haber": 0.00, "detalle": "COM MANT CT" },
    { "cuentaCodigo": "1.1.01", "debe": 0.00, "haber": 1500.00, "detalle": "COM MANT CT" }
  ]
}
```

### 2.4 Registro de auditoría (una línea JSONL por intento)

```json
{ "ts": "2026-10-16T15:49:59Z", "asiento_numero": 1, "intento": 1,
  "endpoint": "POST /asientos", "http_status": 201, "resultado": "ok",
  "xubio_id": 99881, "duracion_ms": 412 }
```

---

## 3. Arquitectura objetivo

```
┌──────────────────────────────────────────────────────────────────────┐
│ Angular (4200)                                                        │
│  · conciliación (existe)   · revisión de asientos (NUEVO dashboard)   │
└───────────────▲───────────────────────────────────────────────────────┘
                │ HTTPS + JWT/OAuth2 (NUEVO)
┌───────────────┴───────────────────────────────────────────────────────┐
│ FastAPI (/api)                                                        │
│  1. Extracción     procesador_central + bancos/*     (existe)         │
│  2. Validación     validador_saldos.py               (NUEVO)         │
│  3. Conciliación   conciliador_avanzado             (existe)         │
│  4. Reglas negocio reglas_conciliacion.py           (NUEVO)         │
│  5. Asientos       asientos_ajuste.py               (extender)      │
│  6. Integración    xubio_api_client.py              (NUEVO)         │
│  7. Persistencia   db/ (SQLAlchemy) + cifrado AES-256 (NUEVO)        │
└───────────────┬───────────────────────────────────────────────────────┘
                │
        ┌───────┴────────┐
        │ Xubio REST API │  (POST /asientos, con retry/backoff + auditoría)
        └────────────────┘
```

### Capa nueva de seguridad (Sección 3)

- **Persistencia**: SQLAlchemy + SQLite (dev) / PostgreSQL (prod). Tablas:
  `usuarios`, `credenciales_xubio` (valor cifrado), `asientos_ajuste`,
  `auditoria_xubio`, `sesiones`.
- **Cifrado AES-256**: `cryptography.Fernet` (AES-128-CBC + HMAC-SHA256; para
  AES-256 puro usar `AESGCM` con clave de 32 bytes). Clave en
  `settings.SECRET_ENCRYPTION_KEY` (variable de entorno), **nunca** en el repo.
- **Auth**: JWT (access + refresh) u OAuth2 password flow. Endpoints con
  `Depends(usuario_actual)`.
- **Sanitización / env estricto**: `.env` con todas las claves, `.env.example`
  versionado (hoy **no existe**), `.gitignore` que excluya `.env` (hoy **no
  existe**).

---

## 4. Plan paso a paso (fases)

### Fase 1 — Reglas de negocio + clasificación *(sin BD, sin red)*
- Nuevo `services/reglas_conciliacion.py`: `clasificar_sin_coincidencia(...)`
  → `tipo` (`gasto_bancario` | `retencion_impuesto` | `ingreso_no_registrado` |
  `debito_automatico` | `pendiente_temporal`) + `accion` (`asiento` | `revisar` |
  `pendiente`) + `revisar_manual`.
- Refactor de `conciliador_avanzado._clasificar_ajustes_y_pendientes` para usar
  las reglas nuevas; los ingresos no registrados van a "revisión", los del mayor
  a "pendiente temporal".
- Tests: `tests/test_reglas_conciliacion.py`.

### Fase 2 — Export y contrato de asientos
- Extender `AsientoAjuste`/`AsientoRespuesta`: `tipo`, `regla`, `estado`,
  `revisar_manual`, `cuenta_codigo`, `rol`, `balancea`, `cuit`.
- `config.py`: plan de cuentas con **códigos** (`CUENTA_*_CODIGO`) además del
  nombre.
- **Quitar el verde** (`RELLENO_NO_CONCILIADO`) de `exportador.py`; reemplazar
  por sin relleno + etiqueta/columna "SIN COINCIDENCIA".
- Tests de export: actualizar `test_exportador.py` (hoy afirma `FF93C47D`).

### Fase 3 — API de revisión + dashboard UI
- `POST /api/asientos/proponer` (arma la propuesta), `POST /api/asientos/aprobar`
  (recibe cuenta editada por el usuario), `GET /api/asientos/cuentas`.
- Frontend: nueva pantalla/componente "Revisión de asientos" editable (selector
  de cuenta por línea) + botón **"Aprobar e Inyectar en Xubio"**.

### Fase 4 — Conector Xubio REST *(requiere confirmar el contrato de la API)*
- `services/xubio_api_client.py`: mapeo asiento → JSON Xubio, `POST` con
  retry/backoff exponencial, respeto de rate limit (429 + `Retry-After`),
  auditoría JSONL/DB por transacción.
- Endpoint `POST /api/xubio/asientos/inyectar` (recibe asientos aprobados).

### Fase 5 — Validación de saldos (Sección 4)
- `services/validador_saldos.py`:
  `Saldo Inicial + Σ Créditos − Σ Débitos = Saldo Final`. Si no cuadra, warning
  en la respuesta de extracción y alerta en la UI antes de conciliar.

### Fase 6 — Seguridad y producción (Sección 3)
- BD (SQLAlchemy), cifrado AES-256 de credenciales/tokens, JWT/OAuth2,
  `.env.example` + `.gitignore`, hardening de endpoints, CORS estricto.

### Fase 7 — Auditoría de parsers PDF (Sección 4)
- Fixtures por banco, tests de regresión de importes/fechas/CUIT, detección
  automática de banco (hoy la elige el cliente).

---

## 5. Riesgos y decisiones abiertas

1. **BD + auth + AES cambian el proyecto de "app local sin estado" a "servicio
   con usuarios"**. Es la decisión más grande; conviene confirmarla.
2. **El contrato de la API de Xubio está "sin confirmar"** (comentario en
   `xubio_client.py`). Sin la doc real, la Fase 4 es a ciegas.
3. **Quitar el verde contradice** el trabajo de `e3068b0`/`02ca33b`. Se asume
   que la spec nueva manda.
4. **CUIT en extractos**: los parsers PDF **no** extraen CUIT hoy; solo se
   enriquece desde el extracto crudo de 17 columnas. Si se necesita CUIT en el
   asiento, hay que agregarlo a los extractores.
