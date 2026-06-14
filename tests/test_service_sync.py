from __future__ import annotations

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.system import service_sync


class ServiceSyncTests(unittest.TestCase):
    def test_skip_garmin_avoids_planned_sync_step(self) -> None:
        steps = []

        def fake_run_step(label: str, command: list[str], *, required: bool = True):
            steps.append(label)
            return {"label": label, "ok": True, "required": required}

        with (
            patch.object(service_sync, "run_step", side_effect=fake_run_step),
            patch.object(service_sync, "write_athlete_state_runtime", return_value={"generated_at": "a"}),
            patch.object(service_sync, "write_today_feed_runtime", return_value={"generated_at": "b"}),
            patch.object(service_sync, "write_automation_health_runtime", return_value={"generated_at": "c"}),
        ):
            payload = service_sync.service_sync("2026-06-14", skip_garmin=True)

        self.assertTrue(payload["ok"])
        self.assertEqual(steps, ["Coach sync"])


if __name__ == "__main__":
    unittest.main()
