# Garmin Scripts

Espacio reservado para el adaptador local de Garmin.

## Script disponible

- `sync_garmin.py`: importa actividades recientes y metricas diarias.

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
```

## Salida

- `training/completed/imports/garmin/activities/`
- `training/completed/imports/garmin/daily/`
