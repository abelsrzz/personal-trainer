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

## Default Entry Points For Future Sessions

1. Read `../AGENT.md`
2. Read `.agents/memory/project_snapshot.md`
3. Read `.agents/workflows/weekly_coaching_cycle.md`
4. Read the relevant agent or skill file for the current task
