from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.garmin import sync_garmin


class FakeImportClient:
    def get_activities(self, start: int, limit: int, activity_type: str):
        _ = start, limit, activity_type
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

    def upload_workout(self, payload: dict):
        self.uploaded_payload = payload
        return {"workoutId": 777}

    def schedule_workout(self, workout_id: int, schedule_date: str):
        self.scheduled = (workout_id, schedule_date)
        return {"status": "scheduled", "date": schedule_date}


class GarminSyncTests(unittest.TestCase):
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
                summary_files = list((import_root / "activities").glob("*/summary.json"))
                self.assertEqual(len(summary_files), 1)
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


if __name__ == "__main__":
    unittest.main()
