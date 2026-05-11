# AP-01 Spec: Capability `post_workout_refresh`

## Estado

- Item: `AP-01`
- Fase: `phase_06_automation_mastery`
- Resultado: especificacion lista para implementar

## Problema

Hoy el proyecto tiene piezas sueltas para el flujo post-entreno:

- `scripts/garmin/sync_garmin.py` importa actividades
- `scripts/garmin/review_planned_session.py` genera review plan vs realidad
- `scripts/garmin/coach_engine.py` genera decision, dashboard y progreso derivado
- `scripts/garmin/coach_sync.py` las encadena manualmente

Pero no existe una capability unica y explicita que modele:

`entreno completado -> importar -> revisar -> recalcular todo el estado afectado`

Eso deja varios problemas:

1. Dependencia de un comando manual.
2. Falta de contrato claro de entradas y salidas.
3. Falta de estado de procesamiento idempotente.
4. La web puede refrescar decision, pero no necesariamente toda la causalidad del entreno.

## Objetivo

Definir una capability unica llamada `post_workout_refresh` que represente el pipeline automatico post-entreno completo.

Debe servir como base para:

- el trigger automatico de nuevas actividades
- el registro en `system/capabilities/registry.yaml`
- la implementacion del pipeline idempotente
- la observabilidad del estado de procesamiento

## Definicion de la capability

### Nombre

- `post_workout_refresh`

### Source of truth

- Garmin activity feed cuando haya conectividad
- cache local de imports Garmin cuando el sistema trabaje offline

### Consumer principal

- automatizacion interna del sistema tras detectar nueva actividad

### Consumers secundarios

- web:/dashboard
- web:/completed-workouts
- web:/calendar
- web:/progress
- planning:coach_engine
- telegram:/status

## Trigger semantico

La capability debe dispararse cuando ocurra cualquiera de estos eventos:

1. aparece una nueva actividad Garmin dentro de la ventana de observacion
2. aparece una actividad local nueva no procesada aun
3. se añade o modifica feedback subjetivo de una actividad ya revisada

El trigger inicial a implementar en `AP-02` sera solo el caso `1`, pero el contrato debe contemplar los tres.

## Entradas del pipeline

### Obligatorias

1. `activity_id` Garmin o identificador local equivalente
2. `activity_date`
3. `source`
   - `garmin_poll`
   - `local_import`
   - `feedback_update`

### Contextuales

4. planned workout candidate(s) del mismo dia
5. daily metrics recientes
6. athlete profile cache
7. feedback subjetivo existente para el slug si ya existe
8. shin tracker actual

## Salidas esperadas

Cuando el pipeline se complete correctamente, deben quedar consistentes, cuando apliquen:

1. `training/completed/imports/garmin/activities/...`
2. `training/completed/activities/...`
3. `training/completed/reviews/*.analysis.json`
4. `planning/coach_decision.json`
5. `planning/coach_decision.md`
6. `athlete/status_dashboard.md`
7. progreso contra objetivo derivado visible en web
8. estado de proteccion / retorno actualizado
9. `athlete/shin_tracker.yaml` si el feedback o review justifican promocion a estado estructurado
10. manifest del procesamiento

## Estado persistente requerido

La implementacion debe crear un estado de procesamiento dedicado, por ejemplo:

- `system/state/post_workout_refresh_state.json`

Contenido minimo:

1. `last_seen_activity_id`
2. `last_processed_activity_id`
3. `last_processed_at`
4. `last_successful_run`
5. `last_error`
6. `processed_activities`
   - `activity_id`
   - `activity_date`
   - `review_slug`
   - `result`
   - `processed_at`

## Reglas de idempotencia

1. Procesar dos veces la misma actividad no debe duplicar reviews ni artefactos.
2. Si una review ya existe y la actividad no cambió, no debe recalcular innecesariamente salvo `force`.
3. Si el pipeline falla a mitad, debe quedar trazado qué pasos se completaron y cuáles no.
4. Reintentar debe reanudar de forma segura sobre artefactos ya creados.

