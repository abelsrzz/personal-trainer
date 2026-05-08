# Web Calendar Roadmap

## Objetivo

Evolucionar la vista de calendario del portal web para que:

1. muestre color segun el tipo de sesion
2. permita abrir un detalle por dia
3. combine en una sola vista lo planificado y lo completado

La idea es que el calendario se convierta en la vista principal de seguimiento semanal/mensual, con una lectura rapida del plan, la ejecucion real y el estado del bloque.

## Estado actual

Ahora mismo el portal ya tiene:

1. vista de planificados en lista
2. vista de planificados en calendario mensual
3. enlaces a Garmin para actividades reales y entrenamientos subidos

Limitaciones actuales:

1. todos los entrenamientos se ven visualmente iguales
2. el calendario solo muestra lo planificado
3. no existe una pagina especifica de detalle del dia
4. no hay una capa comun que una plan, ejecucion y revision en un mismo objeto de calendario

## Principios de diseño

1. el calendario debe leerse rapido en movil
2. el color debe comunicar sin depender del texto
3. la combinacion planificado/completado no debe duplicar tarjetas si ambas cosas corresponden a la misma sesion
4. la terminologia debe seguir siendo de producto, no tecnica
5. el detalle del dia debe ser la vista donde confluyen plan, ejecucion, revision y enlace a Garmin

## Mejora 1: Color por tipo de sesion

### Objetivo funcional

Dar a cada sesion una identidad visual consistente para que el usuario reconozca de un vistazo:

1. rodaje suave
2. recuperacion
3. calidad
4. tirada larga
5. fuerza
6. competicion
7. descanso

### Estrategia recomendada

Añadir una capa de clasificacion en `scripts/web/app.py` que traduzca cada entrenamiento a un `session_kind` de presentacion.

### Clasificacion inicial propuesta

1. `easy`
2. `recovery`
3. `quality`
4. `long_run`
5. `strength`
6. `race`
7. `rest`
8. `other`

### Fuentes para clasificar

Planificados:

1. `workout.name`
2. `workout.description`
3. `workout.steps`
4. distancia estimada
5. palabras clave como `rodaje`, `recuperacion`, `rectas`, `activacion`, `especifica`, `tirada`, `fuerza`, `carrera`

Completados:

1. `planned.goal_category` cuando exista en la revision
2. nombre de la sesion planificada
3. metadatos Garmin y distancia total

### Mapeo visual inicial propuesto

1. `easy`: azul suave
2. `recovery`: verde suave
3. `quality`: naranja
4. `long_run`: violeta
5. `strength`: gris acero
6. `race`: rojo
7. `rest`: fondo tenue sin bloque fuerte
8. `other`: neutro

### Tareas concretas

1. crear helper `classify_planned_workout(...)`
2. crear helper `classify_completed_review(...)`
3. añadir `session_kind`, `session_kind_label` y `session_color_class` a los datos enviados a plantilla
4. actualizar `web/static/style.css` con variantes visuales por tipo
5. aplicar el estilo tanto en lista como en calendario

### Riesgos

1. algunas sesiones pueden ser ambiguas solo por nombre
2. si la taxonomia crece demasiado, convendra persistir una categoria explicita en los YAML planificados

## Mejora 2: Detalle del dia

### Objetivo funcional

Poder pulsar un dia del calendario y ver una pagina unica con toda la informacion de esa fecha.

### Ruta propuesta

1. `/calendar/day/2026-05-15`

### Contenido del detalle del dia

Bloque 1. resumen del dia

1. fecha
2. estado del dia: solo planificado, completado, revisado, descanso, carrera
3. numero de elementos asociados

Bloque 2. plan del dia

1. sesiones planificadas de esa fecha
2. descripcion
3. estructura por pasos
4. enlace a Garmin del entrenamiento planificado si existe

Bloque 3. ejecucion real

1. actividad o actividades reales de Garmin de ese dia
2. distancia, duracion, ritmo, FC media
3. enlace a Garmin de cada actividad

Bloque 4. analisis

1. score
2. semaforo
3. riesgo
4. comentario corto de cumplimiento

Bloque 5. contexto

1. notas relevantes del plan de la semana si aplican
2. carrera asociada si coincide con un dia de competicion

### Estrategia de datos

Construir un agregador comun por fecha, por ejemplo:

1. `planned_items`
2. `completed_items`
3. `reviews`
4. `races`
5. `daily_summary`

