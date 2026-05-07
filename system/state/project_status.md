# Project Status

## Current Stage

- Base athlete data loaded
- Race model loaded
- Master plan generated
- Planning blocks generated
- Garmin V1 connector implemented
- Workflow for post-workout review defined
- Coach automation implemented with `coach_sync.py` and `coach_engine.py`
- Status dashboard and coach decision files generated from local Garmin/review data
- 35:00 goal gates and shin tracker added

## Next Natural Actions

1. Run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD` after Garmin-linked workouts.
2. Use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` when working from local data only.
3. Read `athlete/status_dashboard.md` and `planning/coach_decision.md` before changing the active week.
4. Update `athlete/shin_tracker.yaml` when periosteum symptoms are reported.
5. Use `planning/goal_gates.yaml` before allowing `35:00` to influence training paces.
