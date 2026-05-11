# Garmin Scripts

Espacio reservado para el adaptador local de Garmin.

## Scripts disponibles

- `sync_garmin.py`: importa actividades recientes y metricas diarias.
- `athlete_sync.py`: aplica al repositorio local el snapshot de perfil Garmin del atleta.
- `review_planned_session.py`: compara una sesion planificada con la actividad real de Garmin.
- `coach_engine.py`: genera estado del atleta, decision de carga y gates del objetivo.
- `coach_sync.py`: orquesta Garmin, revision y dashboard en un solo comando.
- `training/planned/workouts/library_run_templates.yaml`: biblioteca base multidiestancia de sesiones.
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json`: snapshot local de perfil Garmin, FC y gear.

## Preparacion

1. Crea un entorno virtual.
2. Instala `requirements.txt`.
3. Crea `garmin/local_credentials.yaml` a partir de `garmin/local_credentials.yaml.example`.

## Ejemplos

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/2026-05-04_rodaje_10km_z2.yaml
python scripts/garmin/post_workout_refresh.py
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
python scripts/garmin/coach_engine.py --as-of YYYY-MM-DD --days 28
python scripts/garmin/sync_garmin.py import-athlete-profile
python scripts/garmin/athlete_sync.py
```

## Salida

- `training/completed/imports/garmin/activities/`
- `training/completed/imports/garmin/daily/`
- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`
- predictor simple de marca dentro de `athlete/status_dashboard.md`
