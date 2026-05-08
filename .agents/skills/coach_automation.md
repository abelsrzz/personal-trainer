# Skill: Coach Automation

## Purpose

Use the local coach automation layer to turn Garmin data, reviews, shin status and goal gates into a concrete training decision.

## Preferred Commands

```bash
source .venv/bin/activate
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
python scripts/garmin/coach_engine.py --as-of YYYY-MM-DD --days 28
```

## When To Use

- after a Garmin-linked workout
- before revising `planning/weeks/semana_actual.md`
- before generating the next week
- when checking whether `35:00` can influence training paces
- when the user asks for current status, fatigue, progression or risk

## Generated Files

- `athlete/status_dashboard.md`: human-readable load, risk, gates and performance estimate
- `planning/coach_decision.md`: operative green/yellow/red decision
- `planning/coach_decision.json`: structured decision data

## Web Interpretation

- In the web portal, `dashboard` is the main analysis page.
- The operative decision layer is shown inside `dashboard`; the old separate `decision` route is only a redirect.

## Decision Interpretation

- `green`: maintain plan and allow only small progression if shin status is quiet.
- `yellow`: maintain structure but do not increase load or intensity.
- `red`: reduce load, replace quality with easy running/rest and protect the shin.

## Goal Gate Interpretation

- Use `planning/goal_gates.yaml` as the measurable source of truth for the `35:00` target.
- Do not prescribe `3:30/km` as a normal training pace until the gates support it.
- If gates are not passed, keep developing the athlete and recalibrate the race target from evidence.

## Shin Tracker Rule

- Update `athlete/shin_tracker.yaml` when Abel reports pain during, after or the next morning.
- Pain `0-2/10` allows normal cautious progression.
- Pain `3/10` blocks load increase.
- Pain `4/10` or more triggers load reduction.
