# Skill: Weekly Planning Cycle

## Purpose

Generate or adjust the active week from recent evidence, race priorities and current athlete tolerance.

## Inputs To Read First

- `AGENT.md`
- `athlete/health.yaml`
- `athlete/zones.yaml`
- `planning/master_plan.md`
- current block in `planning/blocks/`
- `planning/weeks/semana_actual.md`
- `planning/coach_decision.md`
- `athlete/status_dashboard.md`
- `planning/goal_gates.yaml`
- `athlete/shin_tracker.yaml`
- recent completed reviews

## Planning Rules

- protect shin tolerance first
- respect preferred quality days when possible
- keep progression believable
- do not force precision from weak evidence
- carry the current week forward unless execution, fatigue or pain justify changes
- apply the coach decision: green allows small progression, yellow blocks increases, red requires reduction
- do not let the `35:00` goal set workout paces unless goal gates support it

## Standard Flow

1. review recent execution and recovery
2. refresh coach status with `coach_sync.py --skip-garmin` if stale
3. detect any need to replan the current week from `planning/coach_decision.md`
4. generate or edit `planning/weeks/semana_actual.md`
5. ensure planned workouts exist as YAML files when needed
6. if the week file changed, generate PDF and send by Telegram

## Related Outputs

- `planning/weeks/semana_actual.md`
- `training/planned/workouts/*.yaml`
- optional review-driven changes to upcoming sessions

## Related Commands

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py send-now
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
```
