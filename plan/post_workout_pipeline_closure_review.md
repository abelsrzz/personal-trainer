# Post-Workout Pipeline Closure Review

## Scope

- Review date: `2026-05-11`
- Phase: `phase_06_automation_mastery`
- Reviewed flow: `scripts/garmin/post_workout_refresh.py` -> `scripts/garmin/review_planned_session.py` -> `scripts/garmin/coach_engine.py` -> web surfaces

## Expected Causality Checklist

When a completed workout appears, the system should propagate these effects without manual intervention:

1. Detect the new event.
2. Import the Garmin activity and supporting daily/profile context when needed.
3. Materialize one local completed-workout artifact.
4. Produce one review outcome for that activity, even if the match to plan is imperfect.
5. Rebuild coach decision, dashboard and progress-facing outputs.
6. Detect whether subjective feedback is still missing.
7. Reprocess derived state when feedback later arrives.
8. Promote injury-relevant pain signals to structured tracking.
9. Leave visible processing trace and health state.

## What Is Already Closed

1. New Garmin activities are detected automatically and processed idempotently.
2. Daily metrics and athlete profile can be refreshed inside the same post-workout run.
3. A planned workout with a single valid match produces:
   - local completed activity YAML
   - review markdown
   - review analysis JSON
4. Coach decision and dashboard are rebuilt automatically after a new processed activity.
5. Feedback file updates are detected and can retrigger the decision engine.
6. Tibial or periosteum pain can be promoted automatically into `athlete/shin_tracker.yaml`.
7. The web already exposes recent pipeline runs, last success and recent processed items.

## Remaining Functional Gaps

### Gap 1. Success is declared even when no canonical review outcome exists

- Current behavior treats `No planned workout found` and `Multiple planned workouts found` as non-fatal conditions in `post_workout_refresh.py`.
- In those cases the pipeline still marks the activity as processed, but no completed activity artifact or review is created.
- Result: the event is considered closed operationally even though plan-vs-reality, scoring and feedback entry remain unresolved.

### Gap 2. Missing subjective feedback is not modeled as pending work

- The pipeline reacts when a feedback file exists, but it does not create or expose a pending-feedback state after a workout is processed.
- Result: the system can say the post-workout flow succeeded while the athlete input loop is still open.

### Gap 3. Web feedback save is not causally closed in the same interaction

- Saving feedback from the web writes `training/completed/feedback/*.feedback.json`, but does not trigger an immediate local refresh.
- Derived outputs are updated only when the polling pipeline runs again.
- Result: the flow is automatic eventually, but not closed at the moment the athlete completes feedback.

## Verdict

- The pipeline is technically automated, but not yet functionally closed.
- The remaining work is no longer about detection or observability.
- The real gap is closure quality: every completed workout must end in an explicit review state, an explicit feedback state, and a fully refreshed downstream context.

## Priority Decision

Priority next item: `AP-07` Close functional gaps in the post-workout pipeline.

Why this next:

1. It resolves the only remaining places where the system can report success without complete causal closure.
2. It upgrades the pipeline from "automatic in normal cases" to "operationally complete in real cases".
3. It unlocks any later automation phase from a stable event model instead of layering features over silent exceptions.
