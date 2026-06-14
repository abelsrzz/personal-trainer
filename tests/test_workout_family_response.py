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

from scripts.system import workout_family_response


class WorkoutFamilyResponseTests(unittest.TestCase):
    def test_builds_family_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            review_root = Path(tmp_dir)
            (review_root / "a.analysis.json").write_text(
                json.dumps({"planned": {"knowledge_id": "tempo_broken", "date": "2026-06-10"}, "score": 8, "risk_level": "bajo"}),
                encoding="utf-8",
            )
            (review_root / "b.analysis.json").write_text(
                json.dumps({"planned": {"knowledge_id": "tempo_broken", "date": "2026-06-12"}, "score": 6, "risk_level": "medio"}),
                encoding="utf-8",
            )
            with patch.object(workout_family_response, "REVIEW_ROOT", review_root):
                payload = workout_family_response.build_workout_family_response()

        self.assertEqual(len(payload["families"]), 1)
        self.assertEqual(payload["families"][0]["family"], "tempo_broken")
        self.assertEqual(payload["families"][0]["avg_score"], 7.0)


if __name__ == "__main__":
    unittest.main()
