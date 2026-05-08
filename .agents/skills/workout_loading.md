# Skill: Workout Loading

## Purpose

Create, update, normalize and schedule planned workouts with the repository as source of truth.

## Use Cases

- create a new planned workout YAML
- adjust an already planned session
- convert a coaching idea into structured workout steps
- prepare a workout for Garmin upload

## Inputs To Read First

- `planning/weeks/semana_actual.md`
- relevant block in `planning/blocks/`
- recent reviews in `training/completed/reviews/`
- `planning/coach_decision.md`
- `athlete/status_dashboard.md`
- `planning/coaching_playbook.md`
- `planning/session_selection_matrix.yaml`
- `athlete/response_profile.yaml`
- `planning/workout_evaluation_rules.md`
- `planning/context_automation_policy.md`
- `athlete/preferences.yaml`
- `athlete/zones.yaml`
- `athlete/shoes.yaml`
- `athlete/health.yaml`
- `training/completed/imports/garmin/profile/athlete_profile_snapshot.json`
- `planning/goal_gates.yaml`
- `training/planned/workouts/library_run_templates.yaml`
- reference workouts in `training/planned/workouts/`

## Output Rules

- create or update `training/planned/workouts/YYYY-MM-DD_<slug>.yaml`
- keep the workout description aligned with the coaching intent
- use heart rate targets for easy and long runs
- use pace targets mainly for quality work
- keep structure minimal and explicit
- do not create workouts that contradict a `red` or `yellow` coach decision
- use template library patterns when they fit, but create dated workout YAML as the upload source of truth
- use the library taxonomy and metadata to preserve the intended stimulus when converting a pattern into a dated workout
- if deriving a new session from the library, stay inside the same progression family unless there is a clear coaching reason to change stimulus
- respect the target distance family in the library so 5k, 10k, 21k and marathon workouts keep their own planning logic
- follow `planning/coaching_playbook.md` as the default prescription policy
- use `planning/session_selection_matrix.yaml` to rule out incompatible families before building the workout
- use `athlete/response_profile.yaml` to prefer session families that better fit the athlete's current response pattern
- use `planning/workout_evaluation_rules.md` when modifying a future workout after a completed-session review
- use `planning/context_automation_policy.md` to decide which contextual files are mandatory for the current workout task
- use `athlete/preferences.yaml` to preserve plan style and detail level
- use `athlete/zones.yaml` as the default source for pace and heart-rate targets unless fresher evidence overrides it
- use `athlete/shoes.yaml` to assign session-appropriate shoes conservatively when plated or aggressive options add risk
- use `athlete/health.yaml` and `planning/goal_gates.yaml` to avoid workouts that are unrealistic or mechanically expensive for the current state
- if the Garmin athlete profile snapshot exists, assume `athlete/profile.yaml`, `athlete/zones.yaml`, `athlete/health.yaml` and `athlete/shoes.yaml` may already reflect fresher synced data and use them accordingly

## Validation Checklist

1. date matches the active week
2. sport is correct
3. estimated duration is coherent
4. steps are ordered and complete
5. targets are realistic for the athlete status
6. if requested, upload with Garmin and keep the upload trace
7. the chosen workout family matches the intended physiological stimulus and target race context
8. the chosen family is compatible with the session selection matrix and the athlete response profile
9. targets, shoes and constraints are coherent with zones, preferences, health and goal-gate context

## Related Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
```
