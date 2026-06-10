from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


def _install_garmin_stubs() -> None:
    garmin_module = types.ModuleType("garminconnect")
    garmin_module.Garmin = object

    workout_module = types.ModuleType("garminconnect.workout")

    class DummyWorkoutObject:
        def __init__(self, **kwargs) -> None:
            self.payload = kwargs

        def to_dict(self) -> dict:
            def convert(value):
                if isinstance(value, list):
                    return [convert(item) for item in value]
                if hasattr(value, "to_dict"):
                    return value.to_dict()
                return value

            return {key: convert(value) for key, value in self.payload.items()}

    for name in [
        "CyclingWorkout",
        "ExecutableStep",
        "FitnessEquipmentWorkout",
        "RepeatGroup",
        "RunningWorkout",
        "SwimmingWorkout",
        "WorkoutSegment",
    ]:
        setattr(workout_module, name, DummyWorkoutObject)

    sys.modules.setdefault("garminconnect", garmin_module)
    sys.modules.setdefault("garminconnect.workout", workout_module)


_install_garmin_stubs()

from scripts.garmin import sync_garmin


class FakeImportClient:
    def __init__(self) -> None:
        self.requested_activity_type = None

    def get_activities(self, start: int, limit: int, activity_type: str):
        _ = start, limit
        self.requested_activity_type = activity_type
        today = date.today().isoformat()
        return [
            {
                "activityId": 123,
                "startTimeLocal": f"{today} 08:00:00",
                "activityName": "Rodaje suave",
            }
        ]

    def get_activity_details(self, activity_id: int):
        return {"activityId": activity_id, "splits": []}


class FakeProfileClient:
    def get_full_name(self):
        return "Abel Test"

    def get_user_profile(self):
        return {
            "id": 999,
            "displayName": "Abel",
            "userData": {
                "gender": "MALE",
                "birthDate": "2004-06-17",
                "weight": 64.2,
                "height": 175.0,
                "vo2MaxRunning": 47,
                "availableTrainingDays": ["MONDAY", "TUESDAY"],
                "preferredLongTrainingDays": ["SUNDAY"],
            },
        }

    def get_settings(self):
        return {"maxHR": 198}

    def get_personal_record(self):
        return []

    def get_user_summary(self, current_date: str):
        return {"calendarDate": current_date, "restingHeartRate": 50, "maxHeartRate": 198}

    def get_gear(self, user_id: int):
        return [{"displayName": "Adizero Boston", "totalDistance": 245.0, "name": "Boston"}] if user_id == 999 else []


class FakeWorkoutClient:
    def __init__(self) -> None:
        self.uploaded_payload = None
        self.scheduled = None
        self.unscheduled: list[int] = []
        self.deleted: list[int] = []
        self.calendar_items: list[dict] = []

    def upload_workout(self, payload: dict):
        self.uploaded_payload = payload
        sport_type = payload.get("sportType") or {}
        return {"workoutId": 777, "sportType": sport_type}

    def upload_swimming_workout(self, payload):
        self.uploaded_payload = payload.to_dict()
        sport_type = self.uploaded_payload.get("sportType") or {}
        return {"workoutId": 777, "sportType": sport_type}

    def schedule_workout(self, workout_id: int, schedule_date: str):
        self.scheduled = (workout_id, schedule_date)
        return {"status": "scheduled", "date": schedule_date, "workoutScheduleId": 7770}

    def unschedule_workout(self, scheduled_workout_id: int):
        self.unscheduled.append(scheduled_workout_id)
        return {"status": "unscheduled"}

    def delete_workout(self, workout_id: int):
        self.deleted.append(workout_id)
        return {"status": "deleted"}

    def get_scheduled_workouts(self, year: int, month: int):
        _ = year, month
        return {"calendarItems": list(self.calendar_items)}


