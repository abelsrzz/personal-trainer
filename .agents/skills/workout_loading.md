# Skill: Workout Loading

## Purpose

Create, update, normalize and schedule planned workouts with the repository as source of truth.

## Use Cases

- create a new planned workout YAML
- adjust an already planned session
- convert a coaching idea into structured workout steps
- prepare a workout for Garmin upload

## Inputs To Read First

- `planning/weeks/semana_actual.md`
- relevant block in `planning/blocks/`
- recent reviews in `training/completed/reviews/`
- reference workouts in `training/planned/workouts/`

## Output Rules

- create or update `training/planned/workouts/YYYY-MM-DD_<slug>.yaml`
- keep the workout description aligned with the coaching intent
- use heart rate targets for easy and long runs
- use pace targets mainly for quality work
- keep structure minimal and explicit

## Validation Checklist

1. date matches the active week
2. sport is correct
3. estimated duration is coherent
4. steps are ordered and complete
5. targets are realistic for the athlete status
6. if requested, upload with Garmin and keep the upload trace

## Related Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
```
