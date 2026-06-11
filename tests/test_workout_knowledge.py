from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.system import workout_knowledge as shared_knowledge

try:
    from scripts.web_v2 import legacy_support as web_app
except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
    web_app = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


class WorkoutKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        if IMPORT_ERROR is not None or web_app is None:
            self.skipTest(f"web app dependencies not available: {IMPORT_ERROR}")

    def test_workout_knowledge_matches_specific_10k_session(self) -> None:
        payload = {
            "name": "5x1000 @ ritmo 10k rec 2'",
            "description": "Sesion especifica 10k",
            "steps": [],
        }
        match = web_app.workout_knowledge_summary(payload, "quality")
        self.assertIsNotNone(match)
        self.assertEqual(match["label"], "5x1000 @ ritmo 10k rec 2'")
        self.assertTrue(any(item in match["goal_labels"] for item in ["Ritmo 10k", "Vo2max", "Resistencia especifica 10k"]))

    def test_protective_alternative_uses_knowledge_for_vo2(self) -> None:
        workout = {
            "session_kind": "quality",
            "knowledge": {
                "label": "4x5' @ ritmo 5k rec 3'",
                "goals": ["vo2max"],
                "primary_goal": "VO2max",
            },
        }
        kind, label = web_app.protective_alternative_from_knowledge(workout, "auto_today")
        self.assertEqual(kind, "recovery")
        self.assertEqual(label, "30' suave o 30' regenerativo muy suave")

    @patch("scripts.system.workout_knowledge.load_workout_knowledge")
    def test_shared_matcher_returns_semantic_summary(self, load_mock) -> None:
        load_mock.return_value = {
            "categories": {
                "ritmo_10k": [
                    {"label": "6x1000 @ ritmo 10k rec 2'", "goals": ["ritmo_10k", "resistencia_especifica_10k"]}
                ]
            }
        }
        match = shared_knowledge.match_workout_knowledge({"name": "6x1000 @ ritmo 10k rec 2'", "description": "specific 10k", "steps": []}, "quality")
        self.assertIsNotNone(match)
        self.assertEqual(match["primary_goal"], "Ritmo 10k")
        self.assertIn("resistencia especifica 10k", match["summary"].lower())

    @patch("scripts.system.workout_knowledge.load_workout_knowledge")
    def test_shared_matcher_derives_primary_goal_for_controlled_quality(self, load_mock) -> None:
        load_mock.return_value = {
            "categories": {
                "base": [
                    {"label": "50' suave", "goals": ["base_aerobica"]}
                ]
            }
        }
        match = shared_knowledge.match_workout_knowledge(
            {
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
            },
            "quality",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["primary_goal"], "Umbral lactico")

    @patch("scripts.system.workout_knowledge.template_knowledge_map")
    @patch("scripts.system.workout_knowledge.iter_knowledge_entries")
    def test_template_id_mapping_has_priority_over_text_heuristic(self, entries_mock, template_map_mock) -> None:
        entries_mock.return_value = [
            {"id": "30_suave", "label": "30' suave", "goals": ["recuperacion"], "category": "base"},
            {"id": "4x5_ritmo_21k_rec_1", "label": "4x5' @ ritmo 21k rec 1'", "goals": ["umbral_fraccionado"], "category": "threshold"},
        ]
        template_map_mock.return_value = {"cruise_intervals": {"preferred_knowledge_ids": ["4x5_ritmo_21k_rec_1"]}}
        match = shared_knowledge.match_workout_knowledge(
            {"name": "Rodaje suave con texto ambiguo", "description": "sesion controlada", "steps": []},
            "quality",
            template_id="cruise_intervals",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["id"], "4x5_ritmo_21k_rec_1")


if __name__ == "__main__":
    unittest.main()
