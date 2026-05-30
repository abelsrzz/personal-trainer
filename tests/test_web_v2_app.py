from __future__ import annotations

import sys
import types
import unittest
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
    def test_legacy_url_normalizes_relative_paths(self) -> None:
        self.assertEqual(app.legacy_url("/calendar"), "http://127.0.0.1:8090/calendar")
        self.assertEqual(app.legacy_url("completed-workouts/demo"), "http://127.0.0.1:8090/completed-workouts/demo")

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
            unittest.mock.patch.object(app.legacy_app, "home_page_data", return_value=payload),
            unittest.mock.patch.object(app.legacy_app, "calendar_day_data", return_value={"planned_items": [{"slug": "2026-05-24_calentamiento_precarrera_ordes", "name": "Calentamiento pre-carrera Ordes", "session_kind_label": "Rodaje facil", "estimated_duration": "17:00"}], "completed_items": []}),
            unittest.mock.patch.object(app.legacy_app, "races_by_day", return_value={"2026-05-24": [{"name": "XXIX CARREIRA POPULAR CONCELLO DE ORDES"}]}),
            unittest.mock.patch.object(app.legacy_app, "completed_reviews", return_value=[{
                "slug": "2026-05-24_xxix_carreira_popular_concello_de_ordes",
                "date": "2026-05-24",
                "activity_name": "Ordes race",
                "session_kind": "race",
            }]),
            unittest.mock.patch.object(app.legacy_app, "review_matches_planned_workout", return_value=False),
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
            unittest.mock.patch.object(app.legacy_app, "home_page_data", return_value=payload),
            unittest.mock.patch.object(app.legacy_app, "calendar_day_data", return_value=day_payload),
            unittest.mock.patch.object(app.legacy_app, "races_by_day", return_value={"2026-05-24": [{"name": "Race event", "distance_km": "8.5k", "goal": "4:10-4:20/km"}]}),
            unittest.mock.patch.object(app.legacy_app, "completed_reviews", return_value=[]),
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
            unittest.mock.patch.object(app.legacy_app, "completed_review_detail", return_value=review),
            unittest.mock.patch.object(app.legacy_app, "garmin_feedback_metrics", return_value=[{"label": "Calorías", "value": "513 kcal"}]),
        ):
            page = app.completed_workout_page_data("race-review")
        self.assertEqual(page["review"]["slug"], "race-review")
        self.assertIsNone(page["review"]["payload"]["compliance"].get("duration_diff_s_vs_est"))
        self.assertEqual(page["review"]["garmin_feedback"][0]["label"], "Calorías")


if __name__ == "__main__":
    unittest.main()
