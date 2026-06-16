from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scripts.telegram import opencode_bridge


class OpenCodeBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_unavailable_ignores_plain_timeout(self) -> None:
        self.assertFalse(
            opencode_bridge._is_provider_unavailable(
                124,
                "",
                "Command timed out after 25s. La tarea de OpenCode excedio el limite del bot.",
            )
        )
        self.assertTrue(opencode_bridge._is_provider_unavailable(1, "", "Gemini API error 429: quota exceeded"))

    async def test_attach_timeout_retries_locally_before_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_dir = Path(tmp_dir)
            config = opencode_bridge.OpenCodeRemoteConfig(
                enabled=True,
                server_url="http://127.0.0.1:4096",
                project_dir=project_dir,
                session_store=project_dir / "sessions.json",
                timeout_s=300,
                allow_commit=True,
                allow_push=True,
                dangerously_skip_permissions=False,
                model="openai/gpt-5.4",
                variant=None,
                max_response_chars=12000,
                local_retry_timeout_s=300,
                require_confirmation_patterns=(),
                gemini_fallback_enabled=True,
                gemini_api_key="key",
                gemini_models=("gemini-2.5-pro",),
            )
            bridge = opencode_bridge.OpenCodeBridge(config)
            calls: list[tuple[list[str], int]] = []

            async def fake_run_command(command: list[str], cwd: Path, timeout_s: int, on_started=None):
                self.assertEqual(cwd, project_dir)
                calls.append((command, timeout_s))
                if on_started is not None:
                    await on_started()
                if len(calls) == 1:
                    return 124, "", "Command timed out after 25s."
                return 0, "respuesta final", ""

            fallback = AsyncMock()

            with (
                patch.object(opencode_bridge, "run_command", side_effect=fake_run_command),
                patch.object(bridge.store, "get_session", return_value="ses_attach"),
                patch.object(bridge.store, "get_session_backend", return_value="attach"),
                patch.object(bridge.store, "get_model", return_value=None),
                patch.object(bridge, "discover_session_id", return_value="ses_local"),
                patch.object(bridge, "_try_gemini_fallback", fallback),
            ):
                result = await bridge.send(
                    "chat-1",
                    "mensaje",
                    health=opencode_bridge.BridgeHealth(ok=True, attach=True, user_message="ok", detail="", opencode_version="1"),
                )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.text, "respuesta final")
            self.assertEqual(len(calls), 2)
            self.assertIn("--attach", calls[0][0])
            self.assertNotIn("--attach", calls[1][0])
            self.assertIn("--title", calls[1][0])
            self.assertEqual(calls[0][1], 25)
            self.assertEqual(calls[1][1], 300)
            fallback.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
