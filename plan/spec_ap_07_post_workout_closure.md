# AP-07 Spec: Cerrar huecos funcionales del pipeline post-entreno

## Contexto

La revision `plan/post_workout_pipeline_closure_review.md` confirma que `AP-01` a `AP-06` ya automatizan deteccion, reproceso, decision, lesion y observabilidad.

Lo que falta no es otro trigger ni otro panel, sino cerrar los casos donde el pipeline declara exito sin dejar un estado post-entreno completamente resuelto.

## Objetivo

Hacer que toda actividad nueva termine exactamente en uno de estos estados operativos explicitos:

1. `matched_reviewed`
2. `unplanned_reviewed`
3. `ambiguous_match_pending_resolution`

Y que, ademas, el sistema deje explicito si el feedback subjetivo esta:

1. `pending`
2. `received`
3. `reprocessed`

## Problemas a resolver

### 1. Actividad sin plan o con multiples planes

Hoy se puede marcar una actividad como procesada sin crear review final util.

Se necesita:

- artefacto local canonico por actividad
- estado de matching explicito
- review o stub operativo incluso cuando no haya match perfecto

### 2. Falta de estado `feedback_pending`

Hoy el sistema solo reacciona cuando aparece feedback.

Se necesita:

- detectar automaticamente que falta feedback tras procesar una actividad
- dejarlo visible en estado persistente y UI

### 3. Falta de cierre inmediato al guardar feedback

Hoy el guardado web depende del siguiente polling para regenerar derivados.

Se necesita:

- disparo local seguro e idempotente tras guardar feedback
- o encolado explicito con ejecucion inmediata del reproceso derivado

## Definition Of Done

1. Cada nueva actividad running genera un artefacto local canonico, aunque no exista plan o exista ambiguedad.
2. El pipeline no registra `success` silencioso cuando el matching queda sin resolver; deja un estado explicito y visible.
3. Existe estado persistente para feedback pendiente por actividad o review.
4. La web muestra claramente que sesiones completadas siguen pendientes de feedback.
5. Guardar feedback desde la web refresca decision, dashboard y derivados sin esperar al siguiente polling periodico.
6. El flujo sigue siendo idempotente y seguro ante reintentos.

## Ficheros candidatos

- `scripts/garmin/post_workout_refresh.py`
- `scripts/garmin/review_planned_session.py`
- `scripts/web/app.py`
- `web/templates/completed_workouts.html`
- `web/templates/completed_workout_detail.html`
- `system/state/post_workout_refresh_state.json`

## Resultado esperado

Despues de `AP-07`, completar un entreno deja siempre una lectura operativa cerrada:

- que actividad entro
- como quedo clasificada frente al plan
- si falta feedback del atleta
- si los derivados ya fueron recalculados
