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

        def delete(self, *args, **kwargs):
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
    def test_humanize_ui_label_translates_internal_states(self) -> None:
        self.assertEqual(app.humanize_ui_label("hold_or_reduce"), "Mantener o reducir")
        self.assertEqual(app.clean_ui_text("`Bloque actual`"), "Bloque actual")

    def test_request_app_path_prefixes_proxy_root_path(self) -> None:
        request = types.SimpleNamespace(scope={"root_path": "/running"})
        self.assertEqual(app.request_root_path(request), "/running")
        self.assertEqual(app.request_app_path(request, "/calendar?month=2026-06"), "/running/calendar?month=2026-06")

    def test_request_app_path_keeps_root_route_without_double_slash(self) -> None:
        request = types.SimpleNamespace(scope={"root_path": "/running/"})
        self.assertEqual(app.request_app_path(request, "/"), "/running")
        self.assertEqual(app.request_app_path(request, "/login"), "/running/login")

    def test_normalize_plan_progress_hides_stale_terminal_state(self) -> None:
        old = (app.datetime.now() - app.timedelta(seconds=30)).isoformat()
        payload = app.normalize_plan_progress({"running": False, "step": 5, "total": 5, "label": "Plan generado", "status": "done", "message": "ok", "updated_at": old})
        self.assertEqual(payload["status"], "idle")
        self.assertFalse(payload["running"])

    def test_normalize_plan_progress_keeps_fresh_done_state(self) -> None:
        now = app.datetime.now().isoformat()
        payload = app.normalize_plan_progress({"running": False, "step": 5, "total": 5, "label": "Plan generado", "status": "done", "message": "ok", "updated_at": now})
        self.assertEqual(payload["status"], "done")

    def test_aerobic_target_hr_values_derive_from_z2_band(self) -> None:
        with mock.patch.object(app.portal_core, "load_yaml", return_value={"zones": {"heart_rate": {"z2": "145-160"}}}):
            self.assertEqual(app.aerobic_target_hr_values(), [145, 153, 160])

    def test_build_aerobic_trend_chart_returns_series_for_recent_weeks(self) -> None:
        activities = [
            {"date": app.portal_core.date(2026, 5, 5), "distance_km": 8.2, "duration_s": 3013, "pace_s_per_km": 367.4, "avg_hr": 145.0},
            {"date": app.portal_core.date(2026, 5, 8), "distance_km": 9.0, "duration_s": 3240, "pace_s_per_km": 360.0, "avg_hr": 147.0},
            {"date": app.portal_core.date(2026, 5, 15), "distance_km": 10.0, "duration_s": 3540, "pace_s_per_km": 354.0, "avg_hr": 150.0},
            {"date": app.portal_core.date(2026, 5, 22), "distance_km": 9.4, "duration_s": 3271, "pace_s_per_km": 348.0, "avg_hr": 153.0},
            {"date": app.portal_core.date(2026, 5, 29), "distance_km": 10.1, "duration_s": 3444, "pace_s_per_km": 341.0, "avg_hr": 156.0},
            {"date": app.portal_core.date(2026, 6, 5), "distance_km": 11.2, "duration_s": 3729, "pace_s_per_km": 333.0, "avg_hr": 159.0},
        ]
        with (
            mock.patch.object(app.portal_core, "running_activity_summaries", return_value=activities),
            mock.patch.object(app.portal_core, "load_yaml", return_value={"zones": {"heart_rate": {"z2": "145-160"}}}),
        ):
            chart = app.build_aerobic_trend_chart()

        self.assertIsNotNone(chart)
        self.assertEqual(chart["target_hrs"], [145, 153, 160])
        self.assertEqual(len(chart["series"]), 3)
        self.assertTrue(chart["series"][0]["points"])
        self.assertIn("6 semanas", chart["subtitle"])

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
            mock.patch.object(app, "load_today_feed", return_value=None),
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
            mock.patch.object(app, "load_today_feed", return_value=None),
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

    def test_completed_workout_page_data_supports_imported_garmin_slug(self) -> None:
        imported = {
            "slug": "garmin-import-23201148301",
            "name": "Ordes Caminar",
            "payload": {"summary": {}},
            "garmin_activity_id": 23201148301,
            "recovery_analysis": None,
        }
        with (
            mock.patch.object(app.portal_core, "completed_review_detail", return_value=None),
            mock.patch.object(app.portal_core, "imported_garmin_activity_detail", return_value=imported),
            mock.patch.object(app.portal_core, "garmin_feedback_metrics", return_value=[{"label": "Pasos", "value": "5458"}]),
        ):
            page = app.completed_workout_page_data("garmin-import-23201148301")
        self.assertEqual(page["review"]["slug"], "garmin-import-23201148301")
        self.assertEqual(page["review"]["garmin_feedback"][0]["label"], "Pasos")

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

    def test_plan_page_data_exposes_aerobic_trend_chart(self) -> None:
        cycle_payload = {
            "dashboard": {"decision": {}, "goal_gates": {}, "athlete_state": {}},
            "master_plan": {"blocks": []},
            "current_block": None,
        }
        with (
            mock.patch.object(app.portal_core, "planned_workouts", return_value=[]),
            mock.patch.object(app.portal_core, "completed_reviews", return_value=[]),
            mock.patch.object(app.portal_core, "cycle_page_data", return_value=cycle_payload),
            mock.patch.object(app.portal_core, "week_page_data", return_value={"rows": [], "executive_summary": None}),
            mock.patch.object(app, "build_aerobic_trend_chart", return_value={"target_hrs": [145, 153, 160], "series": []}),
        ):
            payload = app.plan_page_data()
        self.assertEqual(payload["aerobic_trend_chart"]["target_hrs"], [145, 153, 160])

    def test_calendar_page_data_exposes_range_forms(self) -> None:
        calendar_payload = {
            "selected": "2026-06",
            "selected_label": "Junio 2026",
            "prev_month": "2026-05",
            "next_month": "2026-07",
            "weeks": [[
                {"date": "2026-06-01", "day": 1, "in_month": True, "is_today": False, "events": []},
                {"date": "2026-06-30", "day": 30, "in_month": True, "is_today": False, "events": []},
            ]],
        }
        with mock.patch.object(app.portal_core, "calendar_month_data_combined", return_value=calendar_payload):
            page = app.calendar_page_data("2026-06")
        self.assertEqual(page["plan_range_form"]["start_date"], "2026-06-01")
        self.assertEqual(page["replan_range_form"]["end_date"], "2026-06-30")
        self.assertEqual(page["plan_range_form"]["return_to"], "/calendar?month=2026-06&focus=all")

    def test_planned_workout_page_data_exposes_replan_form(self) -> None:
        workout = {
            "slug": "2026-06-17_quality",
            "name": "Calidad",
            "linked_review": None,
        }
        with mock.patch.object(app.portal_core, "planned_workout_detail", return_value=workout):
            page = app.planned_workout_page_data("2026-06-17_quality")
        self.assertEqual(page["replan_form"]["slug"], "2026-06-17_quality")
        self.assertEqual(page["replan_form"]["return_to"], "/planned-workouts/2026-06-17_quality")

    def test_athlete_page_data_exposes_zones_for_ui(self) -> None:
        athlete_payload = {
            "profile": {"name": "A", "age": 1, "city": "C", "availability": {"days_per_week": 4}},
            "health": {},
            "shoes": [],
            "impact_return": {},
            "hybrid_training": {},
            "training_paces": {},
            "coach_permissions": {},
            "replanning": {},
        }
        with (
            mock.patch.object(app.portal_core, "athlete_page_data", return_value=athlete_payload),
            mock.patch.object(app.portal_core, "fueling_page_data", return_value={"supplements": [], "generated_at": None}),
            mock.patch.object(app.portal_core, "load_optional_yaml", return_value={"zones": {"heart_rate": {"z2": "145-160"}}}),
        ):
            payload = app.athlete_page_data()
        self.assertEqual(payload["zones"]["heart_rate"]["z2"], "145-160")

    def test_compose_chat_message_embeds_selected_session_context(self) -> None:
        with mock.patch.object(
            app,
            "selected_chat_context",
            return_value=([{"id": "review:test", "label": "2026-06-10 · Rodaje", "meta": "Review"}], "Sesiones previas seleccionadas:\n- 2026-06-10 | Rodaje"),
        ):
            message, selected = app.compose_chat_message("ajusta manana", ["review:test"])
        self.assertIn("Sesiones previas seleccionadas", message)
        self.assertIn("Peticion actual del usuario", message)
        self.assertEqual(selected[0]["id"], "review:test")

    def test_update_bot_settings_preserves_existing_gemini_key_when_blank(self) -> None:
        existing = {
            "telegram": {"bot_token": "abc", "chat_id": "1", "caption_prefix": "Running Coach"},
            "opencode_remote": {"gemini_fallback": {"enabled": True, "api_key": "secret", "models": ["gemini-2.5-pro"]}},
        }
        captured = {}

        def fake_write(_path, payload):
            captured["payload"] = payload

        with (
            mock.patch.object(app, "load_bot_settings", return_value=existing),
            mock.patch.object(app.portal_core, "write_yaml", side_effect=fake_write),
        ):
            app.update_bot_settings(
                {
                    "telegram_bot_token": "",
                    "telegram_chat_id": "2",
                    "telegram_caption_prefix": "Coach",
                    "telegram_allowed_chat_ids": "2,3",
                    "opencode_enabled": "1",
                    "opencode_server_url": "http://127.0.0.1:4096",
                    "opencode_timeout_s": "3600",
                    "opencode_allow_commit": "1",
                    "opencode_allow_push": "0",
                    "opencode_dangerously_skip_permissions": "0",
                    "opencode_model": "openai/gpt-5.4",
                    "opencode_max_response_chars": "12000",
                    "opencode_require_confirmation_patterns": "rm -rf",
                    "gemini_enabled": "1",
                    "gemini_api_key": "",
                    "gemini_models": "gemini-2.5-pro, gemini-2.5-flash",
                }
            )

        payload = captured["payload"]
        self.assertEqual(payload["telegram"]["chat_id"], "2")
        self.assertEqual(payload["telegram"]["allowed_chat_ids"], ["2", "3"])
        self.assertEqual(payload["opencode_remote"]["gemini_fallback"]["api_key"], "secret")
        self.assertEqual(payload["opencode_remote"]["gemini_fallback"]["models"], ["gemini-2.5-pro", "gemini-2.5-flash"])


if __name__ == "__main__":
    unittest.main()
