# Workout Reviewer Skill

Use this guidance after each completed workout.

## Required Output

1. Numeric score
2. Traffic light
3. Written review
4. Coaching decision: keep week or replanify

## Review Priorities

- Did the session achieve its purpose?
- Was the intensity controlled correctly?
- Do heart rate, pace and sensations agree?
- Did terrain, shoes or fatigue distort execution?
- Is shin risk increasing?
- What does `planning/coach_decision.md` say after refreshing coach automation?

## Replanning Rule

Replanify the current week if:

- the session was badly missed for non-trivial reasons
- fatigue is clearly higher than expected
- pain or shin symptoms rose
- recovery markers suggest backing off
- coach decision is `red`

## Preferred Automation

```bash
source .venv/bin/activate
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
```

Use `--skip-garmin` if Garmin data is already imported.
