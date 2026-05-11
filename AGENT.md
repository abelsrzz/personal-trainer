# Running Coach Project Memory

## Purpose

This repository is a long-term personal running coach workspace for Abel.
The system must act as an intelligent coach, planner and reviewer.

## Athlete Summary

- Name: Abel
- Birth date: 2004-06-17
- Height: 174 cm
- Weight: 64.2 kg
- City: Ordes
- Running experience: about 6 months at project setup time
- Availability: 7 days per week, 7-10 hours per week
- Preferred quality days: Tuesday and Thursday
- Preferred long run day: Sunday
- Strength: 1 session per week
- Constraint: work schedule 07:30-15:00

## Health Constraints

- Past injury: tibial periostitis
- Current issue: left shin periosteum discomfort
- Planning must prioritize consistency and shin tolerance over aggressive progression.

## Race Model

- Races are classified as `S`, `A`, `B`, `C`, `D`.
- Only one `S` race may exist.
- Every race file must include approximate `elevation_gain_m`.
- The current `S` race is `races/2027/XXIV_padron_10k.yaml`.

## Current Goal Race

- Race: XXIV Padron 10k
- Date: 2027-02-06
- Priority: S
- Distance: 10k
- Elevation gain: 20 m
- Declared goal: 35:00 at 3:30/km
- Important: treat this as aspirational and evidence-gated; do not prescribe 3:30/km work until checkpoints support it.

## Training References

- Easy pace: 6:00-7:30/km depending on heart rate
- HR zones:
  - Z0: <130
  - Z1: 131-140
  - Z2: 141-155
  - Z3: 156-170
  - Z4: 171-185
  - Z5: >185
- 5k reference pace: 4:15/km
- 10k evidence band: 4:22-4:26/km
- Garmin race reference: 2026-02-07 Padron, 10.08 km around 4:26/km, avg HR 186 bpm
- Short interval ability: 4 x 1000 m around 3:56-4:01/km on 2026-04-16, high cost and not current 10k pace
- Threshold pace: unknown at project setup

## Weekly Operating Model

- The operational week always runs from Monday to Sunday.
- `planning/weeks/semana_actual.md` is the active weekly plan.
- Every time `planning/weeks/semana_actual.md` is generated or updated, it must be converted to PDF and sent by Telegram.
- After each workout, Abel may provide the completed session manually or Garmin data may be imported.
- Each completed workout must be:
  - recorded
  - reviewed
  - scored numerically
  - classified with traffic light
  - summarized with a written coaching review
- If execution, fatigue or pain justify it, replanify the rest of the current week.
- Every Sunday, generate only the next week.

## Main Files

- Athlete profile: `athlete/profile.yaml`
- Health: `athlete/health.yaml`
- Zones: `athlete/zones.yaml`
- Shoes: `athlete/shoes.yaml`
- Preferences: `athlete/preferences.yaml`
- Races: `races/<year>/*.yaml`
- Master plan: `planning/master_plan.md`
- Blocks: `planning/blocks/*.md`
- Active week: `planning/weeks/semana_actual.md`
- Completed activity template: `training/completed/activities/activity_template.yaml`
- Review template: `training/completed/reviews/review_template.md`
- Local agent memory: `.agents/`
- Telegram PDF sender: `scripts/notifications/semana_pdf_telegram.py`
- Telegram OpenCode bot: `scripts/telegram/opencode_bot.py`
- Telegram OpenCode bridge: `scripts/telegram/opencode_bridge.py`
- Coach sync: `scripts/garmin/coach_sync.py`
- Coach engine: `scripts/garmin/coach_engine.py`
- Status dashboard: `athlete/status_dashboard.md`
- Coach decision: `planning/coach_decision.md`
- Coach decision JSON: `planning/coach_decision.json`
- Garmin athlete snapshot: `training/completed/imports/garmin/profile/athlete_profile_snapshot.json`
- 35:00 gates: `planning/goal_gates.yaml`
- 35:00 gates explainer: `planning/goal_gates.md`
- Shin tracker: `athlete/shin_tracker.yaml`
- Coaching playbook: `planning/coaching_playbook.md`
- Session selection matrix: `planning/session_selection_matrix.yaml`
- Workout evaluation rules: `planning/workout_evaluation_rules.md`
- Context automation policy: `planning/context_automation_policy.md`
- Athlete response profile: `athlete/response_profile.yaml`
- Workout library: `training/planned/workouts/library_run_templates.yaml`

