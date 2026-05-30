from __future__ import annotations

import unittest
from datetime import date

from scripts.system import load_progression


class LoadProgressionTests(unittest.TestCase):
    def test_progression_window_uses_last_absorbed_week(self) -> None:
        reviews = [
            {
                "planned": {"date": "2026-05-05", "sport": "running"},
                "summary": {"distance_m": 10000, "duration_s": 3000},
                "risk_level": "bajo",
                "score": 8,
            },
            {
                "planned": {"date": "2026-05-07", "sport": "cycling"},
                "summary": {"distance_m": 0, "duration_s": 3600},
                "risk_level": "bajo",
                "score": 8,
            },
        ]
        shin_entries = [{"date": "2026-05-07", "pain_during": 1, "pain_after": 1, "pain_next_morning": 1}]

        payload = load_progression.progression_window(reviews, shin_entries, as_of=date(2026, 5, 10), coach_status="green")

        self.assertEqual(payload["status"], "allow_small_progression")
        self.assertEqual(payload["baseline_running_km"], 10.0)
        self.assertAlmostEqual(payload["next_running_target_km"], 10.5)
        self.assertTrue(payload["keep_bike_support_session"])

    def test_progression_window_blocks_when_shin_red(self) -> None:
        reviews = [
            {
                "planned": {"date": "2026-05-05", "sport": "running"},
                "summary": {"distance_m": 8000, "duration_s": 2800},
                "risk_level": "alto",
                "score": 4,
            }
        ]
        shin_entries = [{"date": "2026-05-06", "pain_during": 5, "pain_after": 5, "pain_next_morning": 4}]

        payload = load_progression.progression_window(reviews, shin_entries, as_of=date(2026, 5, 10), coach_status="red")

        self.assertEqual(payload["status"], "hold_or_reduce")
        self.assertIn("running_progression", payload["blocked_dimensions"])


if __name__ == "__main__":
    unittest.main()
