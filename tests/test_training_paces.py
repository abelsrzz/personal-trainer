from __future__ import annotations

import unittest
from datetime import date

from scripts.system.training_paces import build_training_paces


class TrainingPacesTests(unittest.TestCase):
    def test_build_training_paces_uses_recent_evidence(self) -> None:
        activities = [
            {"date": date(2026, 5, 20), "fastest_5k_s": 1170, "fastest_10k_s": 2460},
        ]
        zones = {"pace": {"easy": "6:00-7:30/km", "ten_k": "4:22/km", "five_k": "4:15/km"}, "heart_rate": {"threshold_hr": 191, "z2": "145-160"}}

        payload = build_training_paces(activities, zones, as_of=date(2026, 5, 27))

        self.assertEqual(payload["strategy"], "progress_from_recent_evidence")
        self.assertEqual(payload["labels"]["ten_k_specific"]["min"], "4:03/km")
        self.assertEqual(payload["bike"]["tempo"]["min_bpm"], 160)


if __name__ == "__main__":
    unittest.main()