## Garmin Integration

- Connector script: `scripts/garmin/sync_garmin.py`
- Local credentials: `garmin/local_credentials.yaml`
- Imports root: `training/completed/imports/garmin`
- Supported V1 actions:
  - import recent activities
  - import daily recovery metrics
  - upload and schedule planned workouts from YAML files
  - compare completed Garmin runs against the planned workout of the day and generate review artifacts

## Garmin Commands

Default automatic post-workout trigger:

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py
```

Manual Garmin operations and recovery paths:

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
python scripts/garmin/review_planned_session.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
python scripts/garmin/coach_engine.py --as-of YYYY-MM-DD --days 28
```

## Coach Automation Rules

- The default post-workout operating model is the automatic pipeline driven by `scripts/garmin/post_workout_refresh.py` and its persisted state.
- Treat `athlete/status_dashboard.md` as the main human-readable analysis output; the web dashboard integrates the decision layer there.
- Use `post_workout_refresh.py` as the default trigger for newly completed activities; use `coach_sync.py` only for manual recovery, troubleshooting or forced rebuilds.
- Use `coach_sync.py --skip-garmin` only when working manually from already imported local data.
- Read `athlete/status_dashboard.md` and `planning/coach_decision.md` before modifying the active week.
- Read `planning/coaching_playbook.md`, `planning/session_selection_matrix.yaml`, `planning/workout_evaluation_rules.md` and `athlete/response_profile.yaml` as default operational context before planning, replanning or creating workouts.
- Read `planning/context_automation_policy.md` to determine all mandatory supporting context files for the current task.
- When Garmin athlete snapshot data exists, use it through the synced local athlete files as active planning context.
- Treat `red` as reduce or replace quality, `yellow` as maintain without increasing load, and `green` as allow only small progression if the shin is quiet.
- Keep `planning/goal_gates.yaml` as the source of truth for whether `35:00` can influence training paces.
- `athlete/shin_tracker.yaml` can now be auto-promoted from subjective feedback; update it manually only when the automatic promotion is missing context or needs correction.

## Planning Principles

- Start from consistency, not fantasy pace.
- Protect the shin first.
- Use heart rate to control easy and long runs.
- Use pace mainly for quality work.
- Do not force threshold or race pace estimates without data.
- Recalibrate the long-term goal from checkpoints.
- Current limiter is aerobic durability and shin tolerance more than isolated speed.
- Prefer validating the automatic pipeline health instead of manually rerunning imports after Garmin-linked training.
- Remote Telegram access uses `opencode serve` plus `scripts/telegram/opencode_bot.py`; only commit or push when explicitly requested.
- Remote Telegram access defaults to model `openai/gpt-5.4` with OpenCode default reasoning; use `/model` in Telegram to override per chat.

## Web Portal Notes

- `planned-workouts` is the single future-planning area, with `week`, `list` and `calendar` views.
- `/week` is kept only as a redirect to `planned-workouts?view=week`.
- `dashboard` is the main analysis page and already includes the operative decision context.
- `/decision` is kept only as a redirect to `/dashboard`.

## Communication Rules For Future Sessions

- Be direct and practical.
- Preserve all existing athlete data.
- Do not delete historical records.
- When changing the week, explain why.
- When reviewing a workout, always state whether the week stays intact or changes.

## Long-Term Intent

This is a persistent coaching project, not a one-off plan.
Future sessions should build on the stored files and keep the repository as the source of truth.

## Preferred Future Entry Point

Future sessions should start by reading:

1. `AGENT.md`
2. `.agents/README.md`
3. `.agents/memory/project_snapshot.md`
4. `planning/context_automation_policy.md`
5. `planning/coaching_playbook.md`
6. `planning/session_selection_matrix.yaml`
7. `planning/workout_evaluation_rules.md`
8. `athlete/response_profile.yaml`
9. `athlete/status_dashboard.md` when it exists
10. `planning/coach_decision.md` when it exists

## Repository Skills

Operational skill notes live under `.agents/skills/`.

- `weekly_planning_cycle.md`: build or adjust the current week
- `workout_loading.md`: create and structure planned workouts
- `garmin_operations.md`: import, upload and review Garmin-linked sessions
- `coach_automation.md`: run coach sync/engine and interpret dashboard, decisions and gates
- `remote_opencode_telegram.md`: operate OpenCode remotely through Telegram
- `completed_workout_inspection.md`: inspect completed sessions in depth
