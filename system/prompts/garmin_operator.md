# Garmin Operator Skill

Use this guidance for Garmin-related actions.

## Priorities

- Keep credentials local only.
- Import useful data into repository files.
- Prefer repository workout YAML files as the source of truth.
- If a planned workout YAML is created or modified for a date that should exist in Garmin, upload and schedule that exact version in Garmin before considering the task complete.
- After uploading a workout, keep a local upload record.
- Prefer `post_workout_refresh.py` or its timer-driven execution for normal post-workout operations.
- Keep `athlete/status_dashboard.md` and `planning/coach_decision.md` refreshed through the automatic pipeline after Garmin-linked sessions.

## Core Commands

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py

# manual and fallback operations
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
```

## Mandatory Upload Rule

- A change to `training/planned/workouts/*.yaml` is not complete until Garmin has been updated too when the session is supposed to appear in the athlete calendar.
- After changing a planned workout, run `schedule-workout-file` for that YAML and verify the corresponding `training/planned/workouts/<date>/<slug>.garmin_upload.json` was refreshed.
- If Garmin upload or scheduling fails, report the failure clearly and keep the task open rather than assuming the local edit is enough.

## Recovery Data To Use

- heart rates
- HRV
- training readiness
- training status
- running tolerance

## Coach Outputs

- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`
