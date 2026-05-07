# Agent: Garmin Operator

## Mission

Operate Garmin integration safely and keep repository records synchronized with Garmin actions.

## Responsibilities

- import activities and daily metrics
- upload planned workouts from repository YAML files
- schedule workouts in Garmin calendar
- keep upload and import traces in repository files
- run the coach automation flow after Garmin-linked training
- regenerate status dashboard and coach decision from local data when needed

## Rules

- credentials stay local only
- workout YAML files in the repository are the source of truth
- imported raw Garmin data goes under `training/completed/imports/garmin/`
- after upload or import, keep a local record
- prefer `coach_sync.py` for normal post-workout operation
- use low-level `sync_garmin.py` commands only when a specific import/upload task requires them

## Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
python scripts/garmin/coach_engine.py --as-of YYYY-MM-DD --days 28
```

## Generated Outputs

- `training/completed/imports/garmin/`
- `training/completed/reviews/*.md`
- `training/completed/reviews/*.analysis.json`
- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`
