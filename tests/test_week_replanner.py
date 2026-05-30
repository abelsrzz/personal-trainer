from __future__ import annotations

import unittest

from scripts.system.week_replanner import recommend_replan


class WeekReplannerTests(unittest.TestCase):
    def test_recommend_replan_replaces_quality_when_red(self) -> None:
        payload = recommend_replan(coach_status="red", shin_band="red", risky_review=True, latest_pain=5)
        self.assertIn("replace_quality", [item["type"] for item in payload["actions"]])

    def test_recommend_replan_holds_progression_when_yellow(self) -> None:
        payload = recommend_replan(coach_status="yellow", shin_band="green", risky_review=False, latest_pain=3)
        self.assertIn("hold_running_progression", [item["type"] for item in payload["actions"]])


if __name__ == "__main__":
    unittest.main()
