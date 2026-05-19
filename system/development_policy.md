# Dynamic Development Policy

Every new system feature that depends on changing data must be implemented as a dynamic capability.

## Mandatory Rules

1. No new feature may rely only on a static local file when an upstream source exists.
2. Every new dynamic feature must declare a capability in `system/capabilities/registry.yaml`.
3. Every capability must define:
   - source of truth
   - local cache files
   - freshness strategy
   - sync command
   - consumers
   - stale behavior
4. If Garmin can provide the data, the system must try Garmin before asking the athlete.
5. If Garmin fails, the system may use the local cache only if it also reports that the data may be stale.
6. Agent workflows must prefer capabilities over direct file reads for dynamic data.
7. Derived outputs like dashboards, decisions and reports must declare which capabilities they depend on.

## Freshness Strategies

- `refresh_before_read`: always try to refresh before using the capability.
- `refresh_before_decision`: refresh before planning, reviewing or making a coaching decision.
- `scheduled_refresh`: refresh in background on a cadence.

## Development Checklist

When adding a feature:

1. Register the capability.
2. Implement the sync path.
3. Implement freshness state tracking.
4. Connect the consumer to the capability engine.
5. Add stale fallback behavior.
6. Update agent instructions if the feature affects planning or coaching.
7. Add or update improvement documentation when new Garmin metrics become available.

## Garmin-First Rule

Before requesting athlete input for HRV, readiness, resting heart rate, shoe mileage or similar operational metrics, the system must attempt to refresh Garmin data first.

## Planned Workout Sync Rule

If a task creates or edits a planned workout YAML that is meant to exist in Garmin calendar, the task is not complete until the updated workout has been uploaded and scheduled in Garmin and the local Garmin upload record has been refreshed.
