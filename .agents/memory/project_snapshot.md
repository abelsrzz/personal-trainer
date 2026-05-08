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
- `garmin/mappings.yaml`
- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`
- `planning/goal_gates.yaml`
- `planning/goal_gates.md`
- `athlete/shin_tracker.yaml`
- `training/planned/workouts/library_run_templates.yaml`
- `scripts/telegram/opencode_bot.py`
- `scripts/telegram/opencode_bridge.py`
- `deploy/systemd/opencode-server.service.example`
- `deploy/systemd/opencode-telegram-bot.service.example`

## Coach Automation Operating Model

- Run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD` after Garmin-linked sessions when credentials/network use is acceptable.
- Run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` when using already imported local data.
- Read `athlete/status_dashboard.md` for load, risk, 35:00 gates and rough performance estimate.
- Read `planning/coach_decision.md` for the operative green/yellow/red decision.
- Treat `red` as reduce or replace quality, `yellow` as maintain without increasing load, and `green` as allow small progression if shin status is quiet.
- Update `athlete/shin_tracker.yaml` whenever Abel reports periosteum pain during, after or the next morning.

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
