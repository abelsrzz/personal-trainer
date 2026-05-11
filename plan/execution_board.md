# Execution Board

## Current Phase

- `phase_02_feedback_loop`

## In Progress

- Ninguno.

## Ready Next

1. `RP-06` Exponer patrones basicos de respuesta del atleta.
2. `RP-10` Consolidar tarjeta de readiness diaria.
3. `RP-07` Definir triggers de adaptacion visibles.

## Blocked

- Ninguno.

## Completed

- `RP-01` Definir el bloque principal Plan de hoy.
- `RP-02` Implementar CTA operativos en la sesion del dia.
- `RP-03` Implementar reenvio a Garmin y reintentos visibles.
- `RP-04` Definir captura rapida de feedback post-entreno.
- `RP-05` Implementar formulario y persistencia de feedback.

## Decision Log

### 2026-05-10

- Se crea backlog local y sistema de ejecucion.
- Se prioriza empezar por `Plan de hoy` porque tiene mayor impacto sobre percepcion de valor.
- Se completa `RP-01` con una especificacion implementable en `plan/spec_rp_01_plan_de_hoy.md`.
- Queda desbloqueado `RP-02` para implementar CTA operativos sobre la sesion del dia.
- Se completa `RP-02` integrando CTA persistentes en home, detalle y vista diaria para marcar hecha, no hecha o pedir alternativa.
- Se completa `RP-03` con un reenvio manual a Garmin desde la web, persistencia del ultimo intento y badges visibles de sincronizacion.
- Queda activa `phase_02_feedback_loop` con `RP-04` como siguiente foco operativo.
- Se completa `RP-04` con una especificacion implementable de feedback subjetivo, almacenamiento local separado y mapeo claro de vistas y rutas.
- Se completa `RP-05` con captura web de feedback, persistencia por sesion y resumen visible en detalle, dia y listado de completados.
