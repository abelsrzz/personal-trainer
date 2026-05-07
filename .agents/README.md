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

## Default Entry Points For Future Sessions

1. Read `../AGENT.md`
2. Read `.agents/memory/project_snapshot.md`
3. Read `.agents/workflows/weekly_coaching_cycle.md`
4. Read `../athlete/status_dashboard.md` and `../planning/coach_decision.md` when they exist
5. Read the relevant agent or skill file for the current task

## Default Automation Rule

- After Garmin-linked training, prefer `python scripts/garmin/coach_sync.py --date YYYY-MM-DD` over running separate import/review/dashboard commands manually.
- If Garmin should not be contacted, use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` to refresh decisions from local data.
- Use `planning/coach_decision.md` as the first load-management signal before changing the active week.
