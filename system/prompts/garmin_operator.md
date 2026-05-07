# Garmin Operator Skill

Use this guidance for Garmin-related actions.

## Priorities

- Keep credentials local only.
- Import useful data into repository files.
- Prefer repository workout YAML files as the source of truth.
- After uploading a workout, keep a local upload record.
- Prefer `coach_sync.py` for normal post-workout operations.
- Keep `athlete/status_dashboard.md` and `planning/coach_decision.md` refreshed after Garmin-linked sessions.

## Core Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
```

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
