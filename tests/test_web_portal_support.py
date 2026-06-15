from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_web_framework_stubs() -> None:
    fastapi_module = types.ModuleType("fastapi")

    class DummyFastAPI:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def add_middleware(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def mount(self, *args, **kwargs) -> None:
            _ = args, kwargs

        def get(self, *args, **kwargs):
            _ = args, kwargs

            def decorator(func):
                return func

            return decorator

        def post(self, *args, **kwargs):
            _ = args, kwargs

            def decorator(func):
                return func

            return decorator

        def delete(self, *args, **kwargs):
            _ = args, kwargs

            def decorator(func):
                return func

            return decorator

    fastapi_module.FastAPI = DummyFastAPI
    fastapi_module.Form = lambda *args, **kwargs: None
    fastapi_module.Request = object
    sys.modules.setdefault("fastapi", fastapi_module)

    responses_module = types.ModuleType("fastapi.responses")
    responses_module.HTMLResponse = object
    responses_module.JSONResponse = object
    responses_module.RedirectResponse = object
    sys.modules.setdefault("fastapi.responses", responses_module)

    staticfiles_module = types.ModuleType("fastapi.staticfiles")

    class DummyStaticFiles:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs

    staticfiles_module.StaticFiles = DummyStaticFiles
    sys.modules.setdefault("fastapi.staticfiles", staticfiles_module)

    templating_module = types.ModuleType("fastapi.templating")

    class DummyTemplates:
        def __init__(self, *args, **kwargs) -> None:
            _ = args, kwargs
            self.env = types.SimpleNamespace(filters={}, globals={})

    templating_module.Jinja2Templates = DummyTemplates
    sys.modules.setdefault("fastapi.templating", templating_module)

    sessions_module = types.ModuleType("starlette.middleware.sessions")
    sessions_module.SessionMiddleware = object
    sys.modules.setdefault("starlette.middleware.sessions", sessions_module)


_install_web_framework_stubs()

from scripts.web_v2 import legacy_support as app
from scripts.garmin.recovery_analysis import build_recovery_analysis


class WebAppTests(unittest.TestCase):
    def test_calendar_day_data_includes_imported_unreviewed_activity(self) -> None:
        review = {
            "slug": "reviewed-run",
            "date": "2026-06-17",
            "garmin_activity_id": 123,
            "activity_name": "Run reviewed",
        }
        imported = {
            "slug": "garmin-import-456",
            "date": "2026-06-17",
            "garmin_activity_id": 456,
            "activity_name": "Walk imported",
            "is_imported_only": True,
        }
        with (
            patch.object(app, "planned_workouts", return_value=[]),
            patch.object(app, "completed_reviews", return_value=[review]),
            patch.object(app, "imported_garmin_activities", return_value=[imported]) as imported_mock,
            patch.object(app, "races_by_day", return_value={}),
            patch.object(app, "today_plan_data", return_value=None),
            patch.object(app, "compare_day_plan_vs_execution", return_value=[]),
            patch.object(app, "day_status_label", return_value="Hecho"),
        ):
            payload = app.calendar_day_data("2026-06-17")

        self.assertEqual(len(payload["completed_items"]), 2)
        self.assertEqual(payload["reviews"], [review])
        self.assertEqual(payload["completed_items"][1]["activity_name"], "Walk imported")
        imported_mock.assert_called_once_with("2026-06-17", {123})

    def test_imported_garmin_activity_detail_builds_readable_payload(self) -> None:
        summary = {
            "activityId": 23201148301,
            "activityName": "Ordes Caminar",
            "startTimeLocal": "2026-06-10 19:37:10",
            "activityType": {"typeKey": "walking"},
            "distance": 4541.25,
            "duration": 2677.57,
            "averageHR": 116,
        }
        with patch.object(app, "garmin_activity_summary_payload", return_value=summary), patch.object(app, "build_recovery_analysis", return_value={"status": "missing_data"}):
            item = app.imported_garmin_activity_detail(23201148301)
        self.assertEqual(item["slug"], "garmin-import-23201148301")
        self.assertEqual(item["session_kind_label"], "Caminar")
        self.assertEqual(item["garmin_activity_id"], 23201148301)

    def test_build_recovery_analysis_from_daily_hr_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            activity_root = root / "activities"
            daily_root = root / "daily"
            activity_dir = activity_root / "2026-05-24_123"
            activity_dir.mkdir(parents=True, exist_ok=True)
            (activity_dir / "summary.json").write_text(json.dumps({"activityId": 123, "endTimeGMT": "2026-05-24 09:44:59", "maxHR": 194}), encoding="utf-8")
            (activity_dir / "details.json").write_text(json.dumps({
                "metricDescriptors": [
                    {"metricsIndex": 0, "key": "directTimestamp"},
                    {"metricsIndex": 1, "key": "directHeartRate"},
                ],
                "activityDetailMetrics": [
                    {"metrics": [1779615899000, 194]},
                ],
            }), encoding="utf-8")
            (daily_root / "2026-05-24.json").parent.mkdir(parents=True, exist_ok=True)
            (daily_root / "2026-05-24.json").write_text(json.dumps({
                "heart_rates": {
                    "restingHeartRate": 55,
                    "heartRateValues": [
                        [1779615960000, 180],
                        [1779616080000, 136],
                        [1779616200000, 134],
                        [1779616440000, 130],
                        [1779616560000, 128],
                        [1779616680000, 126],
                    ],
                }
            }), encoding="utf-8")

            analysis = build_recovery_analysis({
                "planned": {"date": "2026-05-24"},
                "summary": {"activity_id": 123},
            }, activity_dir=activity_root, daily_dir=daily_root)

        self.assertEqual(analysis["status"], "complete")
        self.assertEqual(analysis["finish_hr_bpm"], 194)
        self.assertEqual(analysis["hrr_3min_bpm"], 58)
        self.assertEqual(analysis["normal_hr_bpm"], 130)

    def test_today_plan_prefers_race_review_over_unrelated_warmup_plan(self) -> None:
        planned_workout = {
            "slug": "2026-05-24_calentamiento_precarrera_ordes",
            "date": "2026-05-24",
            "name": "Calentamiento pre-carrera Ordes",
            "session_kind": "easy",
            "session_kind_label": "Rodaje facil",
            "estimated_duration": "17:00",
            "description": "Warmup",
        }
        warmup_review = {
            "slug": "2026-05-24_calentamiento_precarrera_ordes",
            "date": "2026-05-24",
            "activity_name": "Ordes - Calentamiento pre-carrera Ordes",
            "session_kind": "easy",
            "payload": {
                "planned": {
                    "planned_session_reference": "training/planned/workouts/2026-05-24_calentamiento_precarrera_ordes.yaml"
                }
            },
        }
        race_review = {
            "slug": "2026-05-24_xxix_carreira_popular_concello_de_ordes",
            "date": "2026-05-24",
            "activity_name": "Ordes - XXIX CARREIRA POPULAR CONCELLO DE ORDES",
            "session_kind": "race",
            "payload": {
                "planned": {
                    "planned_session_reference": "races/2026/2026-05-24_xxix_carreira_popular_concello_de_ordes.yaml"
                }
            },
        }
        dashboard = {"decision": {"status": "green", "recommendation": "OK", "session_guidance": {}, "daily_signals": {}}, "goal_gates": {"metrics": {}}}

        with (
            patch.object(app, "daily_checkin", return_value=None),
            patch.object(app, "daily_checkin_form_state", return_value={"exists": False}),
            patch.object(app, "preferred_replan_suggestion", return_value=None),
            patch.object(app, "races_by_day", return_value={"2026-05-24": [{"name": "XXIX CARREIRA POPULAR CONCELLO DE ORDES"}]}),
        ):
            payload = app.today_plan_data("2026-05-24", dashboard=dashboard, workouts=[planned_workout], reviews=[race_review, warmup_review])

        self.assertEqual(payload["completed_review"]["slug"], "2026-05-24_calentamiento_precarrera_ordes")
        self.assertEqual(payload["planned_workout"]["slug"], "2026-05-24_calentamiento_precarrera_ordes")

        with (
            patch.object(app, "daily_checkin", return_value=None),
            patch.object(app, "daily_checkin_form_state", return_value={"exists": False}),
            patch.object(app, "preferred_replan_suggestion", return_value=None),
            patch.object(app, "races_by_day", return_value={"2026-05-24": [{"name": "XXIX CARREIRA POPULAR CONCELLO DE ORDES"}]}),
        ):
            payload = app.today_plan_data("2026-05-24", dashboard=dashboard, workouts=[planned_workout], reviews=[race_review])

        self.assertEqual(payload["completed_review"]["slug"], "2026-05-24_xxix_carreira_popular_concello_de_ordes")
        self.assertIsNone(payload["planned_workout"])

    def test_compare_day_plan_vs_execution_marks_unlinked_review_completed_only(self) -> None:
        planned_items = [
            {
                "slug": "2026-05-24_calentamiento_precarrera_ordes",
                "name": "Calentamiento pre-carrera Ordes",
                "session_kind_label": "Rodaje facil",
                "estimated_duration": "17:00",
                "payload": {},
            }
        ]
        completed_items = [
            {
                "slug": "2026-05-24_xxix_carreira_popular_concello_de_ordes",
                "activity_name": "Ordes - XXIX CARREIRA POPULAR CONCELLO DE ORDES",
                "session_kind_label": "Carrera",
                "distance_km": 8.45,
                "duration": "39:37",
                "avg_hr": 191,
                "traffic_light": "amarillo",
                "compliance_note": "Race review",
                "payload": {
                    "planned": {
                        "planned_session_reference": "races/2026/2026-05-24_xxix_carreira_popular_concello_de_ordes.yaml"
                    },
                    "compliance": {},
                },
            }
        ]

        comparison = app.compare_day_plan_vs_execution(planned_items, completed_items)

        self.assertEqual([item["status"] for item in comparison], ["planned_only", "completed_only"])

    def test_retry_garmin_workout_sync_uses_replanned_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            workouts_dir = root / "planned"
            workout_file = workouts_dir / "quality_session.yaml"
            workout_file.parent.mkdir(parents=True, exist_ok=True)
            with workout_file.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    {
                        "workout": {
                            "name": "Series",
                            "schedule_date": "2026-05-12",
                            "description": "Original",
                            "steps": [{"order": 1, "description": "Original"}],
                        }
                    },
                    handle,
                    allow_unicode=False,
                    sort_keys=False,
                )
            replans_path = root / "planned_workout_replans.json"
            replans_path.write_text(
                json.dumps(
                    {
                        "workouts": {
                            "quality_session": {
                            "effective_date": "2026-05-13",
                            "effective_sport": "elliptical",
                            "effective_name": "Series adaptadas",
                            "effective_description": "Version protectora",
                            "effective_steps": [{"order": 1, "description": "Suave"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            stale_upload = workouts_dir / "2026-05-12" / "quality_session.garmin_upload.json"
            stale_upload.parent.mkdir(parents=True, exist_ok=True)
            stale_upload.write_text("{}", encoding="utf-8")

            seen_command: dict[str, str] = {}

            def fake_run(command: list[str], **kwargs):
                _ = kwargs
                seen_command["workout_file"] = command[-1]

                class Result:
                    returncode = 0
                    stdout = '{"status": "ok"}'
                    stderr = ""

                return Result()

            with (
                patch.object(app, "ROOT", root),
                patch.object(app, "PLANNED_WORKOUTS_DIR", workouts_dir),
                patch.object(app, "PLANNED_REPLANS_PATH", replans_path),
                patch.object(app, "GARMIN_SYNC_SCRIPT", root / "sync_garmin.py"),
                patch.object(app, "set_garmin_retry_state"),
                patch.object(app.subprocess, "run", side_effect=fake_run),
            ):
                ok, _message = app.retry_garmin_workout_sync("quality_session", "tester")

            self.assertTrue(ok)
            self.assertFalse(stale_upload.exists())
            synced_payload = yaml.safe_load(Path(seen_command["workout_file"]).read_text(encoding="utf-8"))
            self.assertEqual(synced_payload["workout"]["schedule_date"], "2026-05-13")
            self.assertEqual(synced_payload["workout"]["sport"], "elliptical")
            self.assertEqual(synced_payload["workout"]["name"], "Series adaptadas")

    def test_apply_planned_workout_replan_triggers_garmin_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            replans_path = Path(tmp_dir) / "planned_workout_replans.json"
            workout = {
                "slug": "easy_run",
                "name": "Rodaje suave",
                "date": "2026-05-12",
                "description": "Rodaje base",
                "estimated_duration_s": 1800,
                "payload": {
                    "schedule_date": "2026-05-12",
                    "name": "Rodaje suave",
                    "description": "Rodaje base",
                    "estimated_duration_s": 1800,
                    "steps": [{"order": 1, "description": "30 min faciles"}],
                    "sport": "running",
                },
                "session_kind": "easy_run",
                "knowledge": {"label": "Aerobico", "primary_goal": "base"},
            }
            dashboard = {"decision": {}, "adaptation_triggers": {}, "protection_mode": {}}

            with (
                patch.object(app, "PLANNED_REPLANS_PATH", replans_path),
                patch.object(app, "set_planned_workout_action"),
                patch.object(app, "retry_garmin_workout_sync", return_value=(True, "Sesion reenviada a Garmin.")),
            ):
                replan_state = app.apply_planned_workout_replan("easy_run", workout, "auto_today", dashboard, "tester")

            self.assertTrue(replan_state["garmin_sync"]["ok"])
            stored_payload = json.loads(replans_path.read_text(encoding="utf-8"))
            self.assertEqual(
                stored_payload["workouts"]["easy_run"]["garmin_sync"]["message"],
                "Sesion reenviada a Garmin.",
            )


if __name__ == "__main__":
    unittest.main()
