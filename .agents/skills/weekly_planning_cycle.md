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
- recent completed reviews

## Planning Rules

- protect shin tolerance first
- respect preferred quality days when possible
- keep progression believable
- do not force precision from weak evidence
- carry the current week forward unless execution, fatigue or pain justify changes

## Standard Flow

1. review recent execution and recovery
2. detect any need to replan the current week
3. generate or edit `planning/weeks/semana_actual.md`
4. ensure planned workouts exist as YAML files when needed
5. if the week file changed, generate PDF and send by Telegram

## Related Outputs

- `planning/weeks/semana_actual.md`
- `training/planned/workouts/*.yaml`
- optional review-driven changes to upcoming sessions

## Related Commands

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py send-now
```
