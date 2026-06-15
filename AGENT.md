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
  - Z0: <132
  - Z1: 132-145
  - Z2: 145-160
  - Z3: 160-176
  - Z4: 176-191
  - Z5: >191
- 5k reference pace: 4:15/km
- 10k evidence band: 4:22-4:26/km
- Garmin race reference: 2026-02-07 Padron, 10.08 km around 4:26/km, avg HR 186 bpm
- Short interval ability: 4 x 1000 m around 3:56-4:01/km on 2026-04-16, high cost and not current 10k pace
- Threshold pace: unknown at project setup

## Weekly Operating Model

- The operational week always runs from Monday to Sunday.
- `planning/weeks/semana_actual.md` is the active weekly plan.
- `planning/weeks/prepared/<year>/` stores prepared next weeks before activation so the active week is not overwritten prematurely.
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
- The safe default is to prepare the next week first and activate it explicitly when appropriate.

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
- Supplements catalog: `athlete/supplements.yaml`
- Fueling plan JSON: `planning/fueling_operational.json`
- Fueling plan MD: `planning/fueling_operational.md`
- Fueling engine: `scripts/system/fueling_engine.py`
- Coaching playbook: `planning/coaching_playbook.md`
- Session selection matrix: `planning/session_selection_matrix.yaml`
- Workout evaluation rules: `planning/workout_evaluation_rules.md`
- Context automation policy: `planning/context_automation_policy.md`
- Athlete response profile: `athlete/response_profile.yaml`
- Workout library: `training/planned/workouts/library_run_templates.yaml`
- Weekly planning pipeline: `scripts/system/weekly_planning_pipeline.py`
- Weekly planning state: `system/state/weekly_planning_state.json`
- Consolidated athlete state: `system/state/athlete_state.json`
- Load progression engine: `scripts/system/load_progression.py`
- Training paces engine: `scripts/system/training_paces.py`
- Week replanner: `scripts/system/week_replanner.py`
- Planning validator: `scripts/system/planning_validator.py`
- Capability registry: `system/capabilities/registry.yaml`

## Garmin Integration

- Connector script: `scripts/garmin/sync_garmin.py`
- Local credentials: `garmin/local_credentials.yaml`
- Imports root: `training/completed/imports/garmin`
- For strength workouts, create one planned step per exercise. Do not collapse the whole routine into a single timed block with a comma-separated description.
- Strength workout steps should use `exercise_name` so Garmin can show the selected exercise on the watch. If Garmin lacks the exact rehab movement, use the closest Garmin exercise name and keep the exact prescription in `description`.
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
- Weekly planning now has a separate pipeline in `scripts/system/weekly_planning_pipeline.py` with a safe prepare/activate flow.
- The planning stack now includes explicit support engines for load progression, training paces, replanning and prepared-week validation.
- `system/state/athlete_state.json` is now the main consolidated machine-readable state for hybrid load, impact return, training paces, permissions and replanning hints.
- Before planning or replanning, prefer reading `system/state/athlete_state.json` and capability-backed outputs instead of re-deriving the same signals ad hoc from scattered files.
- Treat `athlete/status_dashboard.md` as the main human-readable analysis output; the web dashboard integrates the decision layer there.
- Use `post_workout_refresh.py` as the default trigger for newly completed activities; use `coach_sync.py` only for manual recovery, troubleshooting or forced rebuilds.
- Use `coach_sync.py --skip-garmin` only when working manually from already imported local data.
- Read `athlete/status_dashboard.md` and `planning/coach_decision.md` before modifying the active week.
- Read `planning/coaching_playbook.md`, `planning/session_selection_matrix.yaml`, `planning/workout_evaluation_rules.md` and `athlete/response_profile.yaml` as default operational context before planning, replanning or creating workouts.
- Use the load progression semantics already codified in state: last absorbed week, default `~+5%` running progression after impact return, blocked dimensions and bike-support requirement.
- Use the training paces semantics already codified in state: fartlek, tempo, 10k-specific and VO2 bands must progress from recent evidence, not from static legacy paces.
- Use the replanning semantics already codified in state when deciding whether to hold, reduce, replace quality or move intensity to bike.
- Treat hybrid planning as first-class: bike is not only rehabilitation filler, it is also an allowed support surface for aerobic, tempo and VO2 work when tibial cost is the limiter.
- Read `planning/context_automation_policy.md` to determine all mandatory supporting context files for the current task.
- Read `athlete/supplements.yaml` and `planning/fueling_operational.md` when planning races, hard workouts or any pre/during/post fueling guidance.
- When giving powder supplement instructions, express them as target grams first and include the approximate `ml` equivalent using the conversion reference in `athlete/supplements.yaml`.
- When Garmin athlete snapshot data exists, use it through the synced local athlete files as active planning context.
- Treat `red` as reduce or replace quality, `yellow` as maintain without increasing load, and `green` as allow only small progression if the shin is quiet.
- Keep `planning/goal_gates.yaml` as the source of truth for whether `35:00` can influence training paces.
- Keep `planning/goal_gates.yaml` as the source of truth for both the final `35:00` gates and the intermediate block checkpoints toward that target.
- `athlete/shin_tracker.yaml` can now be auto-promoted from subjective feedback; update it manually only when the automatic promotion is missing context or needs correction.
- When a next week is prepared, do not overwrite it silently; report that it already exists unless the user explicitly forces regeneration.
- After weekly planning changes create or update dated workouts, attempt Garmin scheduling automatically for changed files and record the result.
- When changing any future session, update all operative layers, not just the weekly markdown: `planning/weeks/semana_actual.md` or prepared week, the dated file in `training/planned/workouts/`, and Garmin scheduling when that dated workout exists or should exist.
- For user requests such as "change tomorrow session" or "replace this workout", assume the expected done state includes: weekly plan updated, dated workout updated, and Garmin/calendar sync attempted unless the user explicitly says local-only.
- Automatic reality today is: post-workout refresh, weekly prepare/activate pipeline, PDF generation + Telegram send on activation, Garmin scheduling retries and web-triggered weekly planning.
- Desired-but-not-implicit behavior should not be assumed; if a timer or bot is not configured, the user-facing buttons and scripts remain the explicit trigger.

