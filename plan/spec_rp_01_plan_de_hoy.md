# RP-01 Spec: Plan de Hoy

## Estado

- Item: `RP-01`
- Fase: `phase_01_daily_action`
- Resultado: especificacion lista para implementar

## Problema

RunPilot ya muestra contexto, decision operativa, calendario y detalle de sesiones, pero no tiene un bloque principal que responda de forma inmediata a la pregunta mas importante del usuario:

`Que tengo que hacer hoy, por que y que alternativa tengo si el contexto no acompana?`

Hoy esa respuesta esta fragmentada entre:

- `dashboard.decision`
- `dashboard.decision.session_guidance`
- `planned_workouts()`
- `calendar_day_data()`
- detalle de la sesion planificada

## Objetivo del bloque

Crear un bloque `Plan de hoy` que sea el centro operativo de la home y que sirva como base para las siguientes capacidades:

- CTA sobre la sesion del dia
- feedback post-entreno
- replanificacion visible
- reintentos de subida a Garmin

## Principios UX

1. Debe responder en menos de 5 segundos a lo esencial.
2. Debe mezclar prescripcion y contexto, no solo listar una sesion.
3. Debe ofrecer alternativas sin obligar a navegar por varias pantallas.
4. Debe degradar bien si faltan datos o no hay sesion planificada.
5. Debe ser util tanto en desktop como en movil.

## Ubicacion recomendada

### Home `/`

- Debe aparecer inmediatamente despues del `hero` principal.
- Debe ocupar una banda completa antes de las cards de resumen.

### Dia `/calendar/day/YYYY-MM-DD`

- El mismo modelo de datos debe reutilizarse para una tarjeta superior mas compacta.

## Estructura visual

El bloque debe tener 4 zonas.

### 1. Cabecera

- titulo: `Plan de hoy`
- fecha natural: `Domingo 10/05/2026`
- badge de estado:
  - `Listo para ejecutar`
  - `Sin sesion planificada`
  - `Ya ejecutado`
  - `Protegido`
  - `Pendiente de datos`

### 2. Prescripcion principal

Contenido:

- nombre de la sesion
- tipo de sesion
- duracion estimada
- enlace Garmin si existe
- resumen de 1-2 lineas con el objetivo del dia

Ejemplo de texto:

- `Hoy toca rodaje aerobico Z2 de 45 min para consolidar carga sin elevar riesgo tibial.`

### 3. Motivo y contexto

Subbloque explicativo con 3 piezas:

- `Por que hoy`: traducido desde `dashboard.decision.recommendation` y `action_label`
- `Que vigilar`: maximo 2 alertas, derivadas de readiness, periostio o carga
- `Que priorizar`: maximo 2 etiquetas de `session_guidance.primary_labels`

### 4. Variantes

Tres tarjetas, aunque al principio algunas pueden ser derivadas con reglas simples.

- `Version ideal`
- `Version corta`
- `Version protectora`

Cada variante debe mostrar:

- etiqueta
- duracion estimada
- ajuste resumido
- condicion de uso

## Modelo de datos propuesto

Crear en `scripts/web/app.py` una funcion nueva:

- `today_plan_data() -> dict[str, Any]`

### Payload minimo

```python
{
  "date": "2026-05-10",
  "date_label": "Domingo 10/05/2026",
  "status": "planned_today",
  "status_label": "Listo para ejecutar",
  "readiness_tone": "green",
  "planned_workout": {
    "slug": "2026-05-10_recuperacion_movilidad_30min",
    "name": "Recuperacion y movilidad 30 min",
    "session_kind": "recovery",
    "session_kind_label": "Recuperacion",
    "description": "...",
    "estimated_duration": "30:00",
    "garmin_workout_url": "...",
  },
  "completed_review": None,
  "decision": {
    "status": "yellow",
    "status_label": "Cautela",
    "action_label": "No subir carga",
    "recommendation": "...",
  },
  "why_today": "...",
  "watchouts": ["Periostio 2/10", "No subir intensidad hoy"],
  "priorities": ["Rodaje de recuperacion", "Recuperacion con movilidad"],
  "variants": [
    {
      "key": "ideal",
      "label": "Version ideal",
      "duration_label": "30:00",
      "summary": "Haz la sesion completa como esta planificada.",
      "when": "Si no hay dolor ni fatiga anormal."
    },
    {
      "key": "short",
      "label": "Version corta",
      "duration_label": "20:00",
      "summary": "Recorta el bloque central y conserva activacion y vuelta a la calma.",
      "when": "Si hoy vas justo de tiempo."
    },
    {
      "key": "protective",
      "label": "Version protectora",
      "duration_label": "15:00",
      "summary": "Solo movilidad suave y descarga sin impacto.",
      "when": "Si aparece molestia tibial o sensacion de fatiga alta."
    }
  ],
  "links": {
    "detail_url": "/planned-workouts/2026-05-10_recuperacion_movilidad_30min",
    "day_url": "/calendar/day/2026-05-10",
  }
}
```

