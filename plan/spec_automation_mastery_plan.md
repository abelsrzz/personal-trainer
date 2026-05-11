# Automation Mastery Plan

## Tesis

RunPilot no debe comportarse como una coleccion de scripts que el coach dispara manualmente.
Debe comportarse como un entrenador operativo que observa eventos nuevos, recalcula contexto y actualiza por si solo todas las salidas afectadas.

## Objetivo principal

Conseguir que, cuando se complete un entrenamiento o aparezca un dato nuevo relevante, el sistema:

1. detecte el evento sin intervención manual
2. procese el dato nuevo exactamente una vez
3. regenere todos los artefactos derivados afectados
4. deje trazabilidad clara de qué cambió, cuándo y por qué

## Principios de automatizacion

1. Event-driven first: procesar por evento nuevo, no por recordatorio manual.
2. Idempotencia: reejecutar no debe duplicar ni romper estado.
3. Causalidad completa: cada entrenamiento debe propagar todos sus efectos.
4. Garmin-first con fallback local controlado.
5. Observabilidad: logs, manifests y estado de procesamiento visibles.

## Resultado esperado

Cuando entra una actividad completada, el sistema debe actualizar automaticamente, cuando aplique:

- imports de actividad Garmin
- actividad local estructurada
- review plan vs realidad
- feedback pendiente o faltante detectado
- decision del coach
- status dashboard
- progreso contra objetivo
- readiness y señales derivadas
- shin tracker o estado de lesion si el feedback lo exige
- cualquier vista web dependiente del nuevo estado

## Arquitectura objetivo

### 1. Trigger unico post-entreno

Crear un flujo maestro que arranque cuando aparezca una actividad nueva.

Posibles disparadores validos:

- daemon local de polling Garmin
- timer `systemd`
- webhook puente si existe fuente externa fiable

### 2. Registro de eventos procesados

Persistir estado minimo para evitar reprocesar indefinidamente:

- ultima actividad vista
- ultima actividad procesada
- fecha y resultado del pipeline
- errores y reintentos

### 3. Pipeline derivado unico

Un solo pipeline debe encadenar:

1. importar actividad nueva
2. enlazarla con sesion planificada si existe
3. generar o refrescar review
4. actualizar dashboard y coach decision
5. refrescar progreso
6. actualizar estado de lesion si el feedback o la review lo justifican
7. registrar manifest del procesamiento

### 4. Freshness por capability real

No basta con refrescar `coach_decision` al abrir la web.
Debe existir capacidad explicitamente modelada para:

- `post_workout_refresh`
- `completed_review`
- `injury_state`
- `progress_state`

## Riesgos actuales que esta fase debe resolver

1. Dependencia de `coach_sync.py --date YYYY-MM-DD` manual.
2. Review acoplada a una sola fecha operativa.
3. Falta de disambiguacion robusta con multiples sesiones el mismo dia.
4. Feedback subjetivo fuera del motor de decision central.
5. `shin_tracker` dependiente de actualizacion humana.
6. Vistas web que refrescan decision pero no garantizan pipeline post-entreno completo.

## Fases propuestas

### Fase A. Trigger automatico

- detectar actividad nueva sin accion manual
- dejar servicio o timer estable

### Fase B. Pipeline causal completo

- importar -> review -> decision -> dashboard -> progreso
- manifests y estado de ejecucion

### Fase C. Integracion de feedback e injury loop

- meter feedback subjetivo dentro del motor de decision
- actualizar lesion/retorno automaticamente cuando el contexto lo justifique

### Fase D. Supervisión y confianza operativa

- alertas, logs, panel de salud del pipeline
- reintentos seguros
- visibilidad de ultimo procesamiento correcto

## Criterio de exito

El sistema se considera automatizado cuando completar un entrenamiento no requiere ejecutar ningun comando manual para que el estado operativo quede al dia.