### Tareas concretas

1. crear helper `calendar_day_data(day: str)`
2. añadir ruta nueva `/calendar/day/{day}`
3. enlazar cada celda del calendario a su detalle
4. enlazar tambien desde listas cuando la fecha sea visible
5. crear plantilla `web/templates/calendar_day.html`

### Riesgos

1. puede haber varias actividades reales el mismo dia
2. puede existir entrenamiento planificado sin revision aunque haya actividad real
3. puede haber carrera sin YAML planificado formal

## Mejora 3: Calendario combinado planificado + completado

### Objetivo funcional

Tener una sola vista mensual que muestre en cada dia:

1. lo que estaba previsto
2. lo que realmente se hizo
3. el nivel de cumplimiento o revision cuando exista

### Enfoque de modelo de datos

Crear una capa intermedia de eventos de calendario, en vez de renderizar directamente `planned_workouts()`.

### Objeto de calendario recomendado

Cada evento deberia exponer al menos:

1. `date`
2. `title`
3. `kind`
4. `source`
5. `planned_workout`
6. `completed_review`
7. `garmin_activity_url`
8. `garmin_workout_url`
9. `status_label`
10. `score`
11. `traffic_light`
12. `detail_url`

### Estados visuales por relacion plan/real

1. `planned_only`: esta programado pero aun no ejecutado
2. `completed_unplanned`: se entreno pero no estaba programado o no esta enlazado
3. `matched_completed`: existe plan y actividad real correspondiente
4. `reviewed`: ademas existe revision generada
5. `race_day`: dia de competicion
6. `rest_day`: dia sin sesion

### Regla de unificacion recomendada

Prioridad para fusionar elementos del mismo dia:

1. usar la revision como objeto principal si existe
2. si no hay revision, intentar unir actividad real con planificada por `workoutId` o por fecha
3. si no hay union clara, mostrar ambos bloques separados dentro del mismo dia

### Presentacion recomendada en celda

Cada celda del calendario deberia poder mostrar:

1. una tarjeta corta del plan
2. una marca visual de completado
3. score o semaforo si hay revision
4. acceso rapido al detalle del dia

### Tareas concretas

1. crear helper `calendar_events()`
2. crear helper `calendar_month_data_combined(month)`
3. reutilizar la clasificacion por color de la mejora 1
4. actualizar `planned_workouts.html` o mover el calendario combinado a una nueva ruta `calendar`
5. decidir si mantener la lista de planificados separada o integrarla como filtro de la misma pagina

### Riesgos

1. enlazar por fecha solo puede ser insuficiente cuando haya dobles sesiones
2. puede haber varias actividades Garmin no asociadas a plan formal
3. la celda mensual puede saturarse si intentamos mostrar demasiada informacion

## Orden recomendado de implementacion

### Fase 1

1. clasificacion por tipo de sesion
2. colores en lista y calendario actual

### Fase 2

1. nuevo agregador por fecha
2. detalle del dia

### Fase 3

1. calendario combinado planificado + completado
2. estados visuales de cumplimiento

### Fase 4

1. filtros por tipo de sesion
2. filtros por estado: planificado, completado, revisado, carrera
3. opcion semanal ademas del calendario mensual

## Archivos previsiblemente afectados

1. `scripts/web/app.py`
2. `web/templates/planned_workouts.html`
3. `web/templates/index.html`
4. `web/static/style.css`
5. nuevo `web/templates/calendar_day.html`

Posible refactor futuro:

1. extraer logica de agregacion/calendario a `scripts/web/calendar_data.py`

## Criterios de aceptacion

### Color por tipo

1. cada sesion visible en lista y calendario muestra color coherente con su tipo
2. la leyenda o el patron visual es consistente y entendible

### Detalle del dia

1. cualquier dia con contenido se puede abrir
2. el detalle muestra plan, ejecucion y revision cuando existan
3. los enlaces Garmin estan accesibles desde esa vista

### Calendario combinado

1. el usuario puede entender en una sola vista que estaba previsto y que se hizo
2. si hay revision, el dia refleja claramente el resultado
3. la interfaz sigue siendo legible en movil

## Decision recomendada para retomarlo

Cuando se implemente, conviene empezar por construir primero el modelo combinado por fecha y solo despues refinar la UI. Esa capa de datos comun reducira duplicaciones y facilitara tanto el detalle del dia como los colores y estados del calendario.
