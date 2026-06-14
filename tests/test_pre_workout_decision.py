from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.system import pre_workout_decision


class PreWorkoutDecisionTests(unittest.TestCase):
    def test_returns_rest_when_no_workout(self) -> None:
        with (
            patch.object(pre_workout_decision, "load_today_feed_runtime", return_value={"today_workout": None, "today_review": None, "today_plan": {"date": "2026-06-14"}}),
            patch.object(pre_workout_decision, "load_json", return_value={}),
        ):
            payload = pre_workout_decision.build_pre_workout_decision("2026-06-14")

        self.assertEqual(payload["action"], "rest_or_optional")

    def test_yellow_quality_day_swaps_to_lower_cost(self) -> None:
        today_feed = {
            "today_plan": {"date": "2026-06-14"},
            "today_workout": {
                "name": "Tempo controlado",
                "session_kind": "tempo",
                "session_kind_label": "Tempo",
                "description": "Trabajo de umbral",
            },
            "today_review": None,
        }
        athlete_state = {
            "athlete": {"impact_return": {"blocked_dimensions": ["running_progression"], "baseline_running_km": 18.0}},
            "garmin": {"daily_metrics": {"latest_training_readiness": 58}},
        }
        coach_decision = {
            "decision": {
                "status": "yellow",
                "latest_shin_entry": {"pain_during": 1, "pain_after": 1, "pain_next_morning": 1},
                "daily_signals": {"readiness_flag": "moderate"},
            }
        }

        with (
            patch.object(pre_workout_decision, "load_today_feed_runtime", return_value=today_feed),
            patch.object(pre_workout_decision, "load_json", side_effect=[athlete_state, coach_decision]),
        ):
            payload = pre_workout_decision.build_pre_workout_decision("2026-06-14")

        self.assertEqual(payload["action"], "swap_to_lower_cost")


if __name__ == "__main__":
    unittest.main()
