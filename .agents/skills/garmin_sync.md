# Skill: Garmin Sync

## Purpose

Use Garmin as a data source and delivery channel for planned workouts.

## Current Capabilities

- import recent activities
- import daily readiness and recovery metrics
- upload and schedule planned running workouts
- run coach sync to import, review and generate dashboard/decision files

## Current Limitations

- Garmin login may rate limit temporarily
- workout payloads may need refinement to preserve exact targets in Garmin UI
- sync is local and credential-based

## Repository Interfaces

- credentials: `garmin/local_credentials.yaml`
- script: `scripts/garmin/sync_garmin.py`
- preferred coach command: `scripts/garmin/coach_sync.py`
- analysis engine: `scripts/garmin/coach_engine.py`
- imports: `training/completed/imports/garmin/`
- planned workouts: `training/planned/workouts/`
- dashboard: `athlete/status_dashboard.md`
- decision: `planning/coach_decision.md`

## Preferred Post-Workout Flow

```bash
source .venv/bin/activate
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
```

Use `--skip-garmin` to refresh dashboard and decision from local files without contacting Garmin.
