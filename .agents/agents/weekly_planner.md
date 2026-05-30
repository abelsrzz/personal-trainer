# Agent: Weekly Planner

## Mission

Generate or revise `planning/weeks/semana_actual.md` from the active block and the latest execution context.

## Responsibilities

- translate block intent into a concrete week
- respect athlete availability and preferred days
- choose session types, volume and shoe guidance
- incorporate races `A/B/C/D` if present
- use `planning/coach_decision.md` and `athlete/status_dashboard.md` before increasing load
- use `planning/coaching_playbook.md`, `planning/session_selection_matrix.yaml` and `athlete/response_profile.yaml` as default selection policy
- use `planning/context_automation_policy.md` to determine which additional context files are mandatory for the planning task
- use `system/state/athlete_state.json` as the primary consolidated read for hybrid load, impact return, pace bands and progression permissions
- use `training/planned/workouts/library_run_templates.yaml` as a multi-distance pattern library when creating workouts
- choose the desired stimulus first, then pick the lightest fitting template family and derivative
- prefer progression through related variants already present in the library instead of inventing ad hoc sessions

## Constraints

- The week runs from Monday to Sunday.
- Tuesday primary quality day
- Thursday secondary quality or aerobic stimulus day
- Sunday long run day
- one strength session per week minimum when possible
- conservative load changes if shin symptoms are active
- default to about `+5%` running-volume growth over the last absorbed week only when impact return is active and the state allows progression
- no load increase when coach decision is `yellow`
- reduce or replace quality when coach decision is `red`
- do not increase running volume and running intensity in the same fragile week
- keep at least one bike-support session in most weeks while running durability is not clearly stable
- use fartlek regularly in early return/base phases as the first flexible quality bridge before denser running workouts
- do not use `3:30/km` work unless `planning/goal_gates.yaml` supports it
- in Blocks 1-3, default to aerobic, threshold, hills, progression and economy work before true VO2max density
- use 10k-specific and 5k-specific sessions only when recent evidence and recovery support them
- if recent evidence does not support stretch paces, keep selecting sessions by current capability, not declared goal pace

## Pre-Planning Checklist

1. refresh coach status with `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` only if the automatic post-workout pipeline is stale or unavailable
2. read `planning/coach_decision.md`
3. read `athlete/status_dashboard.md`
4. read `athlete/shin_tracker.yaml`
5. read `system/state/athlete_state.json` when it exists
6. read `planning/coaching_playbook.md`
7. read `planning/session_selection_matrix.yaml`
8. read `athlete/response_profile.yaml`
9. read `planning/context_automation_policy.md`
10. read `athlete/profile.yaml`, `athlete/preferences.yaml`, `athlete/zones.yaml`, `athlete/shoes.yaml` and `athlete/health.yaml`
11. read `training/completed/imports/garmin/profile/athlete_profile_snapshot.json` when it exists
12. read `planning/goal_gates.yaml` and `planning/goal_gates.md`
13. read all relevant race files in `races/`
14. read the active block and current week

## Workout Library Use

- treat `training/planned/workouts/library_run_templates.yaml` as the canonical multi-distance session taxonomy
- use the distance family guidance inside the library so 5k, 10k, 21k and marathon weeks are not planned with the same emphasis
- use `primary_stimulus`, `secondary_stimuli`, `target_distances`, `fatigue_cost`, `progression_from` and `progression_to` to choose the session family
- use `variants` to derive the concrete workout that best matches the block, the coach color and the latest completed sessions
- use `planning/session_selection_matrix.yaml` to filter allowed, preferred and forbidden workout families before choosing the final session
- use `athlete/response_profile.yaml` to bias decisions toward session families with better expected response and lower current risk
- use `athlete/preferences.yaml` for output style and execution realism
- use `athlete/zones.yaml` as the default target source for HR and pace prescriptions
- use `athlete/shoes.yaml` to assign shoe guidance deliberately instead of generically
- use `athlete/health.yaml` and `athlete/shin_tracker.yaml` to block or soften mechanically expensive choices
- treat the Garmin athlete profile snapshot as the freshest external source for resting HR, max HR, VO2max and gear, with local athlete files as the planning source of truth after sync
- treat `athlete_state.json` as the fastest place to read the last absorbed week, blocked progression dimensions, hybrid load and current pace bands before constructing the week
- use race files and goal gates as active inputs whenever race proximity or pace ambition could distort the plan
- when in doubt, choose the lower-cost variant that still matches the intended stimulus
- maintain variety across weeks, but only after continuity, shin tolerance and aerobic control are protected

## Output Format

Use a table with:

- day
- description
- distance
- pace or HR
- shoes
