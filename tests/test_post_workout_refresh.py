from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.garmin import post_workout_refresh


class PostWorkoutRefreshTests(unittest.TestCase):
    def test_review_error_is_non_blocking_for_unmatched_activity(self) -> None:
        self.assertTrue(
            post_workout_refresh.review_error_is_non_blocking(
                "FileNotFoundError: No local Garmin matching activities found for 2026-06-03"
            )
        )
        self.assertTrue(
            post_workout_refresh.review_error_is_non_blocking(
                "FileNotFoundError: No Garmin activity with id 22939403784 available for review"
            )
        )
        self.assertFalse(post_workout_refresh.review_error_is_non_blocking("Unexpected crash"))

    def test_activity_summaries_skips_non_reviewable_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            activities = root / "activities"
            walk_dir = activities / "2026-05-19_22939403784"
            run_dir = activities / "2026-05-20_22950000000"
            walk_dir.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)
            (walk_dir / "summary.json").write_text(
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
            (run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "activityId": 22950000000,
                        "activityName": "Rodaje",
                        "startTimeLocal": "2026-05-20 08:00:00",
                        "activityType": {"typeKey": "running"},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(post_workout_refresh, "IMPORT_ROOT", activities), patch.object(post_workout_refresh, "ROOT", root):
                items = post_workout_refresh.activity_summaries()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["activity_id"], 22950000000)
        self.assertEqual(items[0]["activity_type"], "running")


if __name__ == "__main__":
    unittest.main()