## Fases internas del pipeline

### Fase 1. Deteccion

- identificar actividades nuevas no procesadas

### Fase 2. Import operativo

- asegurar `summary.json` y `details.json`
- materializar actividad local estructurada si aplica

### Fase 3. Matching con plan

- localizar planned workout del mismo dia
- si hay multiples candidatos, aplicar estrategia de desambiguacion

### Fase 4. Review

- generar o refrescar review plan vs realidad
- dejar `score`, `traffic_light`, `risk_level`, `compliance`

### Fase 5. Derivados de coaching

- recalcular coach decision
- recalcular status dashboard
- recalcular progreso y modos de proteccion

### Fase 6. Derivados de lesion

- si hay dolor subjetivo o review preocupante, promover senal a `shin_tracker` cuando corresponda

### Fase 7. Manifest y observabilidad

- registrar resultado por actividad y por run

## Relacion con capabilities existentes

`post_workout_refresh` no sustituye estas capabilities, sino que las orquesta:

- `daily_readiness`
- `athlete_profile`
- `coach_decision`

Ademas, esta spec recomienda crear mas adelante capacidades derivadas separadas para:

- `completed_review`
- `injury_state`
- `progress_state`

## Registro propuesto en `registry.yaml`

Configuracion objetivo orientativa:

```yaml
post_workout_refresh:
  description: Process every newly completed workout end-to-end and refresh all derived athlete state.
  source_of_truth: garmin_plus_local_feedback
  local_cache:
    - training/completed/imports/garmin/activities/
    - training/completed/activities/
    - training/completed/reviews/
    - training/completed/feedback/
    - planning/coach_decision.json
    - athlete/status_dashboard.md
    - system/state/post_workout_refresh_state.json
  freshness:
    strategy: scheduled_refresh
    max_age_minutes: 5
  sync:
    command:
      - python
      - scripts/garmin/post_workout_refresh.py
  consumers:
    - automation:post_workout_pipeline
    - web:/dashboard
    - web:/calendar
    - web:/completed-workouts
    - web:/progress
  stale_behavior: show_cached_with_warning
```

## Script objetivo recomendado

La implementacion futura no deberia seguir colgando de `coach_sync.py` como nombre principal para este caso.

Crear:

- `scripts/garmin/post_workout_refresh.py`

Rol:

- detectar nuevas actividades
- decidir que hay que reprocesar
- encadenar import, review, decision, progreso y lesion
- escribir estado y manifest

`coach_sync.py` puede seguir existiendo como orquestador manual o compatibilidad operativa, pero esta capability debe tener su propio entrypoint.

## Casos especiales obligatorios

### 1. Multiples sesiones el mismo dia

La capability no puede fallar con `disambiguation not implemented`.
Debe definir al menos una politica:

- por deporte
- por proximidad de distancia
- por hora planificada si existe en futuro
- o dejar estado `needs_manual_match` trazado sin romper el resto del pipeline

### 2. Actividad sin plan enlazado

Debe:

- importarse
- quedar visible como completada
- regenerar decision y progreso igualmente
- registrar que no hubo matching con plan

### 3. Feedback posterior a la review

Si el atleta añade feedback despues de la review automatica:

- el pipeline debe poder reprocesar derivados sin reimportar toda Garmin si no hace falta

### 4. Garmin no disponible

Debe soportar:

- modo `skip-garmin`
- uso de cache local con warning visible

## Criterio de terminado de AP-01

- Existe contrato claro de `post_workout_refresh`.
- Estan definidos trigger, entradas, salidas, estado persistente e idempotencia.
- Queda propuesto el registro en capabilities y el script objetivo.
- `AP-02` puede implementarse sin ambiguedad.

## Siguiente item desbloqueado

- `AP-02` Automatizar deteccion de actividades nuevas.
