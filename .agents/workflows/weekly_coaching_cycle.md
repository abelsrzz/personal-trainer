# Workflow: Weekly Coaching Cycle

The operational week always runs from Monday to Sunday.

## Daily Or Post-Workout

1. capture completed workout manually or from Garmin
2. if Garmin-linked, run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD` unless the user asks not to contact Garmin
3. if working offline, run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin`
4. read `planning/coach_decision.md` and `athlete/status_dashboard.md`
5. decide whether to keep or replanify the current week
6. update `athlete/shin_tracker.yaml` if the athlete reports periosteum pain

## Sunday Cycle

1. refresh local coach status with `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` if no fresh dashboard exists
2. review the current week
3. archive the outgoing week when needed
4. read active block instructions
5. read `planning/coach_decision.md`, `athlete/status_dashboard.md` and `planning/goal_gates.yaml`
6. consider recent execution, fatigue, shin status and races
7. generate the next `planning/weeks/semana_actual.md`
8. generate `planning/weeks/generated/semana_actual.pdf` and send it by Telegram

## Replanning Triggers

- poor workout execution with meaningful cause
- rising fatigue
- shin pain or injury risk
- `planning/coach_decision.md` status is `red`
- `planning/coach_decision.md` status is `yellow` and the next week would increase load
- schedule disruption
- relevant new race or event

## Coach Decision Rules

- `green`: keep the plan and allow only small progression if the shin is quiet.
- `yellow`: keep structure but do not increase volume or intensity.
- `red`: reduce load, replace quality with easy running or rest, and protect the shin.
