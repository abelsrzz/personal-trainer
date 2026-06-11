from __future__ import annotations

import sys
import types
import unittest
from unittest import mock
from pathlib import Path


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

        def on_event(self, *args, **kwargs):
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
            self.env = types.SimpleNamespace(filters={})

    templating_module.Jinja2Templates = DummyTemplates
    sys.modules.setdefault("fastapi.templating", templating_module)

    sessions_module = types.ModuleType("starlette.middleware.sessions")
    sessions_module.SessionMiddleware = object
    sys.modules.setdefault("starlette.middleware.sessions", sessions_module)


_install_web_framework_stubs()

from scripts.web_v2 import app


class WebV2Tests(unittest.TestCase):
    def test_home_page_prioritizes_race_review_when_race_exists(self) -> None:
        payload = {
            "today_plan": {
                "date": "2026-05-24",
                "why_today": "Race day",
                "planned_workout": {
                    "slug": "2026-05-24_calentamiento_precarrera_ordes",
                    "name": "Calentamiento pre-carrera Ordes",
                },
                "completed_review": {
                    "slug": "2026-05-24_xxix_carreira_popular_concello_de_ordes",
                    "activity_name": "Ordes race",
                    "session_kind": "race",
                },
            },
            "dashboard": {},
            "workspace": {},
            "active_cycle": {},
            "upcoming": [],
            "recent_reviews": [],
        }

        with (
            mock.patch.object(app.portal_core, "home_page_data", return_value=payload),
            mock.patch.object(app.portal_core, "calendar_day_data", return_value={"planned_items": [{"slug": "2026-05-24_calentamiento_precarrera_ordes", "name": "Calentamiento pre-carrera Ordes", "session_kind_label": "Rodaje facil", "estimated_duration": "17:00"}], "completed_items": []}),
            mock.patch.object(app.portal_core, "races_by_day", return_value={"2026-05-24": [{"name": "XXIX CARREIRA POPULAR CONCELLO DE ORDES"}]}),
            mock.patch.object(app.portal_core, "completed_reviews", return_value=[{
                "slug": "2026-05-24_xxix_carreira_popular_concello_de_ordes",
                "date": "2026-05-24",
                "activity_name": "Ordes race",
                "session_kind": "race",
            }]),
            mock.patch.object(app.portal_core, "review_matches_planned_workout", return_value=False),
        ):
            data = app.home_page_data()

        self.assertEqual(data["today_workout"]["slug"], "2026-05-24_calentamiento_precarrera_ordes")
        self.assertEqual(data["today_review"]["slug"], "2026-05-24_xxix_carreira_popular_concello_de_ordes")
        self.assertEqual(data["today_reviews"][0]["slug"], "2026-05-24_xxix_carreira_popular_concello_de_ordes")
        self.assertEqual(len(data["today_workouts"]), 2)

    def test_home_page_exposes_multiple_today_workouts_and_reviews(self) -> None:
        payload = {
            "today_plan": {
                "date": "2026-05-24",
                "why_today": "Double session",
                "watchouts": [],
                "priorities": [],
            },
            "dashboard": {},
            "workspace": {},
            "active_cycle": {},
            "upcoming": [],
            "recent_reviews": [],
        }
        day_payload = {
            "planned_items": [
                {"slug": "warmup", "name": "Warmup", "session_kind_label": "Rodaje", "estimated_duration": "17:00"},
            ],
            "completed_items": [
                {"slug": "warmup", "activity_name": "Warmup done", "distance_km": 2.4, "duration": "17:38", "pace": "7:16/km", "traffic_light": "amarillo"},
                {"slug": "race", "activity_name": "Race done", "distance_km": 8.45, "duration": "39:37", "pace": "4:41/km", "traffic_light": "amarillo"},
            ],
        }

        with (
            mock.patch.object(app.portal_core, "home_page_data", return_value=payload),
            mock.patch.object(app.portal_core, "calendar_day_data", return_value=day_payload),
            mock.patch.object(app.portal_core, "races_by_day", return_value={"2026-05-24": [{"name": "Race event", "distance_km": "8.5k", "goal": "4:10-4:20/km"}]}),
            mock.patch.object(app.portal_core, "completed_reviews", return_value=[]),
        ):
            data = app.home_page_data()

        self.assertEqual(len(data["today_workouts"]), 2)
        self.assertEqual(len(data["today_reviews"]), 2)
        self.assertEqual(data["today_workouts"][0]["slug"], "warmup")
        self.assertEqual(data["today_workouts"][1]["slug"], "race-2026-05-24")
        self.assertEqual(data["today_reviews"][1]["slug"], "race")

    def test_completed_workout_page_data_supports_sparse_race_review_payload(self) -> None:
        review = {
            "slug": "race-review",
            "name": "Race review",
            "feedback_summary": None,
            "compliance_note": "Race summary",
            "date": "2026-05-24",
            "distance_km": 8.45,
            "duration": "39:37",
            "pace": "4:41/km",
            "score": 7,
            "risk_level": "alto",
            "avg_hr": 191,
            "garmin_activity_url": None,
            "feedback_locked": False,
            "feedback_form": {"rpe": "-", "pain_level": "-", "compliance_options": {}, "compliance": "-", "time_feeling_options": {}, "time_feeling": None, "pain_location": None, "note": None},
            "traffic_light": "amarillo",
            "automated_review_summary": "Auto",
            "payload": {"compliance": {"pct_in_hr_zone": 0.0}, "progression": {"summary": "Informative", "trend": "informative"}},
        }
        with (
            mock.patch.object(app.portal_core, "completed_review_detail", return_value=review),
            mock.patch.object(app.portal_core, "garmin_feedback_metrics", return_value=[{"label": "Calorías", "value": "513 kcal"}]),
        ):
            page = app.completed_workout_page_data("race-review")
        self.assertEqual(page["review"]["slug"], "race-review")
        self.assertIsNone(page["review"]["payload"]["compliance"].get("duration_diff_s_vs_est"))
        self.assertEqual(page["review"]["garmin_feedback"][0]["label"], "Calorías")

    def test_start_garmin_auto_sync_respects_disabled_flag(self) -> None:
        with mock.patch.object(app, "GARMIN_AUTO_SYNC_ENABLED", False), mock.patch("threading.Thread") as thread_mock:
            app._garmin_auto_sync_started = False
            app.start_garmin_auto_sync()
        thread_mock.assert_not_called()

    def test_garmin_sync_status_text_formats_finished_state(self) -> None:
        message = app.garmin_sync_status_text(
            {
                "running": False,
                "last_ok": True,
                "last_finished_at": "2026-06-11T10:00:00",
                "last_message": "Sincronizacion Garmin bidireccional completada.",
            }
        )
        self.assertEqual(message, "Sincronizacion Garmin bidireccional completada. (OK)")

    def test_launch_garmin_bidirectional_sync_starts_background_thread(self) -> None:
        app._garmin_sync_state["running"] = False
        with mock.patch("threading.Thread") as thread_mock:
            thread_instance = thread_mock.return_value
            ok, message = app.launch_garmin_bidirectional_sync("manual")
        self.assertTrue(ok)
        self.assertEqual(message, "Sincronizacion Garmin lanzada en segundo plano.")
        thread_mock.assert_called_once()
        thread_instance.start.assert_called_once()

    def test_run_garmin_bidirectional_sync_runs_expected_steps(self) -> None:
        responses = [(True, "ok")] * 7
        with mock.patch.object(app, "run_project_command", side_effect=responses) as run_mock:
            app._garmin_sync_state.update({"running": False, "last_ok": None, "last_message": None})
            ok, message = app.run_garmin_bidirectional_sync("manual")
        self.assertTrue(ok)
        self.assertEqual(message, "Sincronizacion Garmin bidireccional completada.")
        self.assertEqual(run_mock.call_count, 7)
        first_command = run_mock.call_args_list[0].args[0]
        self.assertEqual(first_command[1], str(app.GARMIN_SYNC_SCRIPT))
        self.assertEqual(first_command[2], "import-activities")
        self.assertEqual(first_command[-2:], ["--activity-type", app.GARMIN_SYNC_ACTIVITY_TYPE])
        refresh_command = run_mock.call_args_list[5].args[0]
        self.assertIn("--skip-activity-import", refresh_command)
        self.assertTrue(app._garmin_sync_state["last_ok"])


if __name__ == "__main__":
    unittest.main()
