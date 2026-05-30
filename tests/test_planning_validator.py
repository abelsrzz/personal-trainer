from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.system import planning_validator


class PlanningValidatorTests(unittest.TestCase):
    def test_validate_prepared_week_warns_without_bike_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            week_path = root / "week.md"
            week_path.write_text("# Semana\n\nDel `2026-06-01` al `2026-06-07`\n", encoding="utf-8")
            workouts_dir = root / "training" / "planned" / "workouts"
            workouts_dir.mkdir(parents=True, exist_ok=True)
            (workouts_dir / "2026-06-02_run.yaml").write_text(
                "workout:\n  schedule_date: 2026-06-02\n  sport: running\n  description: rodaje facil\n",
                encoding="utf-8",
            )
            with patch.object(planning_validator, "ROOT", root):
                payload = planning_validator.validate_prepared_week(week_path)
            self.assertTrue(payload["ok"])
            self.assertTrue(any("bici" in item.lower() for item in payload["warnings"]))


if __name__ == "__main__":
    unittest.main()
