# RP-04 Spec: Captura rapida de feedback post-entreno

## Estado

- Item: `RP-04`
- Fase: `phase_02_feedback_loop`
- Resultado: especificacion lista para implementar

## Problema

RunPilot ya tiene:

- sesion planificada
- ejecucion real importada desde Garmin
- review analitica automatica

Pero sigue faltando la capa mas util para coaching diario:

`Como se sintio realmente el atleta y como interpreta el propio atleta si cumplio o no la sesion?`

Hoy esa informacion no existe de forma estructurada.
Solo hay:

- `training/completed/activities/*.yaml`
- `training/completed/reviews/*.analysis.json`
- `athlete/health.yaml` para contexto mas general

Eso deja fuera senales clave que Garmin no resuelve bien:

- RPE real
- dolor percibido alrededor de la sesion
- cumplimiento subjetivo
- motivo de desviacion
- nota corta contextual

## Objetivo

Definir un formulario minimo y muy rapido que permita capturar feedback en menos de 20 segundos tras entrenar.

Debe servir para:

- enriquecer la lectura de una sesion completada
- complementar la review automatica
- alimentar decisiones futuras sobre carga, dolor y adherencia
- abrir el camino a patrones simples en `RP-06`

## Principios UX

1. Debe poder rellenarse en movil con una mano.
2. Debe pedir lo minimo imprescindible en la primera version.
3. Debe funcionar aunque no exista review automatica todavia.
4. Debe convivir con datos Garmin sin duplicarlos.
5. Debe dejar claro que esto es feedback subjetivo del atleta.

## Formulario minimo

Campos requeridos:

1. `rpe`
   - escala `1-10`
   - etiqueta visible: `Esfuerzo percibido`

2. `pain_level`
   - escala `0-10`
   - etiqueta visible: `Dolor o molestia`

3. `compliance`
   - enum corto
   - opciones:
     - `full` -> `La hice como tocaba`
     - `partial` -> `La hice parcialmente`
     - `modified` -> `La adapte`
     - `aborted` -> `La corte`

4. `note`
   - texto libre corto
   - maximo recomendado: `160` caracteres
   - placeholder tipo: `Piernas pesadas pero controlado`, `Molestia tibial leve al final`, `Sin tiempo para completar el bloque final`

Campos opcionales muy utiles en V1:

5. `time_feeling`
   - enum:
     - `spare` -> `Iba sobrado de tiempo`
     - `ok` -> `Tiempo suficiente`
     - `tight` -> `Iba justo de tiempo`
     - `cut_short` -> `Tuve que recortar por tiempo`

6. `pain_location`
   - texto corto o enum abierto posterior
   - en V1 puede ser texto libre corto

## Lo que no entra en RP-04

No entra todavia:

- formulario largo de sensaciones
- captura por split
- tags avanzadas de superficie, calor o zapatilla
- modelos derivados de fatiga
- integracion directa en `coach_engine.py`

## Formato de almacenamiento recomendado

Crear un nuevo directorio local:

- `training/completed/feedback/`

Formato recomendado:

- un archivo JSON por sesion o por fecha
- nombre alineado con `slug` de la sesion/review cuando exista

Ejemplo:

- `training/completed/feedback/2026-05-07_rodaje_6km_rectas_controladas.feedback.json`

## Payload propuesto

```json
{
  "source": "web_manual_feedback",
  "created_at": "2026-05-10T18:20:00",
  "updated_at": "2026-05-10T18:20:00",
  "date": "2026-05-07",
  "planned_workout_slug": "2026-05-07_rodaje_6km_rectas_controladas",
  "completed_review_slug": "2026-05-07_rodaje_6km_rectas_controladas",
  "garmin_activity_id": 22798592588,
  "athlete_feedback": {
    "rpe": 6,
    "pain_level": 2,
    "pain_location": "tibia izquierda",
    "compliance": "modified",
    "time_feeling": "tight",
    "note": "Recorte un poco el final por tiempo pero sin alarma fisica."
  }
}
```

## Decisiones de modelado

1. El feedback debe vivir separado de `*.analysis.json`.
   - Motivo: la review actual es generada automaticamente y no conviene mezclar escritura humana con artefactos de analisis.

