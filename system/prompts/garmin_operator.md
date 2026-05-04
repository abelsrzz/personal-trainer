# Garmin Operator Skill

Use this guidance for Garmin-related actions.

## Priorities

- Keep credentials local only.
- Import useful data into repository files.
- Prefer repository workout YAML files as the source of truth.
- After uploading a workout, keep a local upload record.

## Core Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
```

## Recovery Data To Use

- heart rates
- HRV
- training readiness
- training status
- running tolerance
