from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.system import weekly_planning_pipeline


class WeeklyPlanningPipelineTests(unittest.TestCase):
    def test_plan_next_week_prepares_safe_week(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            prepared_dir = Path(tmp_dir) / "prepared"
            state_box: dict[str, dict] = {}

            def fake_save_state(payload: dict) -> None:
                state_box["payload"] = payload

            def fake_execute(target_start: date, target_end: date, output_path: Path):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    f"# Semana\n\nDel `{target_start.isoformat()}` al `{target_end.isoformat()}`\n",
                    encoding="utf-8",
                )
                return True, "Siguiente semana preparada.", {"command": "opencode run", "returncode": 0}

            with (
                patch.object(weekly_planning_pipeline, "PREPARED_WEEKS_DIR", prepared_dir),
                patch.object(weekly_planning_pipeline, "load_state", return_value={"prepared_weeks": {}}),
                patch.object(weekly_planning_pipeline, "save_state", side_effect=fake_save_state),
                patch.object(
                    weekly_planning_pipeline,
                    "current_active_week_info",
                    return_value={
                        "exists": True,
                        "path": "planning/weeks/semana_actual.md",
                        "title": "Semana activa",
                        "start_date": "2026-05-18",
                        "end_date": "2026-05-24",
                    },
                ),
                patch.object(weekly_planning_pipeline, "execute_opencode_planning", side_effect=fake_execute),
                patch.object(weekly_planning_pipeline, "sync_workouts_to_garmin", return_value={"items": [], "synced": 0, "failed": 0, "skipped": 0}),
            ):
                result = weekly_planning_pipeline.plan_next_week(force=False, source="test")

            self.assertTrue(result["ok"])
            self.assertEqual(result["code"], "prepared")
            self.assertIn("2026-05-25", state_box["payload"]["prepared_weeks"])

    def test_plan_range_requires_successful_post_garmin_verification(self) -> None:
        state_box: dict[str, dict] = {}

        def fake_save_state(payload: dict) -> None:
            state_box["payload"] = payload

        with (
            patch.object(weekly_planning_pipeline, "load_state", return_value={"prepared_weeks": {}}),
            patch.object(weekly_planning_pipeline, "save_state", side_effect=fake_save_state),
            patch.object(weekly_planning_pipeline, "pre_operation_sync", return_value={"ok": True, "summary": "ok"}),
            patch.object(weekly_planning_pipeline, "collect_range_snapshot", return_value={}),
            patch.object(weekly_planning_pipeline, "changed_paths_against_snapshot", return_value=["planning/weeks/semana_actual.md"]),
            patch.object(weekly_planning_pipeline, "execute_opencode_prompt", return_value=(True, "Operacion OpenCode completada.", {"command": "opencode run", "returncode": 0})),
            patch.object(weekly_planning_pipeline, "sync_planned_workouts_verified", return_value={"ok": False, "payload": {"failed": 1}, "message": "bad"}),
            patch.object(weekly_planning_pipeline, "refresh_operational_artifacts"),
        ):
            result = weekly_planning_pipeline.plan_range("2026-06-16", "2026-06-18", "Subir fuerza", "test")

        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "garmin_sync_failed")
        self.assertEqual(state_box["payload"]["last_range_operation"]["operation"], "plan_range")

    def test_range_agent_prompt_rejects_success_without_file_changes(self) -> None:
        with (
            patch.object(weekly_planning_pipeline, "execute_opencode_prompt", return_value=(True, "Operacion OpenCode completada.", {"run_id": "run1"})),
            patch.object(weekly_planning_pipeline, "changed_paths_against_snapshot", return_value=[]),
            patch.object(weekly_planning_pipeline, "_execute_via_gemini", return_value=(False, "Gemini sin cambios", {"fallback": "gemini"})),
        ):
            ok, message, detail, changed_paths = weekly_planning_pipeline.execute_range_agent_prompt(
                "prompt",
                date(2026, 6, 16),
                date(2026, 6, 18),
                {},
            )

        self.assertFalse(ok)
        self.assertIn("sin modificar archivos", message)
        self.assertEqual(changed_paths, [])
        self.assertIn("opencode_no_changes", detail)

    def test_replan_workout_reuses_canonical_yaml_and_verifies_garmin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workouts_dir = root / "training" / "planned" / "workouts"
            workout_path = workouts_dir / "2026-06-17_quality.yaml"
            workout_path.parent.mkdir(parents=True, exist_ok=True)
            workout_path.write_text(
                """
workout:
  name: Calidad
  schedule_date: 2026-06-17
  description: Original
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: interval
      duration_s: 300
      description: Original
""".strip()
                + "\n",
                encoding="utf-8",
            )

            def fake_execute(_prompt: str):
                workout_path.write_text(
                    """
workout:
  name: Calidad replanificada
  schedule_date: 2026-06-17
  description: Nueva version
  estimated_duration_s: 2100
  steps:
    - order: 1
      step_type: interval
      duration_s: 420
      description: 7x1000
""".strip()
                    + "\n",
                    encoding="utf-8",
                )
                return True, "ok", {"command": "opencode run", "returncode": 0}

            with (
                patch.object(weekly_planning_pipeline, "ROOT", root),
                patch.object(weekly_planning_pipeline, "PLANNED_WORKOUTS_DIR", workouts_dir),
                patch.object(weekly_planning_pipeline, "pre_operation_sync", return_value={"ok": True, "summary": "ok"}),
                patch.object(weekly_planning_pipeline, "execute_opencode_prompt", side_effect=fake_execute),
                patch.object(weekly_planning_pipeline, "sync_single_workout_and_verify", return_value={"ok": True, "message": "Garmin OK"}),
                patch.object(weekly_planning_pipeline, "refresh_operational_artifacts"),
                patch.object(weekly_planning_pipeline, "load_state", return_value={"prepared_weeks": {}}),
                patch.object(weekly_planning_pipeline, "save_state"),
            ):
                result = weekly_planning_pipeline.replan_workout("2026-06-17_quality", "7x1000", "test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "replanned")
        self.assertEqual(result["changed_paths"], ["training/planned/workouts/2026-06-17_quality.yaml"])


if __name__ == "__main__":
    unittest.main()