2. El archivo debe enlazar tanto con plan como con review.
   - Motivo: algunas sesiones tendran plan sin review inmediata y otras review disponible al cargar la pantalla.

3. `compliance` subjetivo debe coexistir con cumplimiento automatico.
   - Motivo: una sesion puede salir bien en datos pero mal en sensacion o viceversa.

4. `note` debe ser corta y opcional, no un diario largo.
   - Motivo: minimizar friccion.

## Lectura UX del feedback

En UI, el feedback debe mostrarse como bloque compacto:

- `RPE 6/10`
- `Dolor 2/10`
- `Cumplimiento: adaptada`
- `Tiempo: justo`
- `Nota: ...`

No debe competir visualmente con Garmin ni con la review automatica.
Debe ser un subbloque llamado `Tu feedback`.

## Vistas recomendadas para captura

### 1. Prioridad alta: `web/templates/completed_workout_detail.html`

Motivo:

- ya es la vista con mayor contexto post-entreno
- hay una sola sesion en foco
- es el lugar natural para completar feedback si ya existe review

### 2. Prioridad alta: `web/templates/calendar_day.html`

Motivo:

- permite capturar feedback rapido desde el dia sin entrar a detalle largo
- es util cuando el usuario revisa el dia y quiere dejar la nota rapido

### 3. Prioridad media: `web/templates/index.html`

Motivo:

- solo como CTA de entrada si `today_plan.status == completed_today`
- mejor como enlace `Anadir feedback` hacia el detalle completado, no como formulario embebido en V1

## Estrategia de activacion inicial

Mostrar CTA `Añadir feedback` cuando se cumpla alguna de estas condiciones:

1. existe `completed_review`
2. existe actividad completada enlazada para ese dia
3. no existe aun archivo en `training/completed/feedback/` para ese slug

Si ya existe feedback:

- cambiar CTA por `Editar feedback`
- mostrar resumen compacto del feedback guardado

## API/backend minimo necesario

En `scripts/web/app.py`:

Añadir:

- `COMPLETED_FEEDBACK_DIR`
- `completed_feedback_items() -> dict[str, dict[str, Any]]`
- `completed_feedback_detail(slug: str) -> dict[str, Any] | None`
- `set_completed_feedback(...)`
- `feedback_form_state_for_review(review)` helper opcional

Rutas nuevas propuestas:

- `POST /completed-workouts/{slug}/feedback`
- opcional en la misma fase o siguiente:
  - `POST /calendar/day/{day}/feedback-redirect` no es necesario si el form postea al slug correcto

## Integracion con payloads actuales

### `completed_reviews()`

Debe enriquecerse con:

- `athlete_feedback`
- `feedback_badge`
- `feedback_summary`

### `calendar_day_data()`

Debe pasar el feedback junto a `completed_items`.

### `home_page_data()` y `today_plan_data()`

Cuando `completed_today` exista, debe poder exponer:

- `feedback_present`
- `feedback_cta_url`

## Reglas minimas de validacion

1. `rpe` entre `1` y `10`
2. `pain_level` entre `0` y `10`
3. `compliance` dentro del enum permitido
4. `note` trimmeada y truncada si excede `160` o `200` chars
5. si no hay nota, permitir guardar igual

## Copy recomendado

Titulo del bloque:

- `Tu feedback`

Subtitulo:

- `Completa estas 4 señales para que el sistema entienda mejor como toleraste la sesión.`

Botones:

- `Guardar feedback`
- `Actualizar feedback`

Mensajes flash:

- `Feedback guardado.`
- `Feedback actualizado.`
- `Revisa los campos de esfuerzo y dolor.`

## Criterio de terminado de RP-04

- Existe formulario minimo definido con `RPE`, `dolor`, `cumplimiento` y `nota`.
- Existe formato de almacenamiento local claro y desacoplado de la review automatica.
- Estan mapeadas las vistas donde capturarlo con menor friccion.
- El siguiente paso (`RP-05`) puede implementarlo sin ambiguedad.

## Siguiente item desbloqueado

- `RP-05` Implementar formulario y persistencia de feedback.
