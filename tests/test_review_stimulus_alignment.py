from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.garmin import review_planned_session


class ReviewStimulusAlignmentTests(unittest.TestCase):
    @patch("scripts.garmin.review_planned_session.match_workout_knowledge")
    def test_stimulus_alignment_marks_aligned_threshold_session(self, match_mock) -> None:
        match_mock.return_value = {
            "label": "20' @ ritmo umbral / 21k",
            "goals": ["umbral_lactico"],
            "primary_goal": "Umbral lactico",
        }
        workout = {"workout": {"name": "20' @ ritmo umbral / 21k", "description": "Tempo controlado", "steps": []}}
        summary = {
            "trainingEffectLabel": "TEMPO",
            "aerobicTrainingEffect": 3.1,
            "anaerobicTrainingEffect": 0.1,
            "distance": 6000.0,
            "duration": 1500.0,
        }
        alignment = review_planned_session.planned_vs_actual_stimulus(workout, summary)
        self.assertEqual(alignment["alignment"], "aligned")
        self.assertIn("umbral_lactico", alignment["overlap"])


if __name__ == "__main__":
    unittest.main()
