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
- Garmin athlete profile sync implemented to refresh local profile, zones, health and shoes
- 35:00 goal gates and shin tracker added
- Telegram remote bridge for OpenCode implemented
- Telegram remote bridge defaults to `openai/gpt-5.4` with default reasoning and supports `/model` per-chat overrides
- Web portal planning area unified under `planned-workouts`
- Web portal analysis unified under `dashboard`
- Dynamic capability registry and freshness engine added for Garmin-first feature development
- Automatic Garmin data quality report generated in `planning/data_quality_report.md`
- Initial active-cycle manifest added in `planning/cycles/active.yaml` for migration toward multi-cycle support
- Lifecycle scripts added: `scripts/system/start_cycle.py` and `scripts/system/close_cycle.py`
- Automatic post-workout pipeline added with `scripts/garmin/post_workout_refresh.py`, persisted state and web observability
- Weekly planning pipeline added with `scripts/system/weekly_planning_pipeline.py`, prepared-week state and web-triggered actions

## Next Natural Actions

1. Keep the automatic trigger active with `deploy/systemd/post-workout-refresh.timer.example` or run `python scripts/garmin/post_workout_refresh.py` manually only for validation/troubleshooting.
2. Read `athlete/status_dashboard.md` and `planning/coach_decision.md` before changing the active week.
3. Use the synced local athlete files as planning input when Garmin profile refresh succeeded.
4. Validate `athlete/shin_tracker.yaml` when tibial/periosteum symptoms need extra manual context beyond the automatic promotion.
5. Use `planning/goal_gates.yaml` before allowing `35:00` to influence training paces.
6. For remote access, run `opencode serve --hostname 127.0.0.1 --port 4096` and `python scripts/telegram/opencode_bot.py`.
7. Register every new dynamic feature in `system/capabilities/registry.yaml` and enforce freshness through `scripts/system/capability_engine.py`.
8. Use the weekly planning pipeline to prepare the next week without overwriting the active one, and activate it when ready.
