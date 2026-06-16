"""DB-free tests for the file->SQL migration scope and the dual-write no-op guard."""

from __future__ import annotations

import os

from scripts.storage import migrate_files_to_sql as mig


def test_in_scope_includes_structured_runtime_roots():
    assert mig._in_scope("athlete/profile.yaml")
    assert mig._in_scope("training/planned/workouts/2026-05-04_x.yaml")
    assert mig._in_scope("system/state/athlete_state.json")
    assert mig._in_scope("races/2027/x.yaml")
    assert mig._in_scope("planning/coach_decision.json")  # explicit extra file


def test_in_scope_excludes_static_and_garmin_raw():
    assert not mig._in_scope("planning/coaching_playbook.md")
    assert not mig._in_scope("planning/blocks/01_base.md")
    assert not mig._in_scope("training/completed/imports/garmin/daily/2026-06-01.json")
    assert not mig._in_scope("garmin/mappings.yaml")


def test_should_skip_templates_and_non_data(tmp_path):
    assert mig.should_skip(tmp_path / "library_run_templates.yaml")
    assert mig.should_skip(tmp_path / "workout_template.yaml")
    assert mig.should_skip(tmp_path / "notes.pdf")
    assert mig.should_skip(tmp_path / "x.log")
    assert not mig.should_skip(tmp_path / "real.yaml")


def test_dry_run_summary_covers_expected_tables():
    counts = mig.dry_run_summary(mig.candidate_paths())
    assert counts.get("artifacts", 0) > 0
    assert "planned_workouts" in counts
    assert "athlete_documents" in counts


def test_mirror_is_noop_without_sql_backend(monkeypatch):
    # With STORAGE_BACKEND unset, mirror_file must not attempt any DB connection.
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)

    def _boom(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("DB connection attempted in file mode")

    monkeypatch.setattr(mig, "connection", _boom)
    mig.mirror_file("athlete/profile.yaml")  # should silently no-op
    mig.mirror_delete("athlete/profile.yaml")
