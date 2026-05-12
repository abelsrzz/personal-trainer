# Context Automation Policy

## Purpose

Define which repository context files are mandatory for each coaching task, which are optional, and which are no longer part of active operational behavior.

This file exists to prevent future sessions from relying on partial memory or ad hoc context selection.

## Status Categories

### Mandatory

Files that must be read by default for the relevant workflow.

### Conditional

Files that must be read when the task type or current state makes them relevant.

### Passive Reference

Files that remain useful repository context but should not be treated as mandatory for most day-to-day decisions.

### Obsolete

Files that should be removed or ignored because they no longer match the operating model.

## Current Classification

### Mandatory Global Context

- `AGENT.md`
- `.agents/README.md`
- `.agents/memory/project_snapshot.md`
- `.agents/workflows/weekly_coaching_cycle.md`
- `planning/master_plan.md`
- `planning/coaching_playbook.md`
- `planning/workout_knowledge.yaml`
- `planning/workout_template_knowledge_map.yaml`
- `planning/session_selection_matrix.yaml`
- `planning/workout_evaluation_rules.md`
- `athlete/response_profile.yaml`
- `athlete/status_dashboard.md` when it exists
- `planning/coach_decision.md` when it exists
- `system/state/athlete_state.json` when it exists
- `athlete/shin_tracker.yaml`
- `athlete/supplements.yaml`
- `planning/fueling_operational.md` when it exists
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json` when it exists

### Mandatory For Weekly Planning

- `planning/weeks/semana_actual.md`
- relevant file in `planning/blocks/`
- `athlete/profile.yaml`
- `athlete/preferences.yaml`
- `athlete/zones.yaml`
- `athlete/shoes.yaml`
- `athlete/health.yaml`
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json` when it exists
- `system/state/athlete_state.json` when it exists
- `planning/goal_gates.yaml`
- `planning/goal_gates.md`
- `planning/workout_knowledge.yaml`
- `planning/workout_template_knowledge_map.yaml`
- `training/planned/workouts/library_run_templates.yaml`
- all relevant files in `races/<year>/`
- `athlete/supplements.yaml`
- `planning/fueling_operational.md` when it exists
- recent files in `training/completed/reviews/`

### Mandatory For Workout Creation Or Update

- `planning/weeks/semana_actual.md`
- relevant file in `planning/blocks/`
- `athlete/preferences.yaml`
- `athlete/zones.yaml`
- `athlete/shoes.yaml`
- `athlete/health.yaml`
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json` when it exists
- `planning/goal_gates.yaml`
- `planning/workout_knowledge.yaml`
- `planning/workout_template_knowledge_map.yaml`
- `training/planned/workouts/library_run_templates.yaml`
- `athlete/supplements.yaml`
- `planning/fueling_operational.md` when it exists
- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `athlete/response_profile.yaml`
- relevant recent reviews in `training/completed/reviews/`

### Mandatory For Completed Workout Review And Replanning

- `planning/workout_evaluation_rules.md`
- `planning/coaching_playbook.md`
- `planning/session_selection_matrix.yaml`
- `planning/workout_knowledge.yaml`
- `planning/workout_template_knowledge_map.yaml`
- `athlete/response_profile.yaml`
- `athlete/zones.yaml`
- `athlete/health.yaml`
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json` when it exists
- `athlete/shin_tracker.yaml`
- `planning/coach_decision.md`
- `athlete/status_dashboard.md`
- `system/state/athlete_state.json` when it exists
- planned workout file for the reviewed date when it exists
- recent completed review files for comparison

### Conditional Context

- `athlete/profile.yaml`: mandatory when availability, age, time budget or weekly structure matter.
- `athlete/health.yaml`: mandatory whenever pain, fatigue, recovery, shoe aggressiveness or volume progression are relevant.
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json`: mandatory whenever recently synced Garmin profile data exists and athlete profile, resting HR, max HR, VO2max or gear could affect planning.
- `athlete/shoes.yaml`: mandatory whenever a weekly plan or dated workout includes shoe guidance.
- `planning/goal_gates.md`: mandatory when discussing stretch-goal realism or target pace decisions.
- `races/<year>/`: mandatory when planning a week that is inside the race horizon or when reprioritizing the cycle.
- `athlete/supplements.yaml`: mandatory whenever a race or hard session needs pre/during/post fueling guidance.
- `planning/fueling_operational.md`: mandatory whenever race execution, hydration or supplementation are part of the task.

### Passive Reference

- `training/completed/activities/activity_template.yaml`
- `training/completed/reviews/review_template.md`
- `training/planned/workouts/workout_template.yaml`

These remain useful scaffolding files, but they should not drive coaching decisions.

### Obsolete

- none confirmed at this time

No current planning or athlete-context file is clear garbage. Existing overlap is acceptable because the files serve different roles: policy, state, athlete profile, weekly plan, review loop and workout library.

## Operational Rules

- If a file is classified as mandatory for the task, future sessions must read it by default before deciding.
- If a file is only passive reference, it should not displace more important decision context.
- Delete files only when their content is truly dead, duplicated without role separation, or contradictory to the current operating model.
