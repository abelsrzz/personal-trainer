# Skill: Garmin Sync

## Purpose

Use Garmin as a data source and delivery channel for planned workouts.

## Current Capabilities

- import recent activities
- import daily readiness and recovery metrics
- upload and schedule planned running workouts

## Current Limitations

- Garmin login may rate limit temporarily
- workout payloads may need refinement to preserve exact targets in Garmin UI
- sync is local and credential-based

## Repository Interfaces

- credentials: `garmin/local_credentials.yaml`
- script: `scripts/garmin/sync_garmin.py`
- imports: `training/completed/imports/garmin/`
- planned workouts: `training/planned/workouts/`
