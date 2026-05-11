# RP-13 Spec: Onboarding guiado

## Estado

- Item: `RP-13`
- Fase: `phase_05_onboarding_and_progress`
- Resultado: especificacion lista para implementar

## Problema

RunPilot ya puede operar sobre un atleta configurado, pero el setup actual esta disperso entre varios archivos:

- `athlete/profile.yaml`
- `athlete/health.yaml`
- `athlete/preferences.yaml`
- `athlete/shin_tracker.yaml`
- `races/**/*.yaml`

Eso funciona para una instalacion manual, pero no para una experiencia reusable.
Hoy no existe un flujo claro que diga:

1. que datos hay que pedir
2. que datos pueden venir de Garmin
3. en que orden hay que recogerlos
4. que archivos se escriben o actualizan

## Objetivo

Definir un onboarding guiado para dejar listo un nuevo atleta o una nueva configuracion base sin tener que editar YAMLs a mano.

Debe cubrir como minimo:

- identidad y contexto del atleta
- disponibilidad real
- salud y restricciones
- objetivo principal y carreras soporte
- preferencias de lectura del plan

## Principios

1. Garmin-first: si Garmin puede aportar el dato, se intenta antes de preguntar.
2. Pedir solo lo que cambia realmente la planificacion o la UI.
3. Separar datos estables del atleta de contexto temporal o dolor actual.
4. Evitar formularios largos de una sola pantalla.
5. El onboarding debe dejar el proyecto en un estado operativo minimo.

## Resultado esperado del onboarding

Al terminar, deben existir o quedar actualizados como minimo:

- `athlete/profile.yaml`
- `athlete/health.yaml`
- `athlete/preferences.yaml`
- `athlete/shin_tracker.yaml` si hay antecedente o problema activo
- al menos una carrera `S` dentro de `races/`

Y el sistema debe quedar listo para:

- mostrar `/athlete`
- mostrar `/dashboard`
- generar plan activo y decision del coach

## Flujo propuesto

### Paso 1. Conexion y precarga Garmin

Objetivo:

- intentar poblar automaticamente perfil, FC, gear y metricas diarias disponibles

Entradas:

- credenciales Garmin ya configuradas en el sistema o via setup inicial

Acciones:

1. ejecutar refresh de `athlete_profile`
2. ejecutar refresh de `daily_readiness` cuando sea posible
3. mostrar al usuario que campos ya se han inferido y cuales no

No debe pedir al atleta:

- peso si Garmin ya lo tiene reciente
- resting HR, HRV o readiness si Garmin ya los expone
- zapatillas si Garmin gear ya esta sincronizado

### Paso 2. Perfil base del atleta

Objetivo:

- completar identidad deportiva y disponibilidad real

Campos minimos:

1. `name`
2. `birth_date` o `age`
3. `sex`
4. `city`
5. `years_running`
6. `availability.days_per_week`
7. `availability.hours_per_week.min`
8. `availability.hours_per_week.max`
9. `availability.preferred_quality_days`
10. `availability.preferred_long_run_day`
11. `availability.constraints`
12. `current_context.strength_sessions_per_week`

Destino principal:

- `athlete/profile.yaml`

### Paso 3. Salud, lesiones y restricciones

Objetivo:

- capturar lo minimo necesario para que el sistema no planifique como si el atleta estuviera sano si no lo esta

Campos minimos:

1. `current_issues`
2. `past_injuries`
3. `medical_constraints`
4. `sleep_notes` opcional
5. `stress_notes` opcional
6. `recovery_notes` opcional

Regla especial:

- si el atleta declara periostio, tibia o dolor activo de carrera, activar tambien setup de `shin_tracker`

Campos minimos para `shin_tracker` cuando aplique:

1. localizacion
2. si hay dolor actual
3. valor durante / despues / manana siguiente si ya existe referencia
4. nota corta contextual

Destino principal:

- `athlete/health.yaml`
- `athlete/shin_tracker.yaml` cuando exista riesgo o antecedente relevante

