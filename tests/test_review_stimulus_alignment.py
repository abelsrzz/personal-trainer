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

    def test_planned_distance_includes_timed_pace_blocks(self) -> None:
        workout = {
            "workout": {
                "estimated_duration_s": 3120,
                "steps": [
                    {"step_type": "warmup", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                    {
                        "type": "repeat_group",
                        "iterations": 3,
                        "steps": [
                            {"step_type": "interval", "duration_s": 240, "target": {"type": "pace_range", "min_pace": "4:25/km", "max_pace": "4:20/km"}},
                            {"step_type": "recovery", "duration_s": 120, "target": {"type": "heart_rate_range", "min_bpm": 131, "max_bpm": 150}},
                        ],
                    },
                    {"step_type": "cooldown", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                ],
            }
        }

        planned_distance = review_planned_session.planned_distance_m(workout)

        self.assertIsNotNone(planned_distance)
        self.assertAlmostEqual(float(planned_distance), 6742.857142857143, places=3)

    def test_hr_target_windows_skip_short_post_interval_recoveries(self) -> None:
        workout = {
            "workout": {
                "estimated_duration_s": 3120,
                "steps": [
                    {"step_type": "warmup", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                    {
                        "type": "repeat_group",
                        "iterations": 3,
                        "steps": [
                            {"step_type": "interval", "duration_s": 240, "target": {"type": "pace_range", "min_pace": "4:25/km", "max_pace": "4:20/km"}},
                            {"step_type": "recovery", "duration_s": 120, "target": {"type": "heart_rate_range", "min_bpm": 131, "max_bpm": 150}},
                        ],
                    },
                    {"step_type": "cooldown", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                ],
            }
        }

        windows, hr_min, hr_max = review_planned_session.hr_target_windows(workout, actual_duration_s=3120.0)

        self.assertEqual(len(windows), 1)
        self.assertEqual(hr_min, 135.0)
        self.assertEqual(hr_max, 150.0)
        self.assertAlmostEqual(windows[0]["start_s"], 0.0, places=3)
        self.assertAlmostEqual(windows[0]["end_s"], 1020.0, places=3)

    def test_distance_compliance_disabled_for_timed_quality_sessions(self) -> None:
        workout = {
            "workout": {
                "estimated_duration_s": 3120,
                "steps": [
                    {"step_type": "warmup", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                    {
                        "type": "repeat_group",
                        "iterations": 3,
                        "steps": [
                            {"step_type": "interval", "duration_s": 240, "target": {"type": "pace_range", "min_pace": "4:25/km", "max_pace": "4:20/km"}},
                            {"step_type": "recovery", "duration_s": 120, "target": {"type": "heart_rate_range", "min_bpm": 131, "max_bpm": 150}},
                        ],
                    },
                    {"step_type": "cooldown", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                ],
            }
        }

        self.assertFalse(review_planned_session.distance_compliance_supported(workout))

    @patch("scripts.garmin.review_planned_session.match_workout_knowledge")
    def test_controlled_quality_uses_structural_goals_not_only_easy_knowledge(self, match_mock) -> None:
        match_mock.return_value = {
            "label": "50' suave",
            "goals": ["base_aerobica"],
            "primary_goal": "Base aerobica",
        }
        workout = {
            "workout": {
                "name": "Especifica controlada Ordes",
                "description": "Recordatorio controlado de ritmo cercano al objetivo de carrera.",
                "estimated_duration_s": 3120,
                "steps": [
                    {"step_type": "warmup", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                    {
                        "type": "repeat_group",
                        "iterations": 3,
                        "steps": [
                            {"step_type": "interval", "duration_s": 240, "target": {"type": "pace_range", "min_pace": "4:25/km", "max_pace": "4:20/km"}},
                            {"step_type": "recovery", "duration_s": 120, "target": {"type": "heart_rate_range", "min_bpm": 131, "max_bpm": 150}},
                        ],
                    },
                    {"step_type": "cooldown", "distance_m": 2000, "target": {"type": "heart_rate_range", "min_bpm": 135, "max_bpm": 150}},
                ],
            }
        }
        summary = {
            "trainingEffectLabel": "TEMPO",
            "aerobicTrainingEffect": 3.1,
            "anaerobicTrainingEffect": 0.2,
            "distance": 7588.0,
            "duration": 2880.0,
        }

        alignment = review_planned_session.planned_vs_actual_stimulus(workout, summary)

        self.assertEqual(alignment["alignment"], "aligned")
        self.assertIn("umbral_lactico", alignment["overlap"])

    def test_score_session_can_reach_ten(self) -> None:
        self.assertEqual(review_planned_session.score_session(None, 8.0, 5.0), 10)

    @patch("scripts.garmin.review_planned_session.load_preferences")
    def test_easy_floor_tolerance_accepts_small_hr_drift_at_730_pace(self, preferences_mock) -> None:
        preferences_mock.return_value = {
            "easy_run_constraints": {
                "mechanical_floor_pace": "7:30/km",
                "max_hr_tolerance_bpm_at_floor": 3,
                "floor_activation_band": "7:20-7:30/km",
            }
        }

        accepted = review_planned_session.within_easy_floor_tolerance(1000.0 / 450.0, 152.0, 150.0)

        self.assertTrue(accepted)

    @patch("scripts.garmin.review_planned_session.load_preferences")
    def test_easy_floor_tolerance_does_not_accept_large_hr_drift(self, preferences_mock) -> None:
        preferences_mock.return_value = {
            "easy_run_constraints": {
                "mechanical_floor_pace": "7:30/km",
                "max_hr_tolerance_bpm_at_floor": 3,
                "floor_activation_band": "7:20-7:30/km",
            }
        }

        accepted = review_planned_session.within_easy_floor_tolerance(1000.0 / 450.0, 154.5, 150.0)

        self.assertFalse(accepted)


if __name__ == "__main__":
    unittest.main()
