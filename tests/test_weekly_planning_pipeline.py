from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
