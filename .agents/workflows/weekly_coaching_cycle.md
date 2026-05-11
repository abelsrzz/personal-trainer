# Workflow: Weekly Coaching Cycle

The operational week always runs from Monday to Sunday.

## Daily Or Post-Workout

1. capture completed workout manually or from Garmin
2. if Garmin-linked, prefer the automatic pipeline `python scripts/garmin/post_workout_refresh.py` unless the user explicitly wants a manual rebuild path
3. if working offline, run `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin`
4. read `planning/coach_decision.md` and `athlete/status_dashboard.md`
5. read `planning/context_automation_policy.md` to load the mandatory review and replanning context
6. read `planning/workout_evaluation_rules.md` before deciding whether the completed session justifies progression, repetition, regression or replacement
7. decide whether to keep or replanify the current week
8. validate `athlete/shin_tracker.yaml` if the athlete reports periosteum pain and the automatic promotion lacks context

## Sunday Cycle

1. refresh local coach status with `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` only if the automatic pipeline is unavailable and no fresh dashboard exists
2. review the current week
3. archive the outgoing week when needed
4. read active block instructions
5. read `planning/context_automation_policy.md` and all files marked there as mandatory for weekly planning
6. read `planning/coach_decision.md`, `athlete/status_dashboard.md`, `planning/goal_gates.yaml`, `planning/coaching_playbook.md`, `planning/session_selection_matrix.yaml` and `athlete/response_profile.yaml`
7. consider recent execution, fatigue, shin status, shoes, zones, preferences, health and races through those policy files, not only ad hoc judgment
8. generate the next `planning/weeks/semana_actual.md`
9. generate `planning/weeks/generated/semana_actual.pdf` and send it by Telegram

## Cycle Lifecycle

- Use `python scripts/system/close_cycle.py` to snapshot and close the active cycle before replacing the master plan for a new objective.
- Use `python scripts/system/start_cycle.py` to define the next active cycle manifest.
- Treat `planning/cycles/active.yaml` as the current cycle pointer while legacy active files remain in place.

## Replanning Triggers

- poor workout execution with meaningful cause
- rising fatigue
- shin pain or injury risk
- `planning/coach_decision.md` status is `red`
- `planning/coach_decision.md` status is `yellow` and the next week would increase load
- schedule disruption
- relevant new race or event

## Coach Decision Rules

- `green`: keep the plan and allow only small progression if the shin is quiet.
- `yellow`: keep structure but do not increase volume or intensity.
- `red`: reduce load, replace quality with easy running or rest, and protect the shin.

## Garmin Athlete State Sync

- `python scripts/garmin/post_workout_refresh.py` is now the default post-workout trigger and should be assumed active when automation is healthy.
- Garmin-synced resting HR, max HR, VO2max and gear should flow into local athlete files before planning whenever available.
- Local athlete files remain the source of truth used by planning, but Garmin is the preferred upstream source for those fields.

## Dynamic Capabilities

- Before using dynamic athlete or planning data, prefer the capability registry in `system/capabilities/registry.yaml` over direct file reads.
- If a capability exists, refresh it according to its freshness policy before planning or replanning.
- If Garmin can provide the metric, try Garmin first and only fall back to the local cache with an explicit stale warning.