## Planning Principles

- Start from consistency, not fantasy pace.
- Protect the shin first.
- Use heart rate to control easy and long runs.
- Use pace mainly for quality work.
- Do not force threshold or race pace estimates without data.
- Recalibrate the long-term goal from checkpoints.
- Current limiter is aerobic durability and shin tolerance more than isolated speed.
- Race and hard-workout execution should include practical fueling/hydration guidance when those artifacts exist.
- Prefer validating the automatic pipeline health instead of manually rerunning imports after Garmin-linked training.
- Remote Telegram access uses `opencode serve` plus `scripts/telegram/opencode_bot.py`; only commit or push when explicitly requested.
- Remote Telegram access defaults to model `openai/gpt-5.4` with OpenCode default reasoning; use `/model` in Telegram to override per chat.
- When `openai/gpt-5.4` is unavailable (quota, credits or provider error), the system automatically falls back to the Gemini free API with a full agentic loop (read/write files, execute commands, Garmin sync — full feature parity with OpenCode). Model cascade: `gemini-2.5-pro` → `gemini-2.5-flash` → `gemini-2.0-flash`. A Telegram warning is sent each time the fallback activates. Fallback config: `telegram/bot_config.yaml` under `opencode_remote.gemini_fallback`; bridge module: `scripts/telegram/gemini_fallback.py`.

## Web Portal Notes

- `planned-workouts` is the single future-planning area, with `week`, `list` and `calendar` views.
- `web_v2` is the primary web surface going forward.
- `web` v1 is now legacy/deprecated and should only be used for compatibility, troubleshooting or cross-checking old behavior.
- `/week` is kept only as a redirect to `planned-workouts?view=week`.
- `dashboard` is the main analysis page and already includes the operative decision context plus progress.
- `/decision` is kept only as a redirect to `/dashboard`.
- `/progress` is kept only as a redirect to `/dashboard`.
- The web portal is operational, not read-only anymore: it includes daily check-in, planned-session actions, replanning actions, post-workout feedback, weekly planning triggers and web chat.
- In the planning view, the weekly automation can prepare the next week without overwriting the active one and can later activate the prepared week.
- `chat` is a first-level operative surface; `risk`, `fueling` and `master-plan` are secondary/supporting views.

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
11. `system/state/athlete_state.json` when it exists

## Repository Skills

Operational skill notes live under `.agents/skills/`.

- `weekly_planning_cycle.md`: build or adjust the current week
- `workout_loading.md`: create and structure planned workouts
- `garmin_operations.md`: import, upload and review Garmin-linked sessions
- `coach_automation.md`: run coach sync/engine and interpret dashboard, decisions and gates
- `remote_opencode_telegram.md`: operate OpenCode remotely through Telegram
- `completed_workout_inspection.md`: inspect completed sessions in depth
