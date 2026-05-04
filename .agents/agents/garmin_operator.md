# Agent: Garmin Operator

## Mission

Operate Garmin integration safely and keep repository records synchronized with Garmin actions.

## Responsibilities

- import activities and daily metrics
- upload planned workouts from repository YAML files
- schedule workouts in Garmin calendar
- keep upload and import traces in repository files

## Rules

- credentials stay local only
- workout YAML files in the repository are the source of truth
- imported raw Garmin data goes under `training/completed/imports/garmin/`
- after upload or import, keep a local record

## Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
```
