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
- Telegram remote OpenCode bridge added for self-hosted access
- First Garmin workout upload and scheduling already proven

## Athlete Highlights

- Current key limitation: left shin discomfort with periostitis history
- Current references: 5k 4:15/km, 10k evidence band 4:22-4:26/km
- Garmin race reference: 2026-02-07 Padron, 10.08 km around 4:26/km, avg HR 186 bpm
- Short interval ability exists around 4:00/km reps, but current limiter is durability and shin tolerance
- Easy running controlled mainly by HR, with Z2 at 141-155 bpm

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
- For web interpretation, treat the dashboard page as the single analysis surface; the old separate decision page is now only a redirect.
- Read `planning/coaching_playbook.md` as the default prescription policy.
- Read `planning/session_selection_matrix.yaml` before selecting workout families.
- Read `planning/workout_evaluation_rules.md` after completed-session reviews and before replanning.
- Read `planning/context_automation_policy.md` to know which other files are mandatory for the current coaching task.
- Read `athlete/response_profile.yaml` to bias decisions toward the athlete's current likely response pattern.
- Treat `red` as reduce or replace quality, `yellow` as maintain without increasing load, and `green` as allow small progression if shin status is quiet.
- `athlete/shin_tracker.yaml` now receives automatic promotions from subjective feedback when tibial/periosteum pain is detected; manual updates remain valid for corrections or added context.

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
