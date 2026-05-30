# Project Snapshot

## Current State

- Athlete data loaded
- Race hierarchy implemented with `S/A/B/C/D`
- Elevation included in race model
- Master plan created from 2026-05-25 to 2027-02-06
- Planning blocks reviewed and restructured on 2026-05-07
- Garmin V1 connector implemented
- Coach engine added for dashboard, load decision and 35:00 gates
- Coach sync added as the preferred one-command Garmin workflow
- Garmin athlete profile sync added to update local athlete profile, zones, health and shoes from Garmin data
- Web portal simplified: planned workouts unified under one planning area and decision merged into dashboard
- Weekly planning pipeline added with safe prepare/activate flow and weekly state persistence
- Consolidated athlete state added with hybrid load, impact-return status, pace bands, permissions and replanning hints
- Load progression engine added with absorbed-week logic and default `~+5%` running progression after impact return
- Training paces engine added to derive family-specific pace bands from recent evidence
- Week replanner added to express structured replace/hold/reduce actions after pain, fatigue or risky execution
- Planning validator added to check prepared weeks before activation
- Web v2 promoted as the primary web surface; web v1 now treated as legacy/deprecated
- Telegram remote OpenCode bridge added for self-hosted access
- First Garmin workout upload and scheduling already proven
- Fueling engine added for races and hard workouts, with automatic hydration/carb-load/supplement plans

## Athlete Highlights

- Current key limitation: left shin discomfort with periostitis history
- Current references: 5k 4:15/km, 10k evidence band 4:22-4:26/km
- Garmin race reference: 2026-02-07 Padron, 10.08 km around 4:26/km, avg HR 186 bpm
- Short interval ability exists around 4:00/km reps, but current limiter is durability and shin tolerance
- Easy running controlled mainly by HR, with Z2 at 145-160 bpm

## Important Files

- `AGENT.md`
- `planning/master_plan.md`
- `planning/blocks/`
- `scripts/garmin/sync_garmin.py`
- `scripts/garmin/coach_sync.py`
- `scripts/garmin/coach_engine.py`
- `scripts/garmin/athlete_sync.py`
- `garmin/mappings.yaml`
- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`
- `planning/goal_gates.yaml`
- `planning/goal_gates.md`
- `athlete/shin_tracker.yaml`
- `athlete/supplements.yaml`
- `planning/fueling_operational.md`
- `planning/fueling_operational.json`
- `scripts/system/fueling_engine.py`
- `planning/coaching_playbook.md`
- `planning/session_selection_matrix.yaml`
- `planning/workout_evaluation_rules.md`
- `planning/context_automation_policy.md`
- `athlete/response_profile.yaml`
- `training/planned/workouts/library_run_templates.yaml`
- `scripts/telegram/opencode_bot.py`
- `scripts/telegram/opencode_bridge.py`
- `deploy/systemd/opencode-server.service.example`
- `deploy/systemd/opencode-telegram-bot.service.example`

## Coach Automation Operating Model

- The default post-workout path is the automatic pipeline `python scripts/garmin/post_workout_refresh.py`, ideally launched by the `systemd` timer.
- Use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` only as a manual recovery path when working from already imported local data.
- When Garmin is contacted, athlete profile state should also be refreshed so planning can use updated resting HR, max HR, VO2max and gear.
- Read `athlete/status_dashboard.md` for load, risk, 35:00 gates and rough performance estimate.
- Read `planning/coach_decision.md` for the operative green/yellow/red decision.
- Read `system/state/athlete_state.json` for the consolidated machine-readable state used by planning and UI surfaces.
- The progression default after impact return is now encoded explicitly: roughly `+5%` running volume over the last absorbed week unless blocked by shin, fatigue or coach color.
- Hybrid planning is now first-class: bike support can carry aerobic, tempo or VO2 stimulus when it protects the tibia better than running.
- Training paces should now evolve from recent evidence by family rather than staying frozen from a single old reference.
- For web interpretation, treat `web_v2` as the primary product surface.
- Treat `web` v1 as deprecated/legacy even if some compatibility routes still exist.
- The old progress page is also only a redirect; analysis now lives in the dashboard/Estado surface.
- Read `planning/coaching_playbook.md` as the default prescription policy.
- Read `planning/session_selection_matrix.yaml` before selecting workout families.
- Read `planning/workout_evaluation_rules.md` after completed-session reviews and before replanning.
- Read `planning/context_automation_policy.md` to know which other files are mandatory for the current coaching task.
- Read `athlete/response_profile.yaml` to bias decisions toward the athlete's current likely response pattern.
- Treat `red` as reduce or replace quality, `yellow` as maintain without increasing load, and `green` as allow small progression if shin status is quiet.
- `athlete/shin_tracker.yaml` now receives automatic promotions from subjective feedback when tibial/periosteum pain is detected; manual updates remain valid for corrections or added context.
- Read `athlete/supplements.yaml` and `planning/fueling_operational.md` when race execution or hard-session fueling matters.
- In the planning web view, prefer preparing the next week first; activating it archives the outgoing active week, updates `semana_actual.md`, sends the PDF by Telegram and attempts Garmin scheduling for changed workouts.
- When changing any future session, treat the task as incomplete unless all operative layers are handled: weekly plan (`planning/weeks/semana_actual.md` or prepared week), dated workout file in `training/planned/workouts/`, and Garmin scheduling/calendar sync when applicable.
- If a future session is replaced and Garmin already had an older scheduled version for that date, always attempt to remove the older duplicate from Garmin/calendar and record the result explicitly.
- Unless the user explicitly says local-only, requests like "change tomorrow", "replace this workout" or similar imply full update across plan, dated workout and Garmin calendar.

## Remote Telegram Operating Model

- Start OpenCode with `opencode serve --hostname 127.0.0.1 --port 4096`.
- Start the bot with `python scripts/telegram/opencode_bot.py`.
- Telegram `allowed_chat_ids` in `telegram/bot_config.yaml` are the access control boundary.
- The Telegram bridge defaults to `openai/gpt-5.4` and does not pass a reasoning `--variant`.
- Use `/model` to show the active model, `/model openai/gpt-5.4` to set one, and `/model reset` to return to default.
- Commit and push are allowed through Telegram only when explicitly requested.
- Destructive commands require confirmation through `/confirm <id>`.

## First Proven Garmin Upload

- Workout: `Rodaje 10 km Z2`
- Local file: `training/planned/workouts/2026-05-04_rodaje_10km_z2.yaml`
- Upload record: `training/planned/workouts/2026-05-04/2026-05-04_rodaje_10km_z2.garmin_upload.json`