class GarminSyncTests(unittest.TestCase):
    def test_infer_workout_sport_keeps_elliptical_distinct(self) -> None:
        self.assertEqual(sync_garmin.infer_workout_sport({"sport": "elliptical", "name": "Eliptica aerobica"}), "elliptical")

    def test_build_workout_payload_supports_repetition_steps_inside_repeat_group(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Fuerza por repeticiones",
                    "sport": "strength",
                    "estimated_duration_s": 1800,
                    "steps": [
                        {
                            "order": 1,
                            "type": "repeat_group",
                            "iterations": 4,
                            "steps": [
                                {
                                    "order": 2,
                                    "step_type": "interval",
                                    "description": "Flexiones · 8 repeticiones",
                                    "repetitions": 8,
                                    "exercise_name": "Push Up",
                                    "category": "PLANK",
                                    "garmin_selection_confirmed": True,
                                },
                                {
                                    "order": 3,
                                    "step_type": "recovery",
                                    "description": "Descanso",
                                    "duration_s": 60,
                                },
                            ],
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        repeat_group = payload["workoutSegments"][0]["workoutSteps"][0]
        self.assertEqual(repeat_group["numberOfIterations"], 4)
        strength_step = repeat_group["workoutSteps"][0]
        self.assertEqual(strength_step["endCondition"]["conditionTypeKey"], "reps")
        self.assertEqual(strength_step["endConditionValue"], 8.0)
        self.assertEqual(strength_step["category"], "PLANK")

    def test_build_workout_payload_uses_strength_sport_type(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Fuerza por repeticiones",
                    "sport": "strength",
                    "estimated_duration_s": 1800,
                    "steps": [{"order": 1, "step_type": "interval", "description": "Flexiones", "repetitions": 8}],
                }
            },
            include_targets=True,
        ).to_dict()
        self.assertEqual(payload["sportType"]["sportTypeKey"], "strength_training")
        self.assertEqual(payload["sportType"]["sportTypeId"], 5)
        self.assertEqual(payload["workoutSegments"][0]["sportType"]["sportTypeKey"], "strength_training")

    def test_build_workout_payload_uses_mobility_sport_type(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Movilidad",
                    "sport": "mobility",
                    "estimated_duration_s": 1200,
                    "steps": [{"order": 1, "step_type": "interval", "description": "Circulos de tobillo", "duration_s": 60}],
                }
            },
            include_targets=True,
        ).to_dict()
        self.assertEqual(payload["sportType"]["sportTypeKey"], "mobility")
        self.assertEqual(payload["sportType"]["sportTypeId"], 11)
        self.assertEqual(payload["workoutSegments"][0]["sportType"]["sportTypeKey"], "mobility")

    def test_build_workout_payload_uses_swimming_sport_type(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Natacion continua",
                    "sport": "swimming",
                    "estimated_duration_s": 1800,
                    "steps": [{"order": 1, "step_type": "interval", "description": "30 min continuos", "duration_s": 1800}],
                }
            },
            include_targets=True,
        ).to_dict()
        self.assertEqual(payload["sportType"]["sportTypeKey"], "swimming")
        self.assertEqual(payload["sportType"]["sportTypeId"], 4)
        self.assertEqual(payload["workoutSegments"][0]["sportType"]["sportTypeKey"], "swimming")

    def test_build_workout_payload_maps_exact_mobility_exercises_from_garmin_catalog(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Movilidad",
                    "sport": "mobility",
                    "estimated_duration_s": 1200,
                    "steps": [
                        {
                            "order": 1,
                            "type": "repeat_group",
                            "iterations": 2,
                            "steps": [
                                {
                                    "order": 2,
                                    "step_type": "interval",
                                    "description": "Sentadilla asistida profunda · 8 repeticiones",
                                    "repetitions": 8,
                                    "exercise_name": "Squat",
                                    "category": "SQUAT",
                                },
                                {
                                    "order": 3,
                                    "step_type": "interval",
                                    "description": "Circulos de tobillo · 45 s por lado",
                                    "duration_s": 90,
                                    "exercise_name": "Calf Raise",
                                    "category": "CALF_RAISE",
                                },
                            ],
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        mobility_steps = payload["workoutSegments"][0]["workoutSteps"][0]["workoutSteps"]
        self.assertNotIn("category", mobility_steps[0])
        self.assertNotIn("exerciseName", mobility_steps[0])
        self.assertEqual(mobility_steps[1]["category"], "WARM_UP")
        self.assertEqual(mobility_steps[1]["exerciseName"], "ANKLE_CIRCLES")

    def test_import_activities_writes_manifest_and_files(self) -> None:
        client = FakeImportClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            import_root = Path(tmp_dir)
            original_import_root = sync_garmin.DEFAULT_IMPORT_ROOT
            sync_garmin.DEFAULT_IMPORT_ROOT = import_root
            try:
                sync_garmin.import_activities(client, days=3, limit=10, activity_type="running", download_format=None)
                manifest = json.loads((import_root / "activities" / "last_import_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["imported_count"], 1)
                self.assertEqual(manifest["imported_activity_ids"], [123])
                self.assertEqual(manifest["activity_type"], "running")
                summary_files = list((import_root / "activities").glob("*/summary.json"))
                self.assertEqual(len(summary_files), 1)
            finally:
                sync_garmin.DEFAULT_IMPORT_ROOT = original_import_root

    def test_import_activities_without_filter_uses_all_activity_types(self) -> None:
        client = FakeImportClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            import_root = Path(tmp_dir)
            original_import_root = sync_garmin.DEFAULT_IMPORT_ROOT
            sync_garmin.DEFAULT_IMPORT_ROOT = import_root
            try:
                sync_garmin.import_activities(client, days=3, limit=10, activity_type="all", download_format=None)
                manifest = json.loads((import_root / "activities" / "last_import_manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["activity_type"], "all")
                self.assertIsNone(client.requested_activity_type)
            finally:
                sync_garmin.DEFAULT_IMPORT_ROOT = original_import_root

    def test_import_athlete_profile_handles_argument_methods(self) -> None:
        client = FakeProfileClient()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("scripts.garmin.sync_garmin.write_athlete_state"):
            import_root = Path(tmp_dir)
            original_import_root = sync_garmin.DEFAULT_IMPORT_ROOT
            sync_garmin.DEFAULT_IMPORT_ROOT = import_root
            try:
                sync_garmin.import_athlete_profile(client)
                payload = json.loads((import_root / "profile" / "athlete_profile_snapshot.json").read_text(encoding="utf-8"))
                self.assertEqual(payload["resting_heart_rate"], 50)
                self.assertEqual(payload["max_heart_rate"], 198)
                self.assertEqual(payload["gear"][0]["display_name"], "Adizero Boston")
                self.assertEqual(payload["training_days"], ["MONDAY", "TUESDAY"])
            finally:
                sync_garmin.DEFAULT_IMPORT_ROOT = original_import_root

    def test_schedule_workout_file_records_upload(self) -> None:
        client = FakeWorkoutClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workout_file = tmp_path / "2026-05-26_easy.yaml"
            workout_file.write_text(
                """
workout:
  name: Rodaje suave
  description: Rodaje de prueba
  sport: running
  schedule_date: 2026-05-26
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: warmup
      duration_s: 1800
      description: 30 min faciles
""".strip()
                + "\n",
                encoding="utf-8",
            )
            original_workouts_root = sync_garmin.DEFAULT_WORKOUTS_ROOT
            sync_garmin.DEFAULT_WORKOUTS_ROOT = tmp_path / "planned"
            try:
                sync_garmin.schedule_workout_file(client, workout_file)
                record = json.loads(
                    (sync_garmin.DEFAULT_WORKOUTS_ROOT / "2026-05-26" / "2026-05-26_easy.garmin_upload.json").read_text(encoding="utf-8")
                )
                self.assertEqual(record["status"], "scheduled")
                self.assertEqual(client.scheduled, (777, "2026-05-26"))
            finally:
                sync_garmin.DEFAULT_WORKOUTS_ROOT = original_workouts_root

    def test_schedule_workout_file_accepts_elliptical_sport(self) -> None:
        client = FakeWorkoutClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workout_file = tmp_path / "2026-05-26_elliptical.yaml"
            workout_file.write_text(
                """
workout:
  name: Eliptica aerobica
  description: Sesion sin impacto
  sport: elliptical
  schedule_date: 2026-05-26
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: warmup
      duration_s: 1800
      description: 30 min suaves
""".strip()
                + "\n",
                encoding="utf-8",
            )
            original_workouts_root = sync_garmin.DEFAULT_WORKOUTS_ROOT
            sync_garmin.DEFAULT_WORKOUTS_ROOT = tmp_path / "planned"
            try:
                sync_garmin.schedule_workout_file(client, workout_file)
                self.assertEqual(client.scheduled, (777, "2026-05-26"))
                self.assertEqual(client.uploaded_payload["sportType"]["sportTypeKey"], "other")
                self.assertEqual(client.uploaded_payload["workoutSegments"][0]["sportType"]["sportTypeKey"], "other")
            finally:
                sync_garmin.DEFAULT_WORKOUTS_ROOT = original_workouts_root

    def test_schedule_workout_file_leaves_non_exact_strength_family_unmapped_and_replaces_previous_upload(self) -> None:
        client = FakeWorkoutClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workout_file = tmp_path / "2026-05-26_strength.yaml"
            workout_file.write_text(
                """
workout:
  name: Fuerza A
  description: Sesion de fuerza
  sport: strength
  schedule_date: 2026-05-26
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: interval
      duration_s: 180
      description: Split squat · 3 x 8 por lado
      exercise_name: Split Squat
""".strip()
                + "\n",
                encoding="utf-8",
            )
            stale_dir = tmp_path / "planned" / "2026-05-20"
            stale_dir.mkdir(parents=True, exist_ok=True)
            stale_record = stale_dir / "2026-05-26_strength.garmin_upload.json"
            stale_record.write_text(
                json.dumps(
                    {
                        "uploaded_response": {"workoutId": 123},
                        "scheduled_response": {"workoutScheduleId": 456, "workout": {"workoutId": 123}},
                    }
                ),
                encoding="utf-8",
            )
            original_workouts_root = sync_garmin.DEFAULT_WORKOUTS_ROOT
            sync_garmin.DEFAULT_WORKOUTS_ROOT = tmp_path / "planned"
            try:
                sync_garmin.schedule_workout_file(client, workout_file)
                self.assertNotIn("category", client.uploaded_payload["workoutSegments"][0]["workoutSteps"][0])
                self.assertNotIn("exerciseName", client.uploaded_payload["workoutSegments"][0]["workoutSteps"][0])
                self.assertEqual(client.unscheduled, [456])
                self.assertEqual(client.deleted, [123])
                self.assertFalse(stale_record.exists())
            finally:
                sync_garmin.DEFAULT_WORKOUTS_ROOT = original_workouts_root

    def test_build_workout_payload_maps_exact_visible_strength_family(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Fuerza por repeticiones",
                    "sport": "strength",
                    "estimated_duration_s": 1800,
                    "steps": [
                        {
                            "order": 1,
                            "step_type": "interval",
                            "description": "Standing calf raise · 12 repeticiones",
                            "repetitions": 12,
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        strength_step = payload["workoutSegments"][0]["workoutSteps"][0]
        self.assertEqual(strength_step["category"], "CALF_RAISE")
        self.assertEqual(strength_step["exerciseName"], "STANDING_CALF_RAISE")

    def test_build_workout_payload_maps_exact_glute_bridge_catalog_entry(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Movilidad",
                    "sport": "mobility",
                    "estimated_duration_s": 1200,
                    "steps": [
                        {
                            "order": 1,
                            "step_type": "interval",
                            "description": "Glute bridge suave · 10 repeticiones",
                            "repetitions": 10,
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        step = payload["workoutSegments"][0]["workoutSteps"][0]
        self.assertEqual(step["category"], "BANDED_EXERCISES")
        self.assertEqual(step["exerciseName"], "GLUTE_BRIDGE")

    def test_build_workout_payload_keeps_description_only_for_unmapped_mobility_exercise(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Movilidad",
                    "sport": "mobility",
                    "estimated_duration_s": 1200,
                    "steps": [
                        {
                            "order": 1,
                            "step_type": "interval",
                            "description": "Respiracion diafragmatica suave · 60 s",
                            "duration_s": 60,
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        mobility_step = payload["workoutSegments"][0]["workoutSteps"][0]
        self.assertNotIn("category", mobility_step)
        self.assertNotIn("exerciseName", mobility_step)

    def test_build_workout_payload_preserves_confirmed_strength_selection(self) -> None:
        payload = sync_garmin.build_workout_payload(
            {
                "workout": {
                    "name": "Fuerza por repeticiones",
                    "sport": "strength",
                    "estimated_duration_s": 1800,
                    "steps": [
                        {
                            "order": 1,
                            "step_type": "interval",
                            "description": "Squat · 8 repeticiones",
                            "repetitions": 8,
                            "exercise_name": "Squat",
                            "category": "SQUAT",
                            "garmin_selection_confirmed": True,
                        }
                    ],
                }
            },
            include_targets=True,
        ).to_dict()
        strength_step = payload["workoutSegments"][0]["workoutSteps"][0]
        self.assertEqual(strength_step["category"], "SQUAT")
        self.assertEqual(strength_step["exerciseName"], "Squat")

    def test_schedule_workout_file_omits_warning_when_garmin_preserves_strength_type(self) -> None:
        client = FakeWorkoutClient()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workout_file = tmp_path / "2026-05-26_strength.yaml"
            workout_file.write_text(
                """
workout:
  name: Fuerza A
  description: Sesion de fuerza
  sport: strength
  schedule_date: 2026-05-26
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: interval
      duration_s: 180
      description: Split squat · 3 x 8 por lado
      exercise_name: Split Squat
""".strip()
                + "\n",
                encoding="utf-8",
            )
            original_workouts_root = sync_garmin.DEFAULT_WORKOUTS_ROOT
            sync_garmin.DEFAULT_WORKOUTS_ROOT = tmp_path / "planned"
            try:
                sync_garmin.schedule_workout_file(client, workout_file)
                record = json.loads(
                    (sync_garmin.DEFAULT_WORKOUTS_ROOT / "2026-05-26" / "2026-05-26_strength.garmin_upload.json").read_text(encoding="utf-8")
                )
                self.assertIsNone(record["warning"])
            finally:
                sync_garmin.DEFAULT_WORKOUTS_ROOT = original_workouts_root

    def test_schedule_workout_file_cleans_calendar_duplicates_by_date_and_title(self) -> None:
        client = FakeWorkoutClient()
        client.calendar_items = [
            {
                "id": 456,
                "itemType": "workout",
                "title": "Fuerza A",
                "date": "2026-05-26",
                "workoutId": 123,
            },
            {
                "id": 7770,
                "itemType": "workout",
                "title": "Fuerza A",
                "date": "2026-05-26",
                "workoutId": 777,
            },
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            workout_file = tmp_path / "2026-05-26_strength.yaml"
            workout_file.write_text(
                """
workout:
  name: Fuerza A
  description: Sesion de fuerza
  sport: strength
  schedule_date: 2026-05-26
  estimated_duration_s: 1800
  steps:
    - order: 1
      step_type: interval
      duration_s: 180
      description: Split squat · 3 x 8 por lado
      exercise_name: Split Squat
""".strip()
                + "\n",
                encoding="utf-8",
            )
            original_workouts_root = sync_garmin.DEFAULT_WORKOUTS_ROOT
            sync_garmin.DEFAULT_WORKOUTS_ROOT = tmp_path / "planned"
            try:
                sync_garmin.schedule_workout_file(client, workout_file)
                self.assertIn(456, client.unscheduled)
                self.assertIn(123, client.deleted)
                self.assertNotIn(7770, client.unscheduled)
            finally:
                sync_garmin.DEFAULT_WORKOUTS_ROOT = original_workouts_root


if __name__ == "__main__":
    unittest.main()
