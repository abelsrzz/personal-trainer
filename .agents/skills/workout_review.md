# Skill: Workout Review

## Purpose

Evaluate completed training in a way that is useful for coaching decisions.

## Required Dimensions

- numeric score
- traffic light
- technical comment
- effect on the current week

## Questions

- did the session hit the intended stimulus?
- was effort controlled correctly?
- did pace, heart rate and sensations align?
- was there any shin warning?
- should the next 2-4 days change?
- does `coach_sync.py` produce green, yellow or red after the review?

## Preferred Automation

```bash
source .venv/bin/activate
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
```

If Garmin data is already local, use `--skip-garmin`.
