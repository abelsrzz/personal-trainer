# Running Coach Project Memory

## Purpose

This repository is a long-term personal running coach workspace for Abel.
The system must act as an intelligent coach, planner and reviewer.

## Athlete Summary

- Name: Abel
- Birth date: 2004-06-17
- Height: 174 cm
- Weight: 64.2 kg
- City: Ordes
- Running experience: about 6 months at project setup time
- Availability: 7 days per week, 7-10 hours per week
- Preferred quality days: Tuesday and Thursday
- Preferred long run day: Sunday
- Strength: 1 session per week
- Constraint: work schedule 07:30-15:00

## Health Constraints

- Past injury: tibial periostitis
- Current issue: left shin periosteum discomfort
- Planning must prioritize consistency and shin tolerance over aggressive progression.

## Race Model

- Races are classified as `S`, `A`, `B`, `C`, `D`.
- Only one `S` race may exist.
- Every race file must include approximate `elevation_gain_m`.
- The current `S` race is `races/2027/XXIV_padron_10k.yaml`.

## Current Goal Race

- Race: XXIV Padron 10k
- Date: 2027-02-06
- Priority: S
- Distance: 10k
- Elevation gain: 20 m
- Declared goal: 35:00 at 3:30/km
- Important: treat this as ambitious and recalibrate with evidence.

## Training References

- Easy pace: 6:00-7:30/km depending on heart rate
- HR zones:
  - Z0: <130
  - Z1: 131-140
  - Z2: 141-155
  - Z3: 156-170
  - Z4: 171-185
  - Z5: >185
- 5k reference pace: 4:15/km
- 10k reference pace: 4:22/km
- Threshold pace: unknown at project setup

## Weekly Operating Model

- The operational week always runs from Monday to Sunday.
- `planning/weeks/semana_actual.md` is the active weekly plan.
- Every time `planning/weeks/semana_actual.md` is generated or updated, it must be converted to PDF and sent by Telegram.
- After each workout, Abel may provide the completed session manually or Garmin data may be imported.
- Each completed workout must be:
  - recorded
  - reviewed
  - scored numerically
  - classified with traffic light
  - summarized with a written coaching review
- If execution, fatigue or pain justify it, replanify the rest of the current week.
- Every Sunday, generate only the next week.

## Main Files

- Athlete profile: `athlete/profile.yaml`
- Health: `athlete/health.yaml`
- Zones: `athlete/zones.yaml`
- Shoes: `athlete/shoes.yaml`
- Preferences: `athlete/preferences.yaml`
- Races: `races/<year>/*.yaml`
- Master plan: `planning/master_plan.md`
- Blocks: `planning/blocks/*.md`
- Active week: `planning/weeks/semana_actual.md`
- Completed activity template: `training/completed/activities/activity_template.yaml`
- Review template: `training/completed/reviews/review_template.md`
- Local agent memory: `.agents/`
- Telegram PDF sender: `scripts/notifications/semana_pdf_telegram.py`

## Garmin Integration

- Connector script: `scripts/garmin/sync_garmin.py`
- Local credentials: `garmin/local_credentials.yaml`
- Imports root: `training/completed/imports/garmin`
- Supported V1 actions:
  - import recent activities
  - import daily recovery metrics
  - upload and schedule planned workouts from YAML files

## Garmin Commands

```bash
source .venv/bin/activate
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
python scripts/garmin/sync_garmin.py import-daily --days 14
python scripts/garmin/sync_garmin.py schedule-workout-file training/planned/workouts/<file>.yaml
```

## Planning Principles

- Start from consistency, not fantasy pace.
- Protect the shin first.
- Use heart rate to control easy and long runs.
- Use pace mainly for quality work.
- Do not force threshold or race pace estimates without data.
- Recalibrate the long-term goal from checkpoints.

## Communication Rules For Future Sessions

- Be direct and practical.
- Preserve all existing athlete data.
- Do not delete historical records.
- When changing the week, explain why.
- When reviewing a workout, always state whether the week stays intact or changes.

## Long-Term Intent

This is a persistent coaching project, not a one-off plan.
Future sessions should build on the stored files and keep the repository as the source of truth.

## Preferred Future Entry Point

Future sessions should start by reading:

1. `AGENT.md`
2. `.agents/README.md`
3. `.agents/memory/project_snapshot.md`
