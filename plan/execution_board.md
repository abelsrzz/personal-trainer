# Execution Board

## Current Phase

- `phase_06_automation_mastery`

## In Progress

- Ninguno.

## Ready Next

1. Revisar cierre funcional del pipeline post-entreno.
2. Evaluar automatizaciones adicionales fuera del flujo post-entreno.
3. Diseñar siguiente fase de automatizacion continua.

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

### 2026-05-11

- Se completa `RP-06` mostrando patrones basicos derivados del feedback subjetivo reciente dentro del dashboard.
- Se reduce el coste de carga en `/athlete` evitando refrescos Garmin duplicados en cada visita.
- Se completa `RP-07` con triggers visibles de fatiga, dolor, tiempo y ejecucion, junto con su traduccion explicita a cambios de plan en el dashboard.
- Se completa `RP-08` mostrando en semana, lista, calendario y dia cuando una sesion sigue original, queda ajustada o entra en modo protegido, con causa y momento visible.
- Se completa `RP-09` activando un modo explicito de lesion o retorno que endurece el guidance y limita el progreso visible cuando el contexto lo exige.
- Se completa `RP-10` consolidando una tarjeta diaria de readiness con estado fresco, neutro, protegido o desactualizado y accion recomendada para hoy.
- Se completa `RP-11` haciendo que el calendario mensual soporte multiples eventos por dia sin perder acceso al detalle diario.
- Se completa `RP-12` mostrando en el detalle del dia una comparacion explicita entre lo prescrito y lo ejecutado, con diferencias visibles y estado de emparejamiento.
- Se completa `RP-13` definiendo un onboarding guiado Garmin-first con pasos, datos minimos, reglas de inferencia y archivos objetivo para futura implementacion.
- Se completa `RP-14` creando una vista dedicada de progreso contra objetivo con lectura clara, focos actuales, riesgos y checkpoints en lenguaje no tecnico.

### 2026-05-12

- Se cierra el plan `RP-01` a `RP-14` como completado.
- Se abre `phase_06_automation_mastery` para eliminar dependencia de pasos manuales tras entrenos completados.
- Se fija como nueva prioridad convertir el sistema en un pipeline automatico post-entreno, Garmin-first, idempotente y observable.
- Se completa `AP-01` definiendo la capability `post_workout_refresh` con contrato claro de trigger, entradas, salidas, estado persistente e idempotencia.
- Se completa `AP-02` creando un trigger local automatico con estado persistente, capability registrada y ejemplos `systemd` para polling periodico de nuevas actividades.
- Se completa `AP-03` desacoplando el refresco post-entreno de `coach_sync.py` por fecha y encadenando review local, decision y progreso por actividad detectada.
- Se completa `AP-04` integrando feedback subjetivo en `coach_engine.py` y permitiendo reproceso automatico de derivados cuando cambia `training/completed/feedback/`.
- Se completa `AP-05` promocionando automaticamente dolor tibial/periostio desde feedback a `athlete/shin_tracker.yaml`, con merge conservador sobre entradas existentes.
- Se completa `AP-06` mostrando en la web la salud del pipeline automatico, ultimo exito, ultimo error y trazabilidad reciente de actividades y feedback procesados.
