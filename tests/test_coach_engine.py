from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from scripts.garmin import coach_engine


class CoachEngineTests(unittest.TestCase):
    @patch("scripts.garmin.coach_engine.active_context")
    @patch("scripts.garmin.coach_engine.load_daily_metrics")
    @patch("scripts.garmin.coach_engine.load_running_tolerance")
    def test_build_decision_uses_pain_and_readiness_signals(self, tolerance_mock, metrics_mock, context_mock) -> None:
        tolerance_mock.return_value = {"weeks": [{"acuteLoad": 130, "chronicLoad": 90}]}
        metrics_mock.return_value = [
            {
                "date": date(2026, 5, 12),
                "payload": {
                    "hrv": 40,
                    "training_readiness": 20,
                    "heart_rates": {"restingHeartRate": 63},
                    "training_status": {"trainingStatus": "recovery"},
                    "sleep": {"sleepScores": 45, "sleepTimeSeconds": 22000},
                },
            }
        ]
        context_mock.return_value = {
            "cycle": {"id": "cycle"},
            "goal_race": {"name": "10K", "priority": "S"},
            "days_to_goal_race": 3,
            "active_block": {"name": "Block 1: Reset, consistency and tissue tolerance"},
            "response_profile": {
                "summary": {"primary_limiter": "aerobic_durability"},
                "automation_rules": {"default_quality_backbone": ["tempo_broken"]},
                "workout_response": {},
            },
            "preferences": {},
            "selection_matrix": {"rules": [], "interpretation": {}},
            "races": [{"name": "10K"}],
        }
        activities = [
            {
                "date": date(2026, 5, 10),
                "distance_km": 8.0,
                "duration_s": 3200,
                "avg_hr": 158,
                "training_effect_label": "TEMPO",
                "aerobic_training_effect": 3.7,
                "anaerobic_training_effect": 0.5,
            }
        ]
        shin_entries = [{"date": date(2026, 5, 12), "pain_during": 4, "pain_after": 4, "pain_next_morning": 3}]

        decision = coach_engine.build_decision(activities, [], [], shin_entries, date(2026, 5, 12))

        self.assertEqual(decision["status"], "red")
        self.assertIn("readiness", " ".join(reason.lower() for reason in decision["reasons"]))
        self.assertIn("periostio", " ".join(reason.lower() for reason in decision["reasons"]))
        self.assertEqual(decision["daily_signals"]["sleep_flag"], "poor")
        self.assertEqual(decision["daily_signals"]["running_tolerance_flag"], "high")


if __name__ == "__main__":
    unittest.main()
