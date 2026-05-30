# Skill: Garmin Sync

## Purpose

Use Garmin as a data source and delivery channel for planned workouts.

## Current Capabilities

- import recent activities
- import daily readiness and recovery metrics
- import athlete profile, resting HR, max HR, VO2max and gear snapshot
- upload and schedule planned running workouts
- run coach sync to import, review and generate the analysis outputs used by planning

## Current Limitations

- Garmin login may rate limit temporarily
- workout payloads may need refinement to preserve exact targets in Garmin UI
- sync is local and credential-based

## Repository Interfaces

- credentials: `garmin/local_credentials.yaml`
- script: `scripts/garmin/sync_garmin.py`
- preferred coach command: `scripts/garmin/coach_sync.py`
- analysis engine: `scripts/garmin/coach_engine.py`
- capability engine: `scripts/system/capability_engine.py`
- capability registry: `system/capabilities/registry.yaml`
- imports: `training/completed/imports/garmin/`
- athlete snapshot: `training/completed/imports/garmin/profile/athlete_profile_snapshot.json`
- planned workouts: `training/planned/workouts/`
- dashboard: `athlete/status_dashboard.md`
- decision: `planning/coach_decision.md`
- data quality report: `planning/data_quality_report.md`

## Preferred Post-Workout Flow

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py
```

Use `--skip-garmin` to refresh analysis outputs from local files without contacting Garmin.

When Garmin is contacted through `coach_sync.py`, it should also attempt to refresh the local athlete profile state used by planning.

When a registered capability depends on Garmin, prefer satisfying it through the capability engine before reading the local cache directly.

The system should also review `planning/data_quality_report.md` to discover newly available Garmin metrics and prioritize automation improvements.
