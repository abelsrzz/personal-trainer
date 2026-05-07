# Skill: Completed Workout Inspection

## Purpose

Inspect completed sessions in depth before making coaching decisions.

## Use Cases

- review a just-finished planned workout
- inspect a recent Garmin run without changing the week yet
- compare execution against the intended stimulus
- identify hidden signals beyond basic pace and average heart rate

## Data Sources

- `training/completed/imports/garmin/activities/<date>_<id>/summary.json`
- `training/completed/imports/garmin/activities/<date>_<id>/details.json`
- `training/completed/activities/*.yaml`
- `training/completed/reviews/*.md`
- matching file in `training/planned/workouts/*.yaml`

## Analysis Minimum

- plan versus completed distance and duration
- time in target zone and time above target
- splits and pacing trend
- first half versus second half drift
- cadence, power, stride length, ground contact time, vertical oscillation, vertical ratio
- terrain and temperature context
- implications for the next days

## Preferred Automation

For planned Garmin runs, use:

```bash
source .venv/bin/activate
python scripts/garmin/review_planned_session.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
```

For normal end-to-end post-workout operation, prefer `coach_sync.py --date YYYY-MM-DD` because it imports, reviews when possible and refreshes the dashboard/decision.

## Output Rules

- if a formal review is requested, write both normalized activity and review artifacts
- keep findings actionable for planning
- do not stop at average pace and average HR
- include the resulting `planning/coach_decision.md` status when planning implications are discussed
