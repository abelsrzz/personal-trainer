from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.garmin import review_planned_session


class ReviewPlannedSessionLocalActivityTests(unittest.TestCase):
    def test_load_local_activity_by_id_reads_imported_activity_without_day_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            import_root = Path(tmp_dir)
            activity_dir = import_root / "activities" / "2026-05-19_22939403784"
            activity_dir.mkdir(parents=True, exist_ok=True)
            (activity_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "activityId": 22939403784,
                        "activityName": "Ordes Caminar",
                        "startTimeLocal": "2026-05-19 19:35:24",
                        "activityType": {"typeKey": "walking"},
                    }
                ),
                encoding="utf-8",
            )

            original_root = review_planned_session.DEFAULT_IMPORT_ROOT
            review_planned_session.DEFAULT_IMPORT_ROOT = import_root
            try:
                payload = review_planned_session.load_local_activity_by_id(22939403784)
                folder = review_planned_session.local_activity_dir_by_id(22939403784)
            finally:
                review_planned_session.DEFAULT_IMPORT_ROOT = original_root

        self.assertEqual(payload["activityId"], 22939403784)
        self.assertEqual(payload["activityType"]["typeKey"], "walking")
        self.assertEqual(folder.name, "2026-05-19_22939403784")


if __name__ == "__main__":
    unittest.main()
