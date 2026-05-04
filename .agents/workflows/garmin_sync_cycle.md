# Workflow: Garmin Sync Cycle

## Import Flow

1. import recent activities
2. import daily metrics
3. analyze imported data when planning or reviewing

## Upload Flow

1. create workout YAML in `training/planned/workouts/`
2. upload and schedule with `scripts/garmin/sync_garmin.py`
3. verify local upload record exists
4. verify workout appears in Garmin calendar when necessary

## Failure Handling

- if Garmin rate limits login, wait and retry later
- if upload works but schedule fails, keep the upload record and retry scheduling
- if target formatting is degraded by Garmin, keep the workout but note the limitation
