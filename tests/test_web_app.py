from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


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
            self.env = types.SimpleNamespace(filters={}, globals={})

    templating_module.Jinja2Templates = DummyTemplates
    sys.modules.setdefault("fastapi.templating", templating_module)

    sessions_module = types.ModuleType("starlette.middleware.sessions")
    sessions_module.SessionMiddleware = object
    sys.modules.setdefault("starlette.middleware.sessions", sessions_module)


_install_web_framework_stubs()

from scripts.web import app


class WebAppTests(unittest.TestCase):
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
                            "effective_sport": "fitness_equipment",
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
            self.assertEqual(synced_payload["workout"]["sport"], "fitness_equipment")
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
