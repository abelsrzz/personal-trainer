# Running Coach Workspace

Workspace local para usar OpenCode como entrenador de running.

## Objetivo

- Mantener el perfil completo del atleta.
- Guardar carreras clasificadas como `S`, `A`, `B`, `C` o `D`, incluyendo desnivel aproximado.
- Construir un plan general basado en la unica carrera `S`.
- Desglosar el plan en bloques y semanas.
- Mantener `planning/weeks/semana_actual.md` como fuente activa semanal.
- Importar actividades reales y, mas adelante, sincronizar con Garmin.

## Reglas clave

- Solo puede existir una carrera con prioridad `S`.
- Las carreras `A`, `B`, `C` y `D` pueden ser multiples.
- La semana operativa siempre va de lunes a domingo.
- Cada domingo se genera la siguiente semana a partir del bloque activo, lo hecho la semana previa y las carreras cercanas.
- La semana anterior se archiva en `planning/weeks/archived/<ano>/`.

## Estructura

- `athlete/`: perfil, zonas, salud, zapatillas e historial.
- `races/`: carreras por ano.
- `planning/`: plan general, bloques y semanas.
- `training/`: entrenamientos planificados, importados y revisados.
- `garmin/`: mapeos y log de sincronizacion.
- `scripts/`: automatizaciones futuras.
- `system/`: plantillas, prompts y esquemas internos.
- `.agents/`: memoria operativa local para futuras sesiones de IA.

## Primera carga de datos

Rellena `INPUT_DATOS_REALES.md` en la raiz del proyecto.

## Flujo De Uso

1. Se genera o actualiza `planning/weeks/semana_actual.md`.
2. Despues de cada entrenamiento, me pasas lo realizado o importamos desde Garmin.
3. Para entrenamientos planificados hechos con Garmin, ejecuta `python scripts/garmin/review_planned_session.py --date YYYY-MM-DD` para importar, comparar y generar la revision automaticamente.
4. El entrenamiento se revisa con nota numerica, semaforo y comentario tecnico.
5. Si la ejecucion o la fatiga lo justifican, se replanifica la semana actual.
6. Cada domingo se genera solo la semana siguiente.
7. Cada vez que se modifique `planning/weeks/semana_actual.md`, se puede generar un PDF y enviarlo por Telegram para tenerlo a mano en el movil.

## Garmin V1

El conector inicial esta en `scripts/garmin/sync_garmin.py`.

Preparacion local:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp garmin/local_credentials.yaml.example garmin/local_credentials.yaml
```

Importar actividades recientes:

```bash
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
```

Importar y revisar automaticamente un entrenamiento planificado completado:

```bash
source .venv/bin/activate
python scripts/garmin/review_planned_session.py --date 2026-05-05
```

Salida generada:

- `training/completed/activities/<workout>.yaml`
- `training/completed/reviews/<workout>.md`
- `training/completed/reviews/<workout>.analysis.json`

Importar metricas diarias para enriquecer recuperacion y estado:

```bash
python scripts/garmin/sync_garmin.py import-daily --days 14
```

## Memoria Persistente

Puntos de entrada recomendados para futuras sesiones:

1. `AGENT.md`
2. `.agents/README.md`
3. `.agents/memory/project_snapshot.md`
4. `.agents/workflows/weekly_coaching_cycle.md`

## PDF Y Telegram

Configuracion local:

```bash
cp telegram/bot_config.yaml.example telegram/bot_config.yaml
```

Generar y enviar el PDF actual:

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py send-now
```

Vigilar cambios en `semana_actual.md` y enviar al detectar modificaciones:

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py watch --interval 30
```