## Fuentes de datos actuales

### Fuente 1: `planned_workouts()`

Uso:

- detectar la sesion de hoy
- nombre
- descripcion
- duracion
- tipo
- enlace Garmin

Campo derivado necesario:

- `planned_today = next(item for item in planned_workouts() if item["date"] == today_iso)`

### Fuente 2: `completed_reviews()`

Uso:

- detectar si hoy ya esta ejecutado y revisado
- mostrar estado `Ya ejecutado`
- anclar versiones futuras de feedback y adherencia

### Fuente 3: `dashboard_payload()`

Uso:

- `decision.status`
- `decision.status_label`
- `decision.action_label`
- `decision.recommendation`
- `decision.session_guidance.primary_labels`
- `decision.session_guidance.avoid_labels`
- `daily_metrics`
- `goal_gates.metrics.latest_shin_pain`

### Fuente 4: `calendar_day_data(today_iso)`

Uso:

- consolidar en una misma vista el estado del dia
- reutilizar en la pagina diaria si interesa

## Estados funcionales requeridos

### A. `planned_today`

Condicion:

- existe sesion planificada hoy
- no existe review completada hoy

UI:

- mostrar bloque completo con variantes
- badge `Listo para ejecutar`

### B. `completed_today`

Condicion:

- existe review completada hoy

UI:

- sustituir CTA principal por resumen de ejecucion
- bloque puede seguir mostrando `plan original` y `resultado real`
- badge `Ya ejecutado`

### C. `no_plan_today`

Condicion:

- no hay sesion planificada hoy

UI:

- mostrar guidance del dia igualmente
- mensaje tipo `Hoy no hay sesion planificada. Si entrenas, deberia ser opcional y conservador.`

### D. `protective_today`

Condicion:

- decision roja, readiness mala o periostio por encima de umbral

UI:

- resaltar variante protectora como principal
- badge `Protegido`

### E. `insufficient_data`

Condicion:

- `dashboard.decision.status == unknown` o faltan artefactos clave

UI:

- mostrar bloque minimizado
- mensaje `Todavia no hay suficiente contexto para generar un plan de hoy fiable.`

## Reglas iniciales de variantes

No hace falta un motor complejo en la primera implementacion.
Se puede empezar con reglas simples derivadas.

### Version ideal

- replica exacta de la sesion planificada.

### Version corta

Reglas:

- si la sesion es por tiempo: reducir a 65-70% del total
- conservar calentamiento y vuelta a la calma
- recortar bloque central

### Version protectora

Reglas:

- recovery o mobility: mantener solo movilidad o bloque suave de 15-20 min
- running facil: 20-30 min muy suaves o caminar + movilidad
- calidad: convertir a rodaje muy suave o movilidad

## Traduccion a copy

### `why_today`

Regla inicial:

- base = `dashboard.decision.recommendation`
- si hay planned workout, anadir una frase corta segun tipo de sesion

Ejemplos:

- recovery: `El objetivo hoy es absorber carga y proteger tejido.`
- easy: `El objetivo hoy es sumar sin aumentar demasiado el coste.`
- quality: `El objetivo hoy es estimular calidad dentro del margen permitido por el estado actual.`

### `watchouts`

Prioridad inicial:

1. periostio
2. readiness/training status
3. tope de calidad o carga

Limite:

- maximo 2 items

## Cambios concretos necesarios

### `scripts/web/app.py`

Anadir:

- `today_plan_data()`
- helper para construir variantes
- helper para mapear estado del dia a badge/tono

Modificar:

- `home_page_data()` para incluir `today_plan`
- opcionalmente `calendar_day_data()` para reutilizar mismo payload despues

### `web/templates/index.html`

Anadir:

- nueva seccion `Plan de hoy` tras el `hero`

### `web/templates/calendar_day.html`

Cambiar en fase posterior o en la misma si sale barato:

- incluir una version compacta del bloque cuando la fecha sea hoy

## No entra en RP-01

Esto debe esperar a siguientes items:

- botones de accion persistentes
- marcar hecha / no hecha
- feedback post-entreno
- reenvio a Garmin
- replanificacion automatica real

## Criterio de terminado de RP-01

- Existe especificacion UX clara del bloque.
- Existe payload concreto con campos definidos.
- Las fuentes de datos actuales estan mapeadas.
- Los estados vacios y protectores estan definidos.
- Los cambios exactos de implementacion estan localizados.

## Siguiente item desbloqueado

- `RP-02` Implementar CTA operativos en la sesion del dia.
