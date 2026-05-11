# Next Step

## Active Item

- `AP-07` Cerrar huecos funcionales del pipeline post-entreno

## Why This Next

- La revision `plan/post_workout_pipeline_closure_review.md` confirma que la automatizacion base ya existe, pero aun hay casos donde se declara exito sin cierre funcional completo.
- El hueco principal esta en actividades sin match limpio, sesiones con feedback aun pendiente y falta de refresco inmediato tras guardar feedback.
- Cerrar esto convierte el pipeline en un circuito realmente operativo antes de abrir otra fase de automatizacion.

## Expected Output

1. Estado explicito por actividad: `matched_reviewed`, `unplanned_reviewed` o `ambiguous_match_pending_resolution`.
2. Estado explicito de feedback pendiente o reprocesado.
3. Refresco inmediato de derivados al guardar feedback.

## Completion Check

- Ninguna actividad running nueva queda marcada como procesada sin estado operativo final claro.
- La ausencia de feedback deja de ser invisible.
- Guardar feedback actualiza decision y dashboard sin depender solo del polling.
