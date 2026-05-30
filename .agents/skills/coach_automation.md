# Skill: Coach Automation

## Purpose

Use the local coach automation layer to turn Garmin data, reviews, shin status and goal gates into a concrete training decision.

## Preferred Commands

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py
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
- `system/state/athlete_state.json`: consolidated machine-readable state with progression, hybrid load, pace bands and replanning hints

## Web Interpretation

- In the web portal, `dashboard` is the main analysis page.
- The operative decision layer is shown inside `dashboard`; the old separate `decision` route is only a redirect.

## Decision Interpretation

- `green`: maintain plan and allow only small progression if shin status is quiet.
- `yellow`: maintain structure but do not increase load or intensity.
- `red`: reduce load, replace quality with easy running/rest and protect the shin.
- Read `decision.progression` to know whether running volume, running intensity or both are blocked.
- Read `decision.replanning` for explicit replace/hold/keep-bike actions after a risky or poorly absorbed week.

## Goal Gate Interpretation

- Use `planning/goal_gates.yaml` as the measurable source of truth for the `35:00` target.
- Do not prescribe `3:30/km` as a normal training pace until the gates support it.
- If gates are not passed, keep developing the athlete and recalibrate the race target from evidence.

## Shin Tracker Rule

- Update `athlete/shin_tracker.yaml` when Abel reports pain during, after or the next morning.
- Pain `0-2/10` allows normal cautious progression.
- Pain `3/10` blocks load increase.
- Pain `4/10` or more triggers load reduction.

## Preferred Derived Signals

- `athlete_state.athlete.impact_return`: absorbed week, `+5%` default target, blocked dimensions and bike-support requirement
- `athlete_state.athlete.training_paces`: current evidence-based pace bands for fartlek, tempo, 10k and VO2 plus bike HR support bands
- `athlete_state.athlete.hybrid_training`: recent mixed running/bike/elliptical load summary
