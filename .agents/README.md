# Local Agents

`.agents/` is the local operational memory for this long-term running coach project.

It exists so future AI sessions can recover the intent, workflows and roles of the repository without depending on prior chat context.

## Structure

- `agents/`: role definitions for recurring agent behaviors.
- `skills/`: reusable instructions for planning, review and Garmin operations.
- `workflows/`: end-to-end execution flows.
- `memory/`: persistent project context snapshots.

## Source Of Truth

The repository data files remain the source of truth.
`.agents/` explains how to operate on them.

Key files:

- `../AGENT.md`
- `../athlete/`
- `../races/`
- `../planning/`
- `../training/`
- `../garmin/`

Coach automation files:

- `../scripts/garmin/coach_sync.py`: preferred one-command Garmin sync, review and dashboard flow.
- `../scripts/garmin/coach_engine.py`: local analysis engine for dashboard, load decision, goal gates and performance estimate.
- `../athlete/status_dashboard.md`: latest generated athlete status.
- `../planning/coach_decision.md`: latest coaching decision for load adjustment.
- `../planning/coach_decision.json`: structured decision data for automation.
- `../planning/goal_gates.yaml`: measurable gates for whether `35:00` can guide training.
- `../athlete/shin_tracker.yaml`: structured periosteum symptom log.
- `../athlete/supplements.yaml`: available supplementation catalog for races and hard sessions.
- `../planning/fueling_operational.md`: latest practical hydration, carb-load and supplementation guidance.
- `../planning/fueling_operational.json`: structured fueling plan for automation.
- `../planning/coaching_playbook.md`: default training prescription policy.
- `../planning/session_selection_matrix.yaml`: default workout-family selection rules.
- `../planning/workout_evaluation_rules.md`: post-session progression and regression rules.
- `../planning/context_automation_policy.md`: mandatory-vs-conditional context map for every coaching workflow.
- `../athlete/response_profile.yaml`: athlete-specific response and tolerance profile.
- `../system/state/athlete_state.json`: consolidated machine-readable athlete state with hybrid load, progression, pace bands and replanning hints.
- `../scripts/system/load_progression.py`: progression logic around absorbed week and default `+5%` post-return growth.
- `../scripts/system/training_paces.py`: current evidence-based pace bands by family.
- `../scripts/system/week_replanner.py`: structured replan hints after risk, pain or fatigue events.
- `../scripts/system/planning_validator.py`: validation layer for prepared/active weeks and dated workouts.
- `../system/capabilities/registry.yaml`: freshness and consumer registry for capability-backed reads.
- `../scripts/telegram/opencode_bot.py`: Telegram remote interface to OpenCode.
- `../scripts/telegram/opencode_bridge.py`: subprocess bridge to `opencode run --attach`.
- `../.agents/workflows/remote_opencode_telegram.md`: remote operation workflow.

## Default Entry Points For Future Sessions

1. Read `../AGENT.md`
2. Read `.agents/memory/project_snapshot.md`
3. Read `.agents/workflows/weekly_coaching_cycle.md`
4. Read `../planning/context_automation_policy.md`
5. Read `../planning/coaching_playbook.md`, `../planning/session_selection_matrix.yaml`, `../planning/workout_evaluation_rules.md` and `../athlete/response_profile.yaml`
6. Read `../athlete/status_dashboard.md` and `../planning/coach_decision.md` when they exist
7. Read `../system/state/athlete_state.json` when it exists
8. Read `../athlete/supplements.yaml` and `../planning/fueling_operational.md` when race execution or hard-session fueling is relevant
9. Read the relevant agent or skill file for the current task

## Default Automation Rule

- After Garmin-linked training, prefer the automatic pipeline driven by `python scripts/garmin/post_workout_refresh.py` or its `systemd` timer instead of manual post-workout commands.
- Use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` only for manual local rebuilds or troubleshooting when the automatic pipeline is not the right tool.
- Use `planning/coach_decision.md` as the first load-management signal before changing the active week.
- Use the playbook, selection matrix, evaluation rules and response profile as mandatory default context for planning and replanning.
- Use `system/state/athlete_state.json` as the fastest consolidated read for hybrid load, impact return, pace bands, permissions and replanning hints, then drill into source files only when needed.
- Prefer capability-backed state over ad hoc file scraping when a capability already exists.
- Use `planning/context_automation_policy.md` to decide which athlete, race, block, zone, shoe and goal files are mandatory for the current task.
- Include fueling context when preparing race execution, hydration strategy or supplementation around hard training.
- In the web portal, treat `web_v2` as the primary product surface.
- Treat `web` v1 as deprecated/legacy and use it only when a specific feature has not yet been ported or when cross-checking old behavior.
- For remote Telegram operation, run `opencode serve` locally and then `python scripts/telegram/opencode_bot.py`.
- Remote Telegram operation defaults to `openai/gpt-5.4` with default reasoning; `/model` changes the per-chat model override.
