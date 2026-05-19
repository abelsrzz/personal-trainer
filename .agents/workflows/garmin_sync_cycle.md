# Workflow: Garmin Sync Cycle

## Import Flow

1. prefer `python scripts/garmin/post_workout_refresh.py` for normal post-workout operation
2. import recent activities with `sync_garmin.py` only when low-level import control is needed
3. import daily metrics with `sync_garmin.py` only when low-level import control is needed
4. analyze imported data through `athlete/status_dashboard.md` and `planning/coach_decision.md`

## Offline Analysis Flow

1. use `python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin` only for manual local rebuilds when Garmin should not be contacted
2. confirm `athlete/status_dashboard.md`, `planning/coach_decision.md` and `planning/coach_decision.json` were refreshed
3. use the generated decision before changing weekly planning

## Upload Flow

1. create workout YAML in `training/planned/workouts/`
2. if an existing planned workout YAML is edited, treat that edit exactly like a new upload
3. upload and schedule with `scripts/garmin/sync_garmin.py`
4. do not consider the change finished until Garmin has the updated version
5. verify local upload record exists and matches the latest workout name/date/sport
6. verify workout appears in Garmin calendar when necessary

## Failure Handling

- if Garmin rate limits login, wait and retry later
- if upload works but schedule fails, keep the upload record and retry scheduling
- if target formatting is degraded by Garmin, keep the workout but note the limitation
- if daily metrics import fails but activities import succeeds, keep going and use local activity/review data