### Paso 4. Objetivo principal y calendario competitivo

Objetivo:

- dejar claro para que carrera se construye el sistema y que carreras de soporte existen

Campos minimos para la carrera principal:

1. `name`
2. `date`
3. `distance`
4. `priority` = `S`
5. `goal.type`
6. `goal.value`
7. `goal.target_pace` cuando aplique
8. `coaching_note` opcional si el objetivo es aspiracional

Campos opcionales para carreras soporte:

- `A`, `B`, `C`, `D`

Reglas:

1. Debe existir una sola carrera `S` activa por onboarding.
2. Si el objetivo declarado es agresivo, debe permitirse guardar igualmente, pero marcandolo como aspiracional en `coaching_note`.
3. Si no hay fecha exacta, se puede guardar provisionalmente con nota visible.

Destino principal:

- `races/<year>/<slug>.yaml`

### Paso 5. Preferencias de lectura y detalle

Objetivo:

- adaptar el formato de salida a como el atleta o el coach quiere consumir la planificacion

Campos minimos:

1. `workout_rating_style`
2. `weekly_plan_format.type`
3. `weekly_plan_format.columns`
4. `session_detail_level`
5. `other_notes` opcional

Destino principal:

- `athlete/preferences.yaml`

### Paso 6. Confirmacion final

Objetivo:

- mostrar resumen de lo inferido, lo declarado y los vacios que siguen abiertos

Debe enseñar:

1. datos tomados de Garmin
2. datos introducidos manualmente
3. archivos que se van a escribir
4. advertencias si falta una pieza importante

## Mapa pedir vs inferir

### Inferir primero desde Garmin

- nombre si existe en snapshot
- edad o birth date derivable
- peso
- FC reposo
- FC max o zonas si existen
- zapatillas / gear
- readiness diaria
- HRV

### Preguntar obligatoriamente

- disponibilidad real semanal
- dias preferidos de calidad
- dia preferido de tirada larga
- restricciones horarias o logisticas
- historial de lesiones no visible en Garmin
- problema activo actual
- objetivo de carrera y prioridad
- preferencias de formato del plan

### Preguntar solo si falta o es ambiguo

- ciudad
- anos corriendo
- numero de sesiones de fuerza
- nota de recuperacion

## Estados vacios que deben soportarse en futura implementacion

1. Garmin no configurado
2. Garmin configurado pero fallo de sync
3. Perfil Garmin parcial
4. Sin carrera objetivo aun
5. Salud declarada como desconocida temporalmente

## Propuesta UX minima

Onboarding en 5 pantallas o pasos:

1. `Conectar y precargar`
2. `Perfil y disponibilidad`
3. `Salud y restricciones`
4. `Objetivo y carreras`
5. `Preferencias y confirmacion`

Cada paso debe permitir:

- guardar borrador
- continuar despues
- volver atras sin perder lo ya introducido

## Persistencia recomendada para futura implementacion

Ademas de escribir YAMLs finales, la implementacion futura puede usar un borrador local:

- `system/state/onboarding_draft.json`

Contenido minimo del borrador:

- paso actual
- datos precargados desde Garmin
- datos manuales ya confirmados
- warnings pendientes

## API/UI minima para futura implementacion

Rutas sugeridas:

- `GET /onboarding`
- `POST /onboarding/garmin-refresh`
- `POST /onboarding/step/profile`
- `POST /onboarding/step/health`
- `POST /onboarding/step/goals`
- `POST /onboarding/step/preferences`
- `POST /onboarding/complete`

Ficheros probables:

- `web/templates/onboarding.html`
- `scripts/web/app.py`
- `system/state/onboarding_draft.json`

## Criterio de terminado de RP-13

- Existe flujo definido de setup del atleta y objetivo.
- Se sabe que parte se infiere desde Garmin y que parte hay que pedir.
- Estan mapeados los archivos finales que debe producir.
- El siguiente build puede implementar la UI sin ambiguedad.

## Siguiente item desbloqueado

- `RP-14` Implementar vista de progreso contra objetivo.
