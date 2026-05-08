# Cycle Lifecycle

The repository is migrating from single-cycle mode to versioned cycle mode.

## Current Model

- `planning/cycles/active.yaml` defines the active cycle.
- Legacy paths like `planning/master_plan.md` and `planning/blocks/` still work as the active compatibility layer.

## Commands

Start or replace the active cycle manifest:

```bash
python scripts/system/start_cycle.py --id 2026-05-25_padron_10k --start-date 2026-05-25 --end-date 2027-02-06 --goal-race-slug XXIV_padron_10k
```

Archive the current cycle snapshot:

```bash
python scripts/system/close_cycle.py --closing-note "Cycle closed after goal race"
```

## Archiving Behavior

`close_cycle.py` snapshots the current active context into `planning/cycles/<cycle_id>/`:

- `master_plan.md`
- `blocks/`
- `weeks/`
- `goal_gates.yaml`
- `coach_decision.json`
- `coach_decision.md`
- `status_dashboard.md`
- `cycle_manifest.yaml`
- `closing_report.md`
