# Skill: Garmin Operations

## Purpose

Operate Garmin as both input source and delivery channel for planned training.

## Use Cases

- import recent activities
- import daily recovery metrics
- upload planned workouts
- review a planned session completed with Garmin

## Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
python scripts/garmin/review_planned_session.py --date YYYY-MM-DD
```

## Rules

- keep credentials local only
- repository YAML files stay as source of truth
- imported raw files go under `training/completed/imports/garmin/`
- if Garmin rate limits, retry later and do not fake missing data

## Expected Repository Traces

- raw Garmin import files
- upload records when workouts are scheduled
- normalized completed activity YAML
- detailed review markdown and analysis JSON
