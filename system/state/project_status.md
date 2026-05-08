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

## Next Natural Actions

1. Run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD` after Garmin-linked workouts.
2. Use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` when working from local data only.
3. Read `athlete/status_dashboard.md` and `planning/coach_decision.md` before changing the active week.
4. Use the synced local athlete files as planning input when Garmin profile refresh succeeded.
5. Update `athlete/shin_tracker.yaml` when periosteum symptoms are reported.
6. Use `planning/goal_gates.yaml` before allowing `35:00` to influence training paces.
7. For remote access, run `opencode serve --hostname 127.0.0.1 --port 4096` and `python scripts/telegram/opencode_bot.py`.
8. Register every new dynamic feature in `system/capabilities/registry.yaml` and enforce freshness through `scripts/system/capability_engine.py`.
