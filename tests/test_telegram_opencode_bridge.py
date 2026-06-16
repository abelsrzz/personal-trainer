from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_SCRIPTS = ROOT / "scripts" / "telegram"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TELEGRAM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(TELEGRAM_SCRIPTS))

from scripts.telegram.opencode_bridge import DEFAULT_LOCAL_RETRY_TIMEOUT_S, load_config, sanitized_config


class TelegramOpenCodeBridgeTests(unittest.TestCase):
    def test_load_config_exposes_bounded_local_retry_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "bot_config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token": "token", "chat_id": "1"},
                        "opencode_remote": {"project_dir": str(ROOT), "local_retry_timeout_s": 45},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.opencode.local_retry_timeout_s, 45)
        self.assertEqual(sanitized_config(config)["opencode_remote"]["local_retry_timeout_s"], 45)

    def test_load_config_uses_safe_default_local_retry_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "bot_config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token": "token", "chat_id": "1"},
                        "opencode_remote": {"project_dir": str(ROOT)},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                config = load_config(config_path)

        self.assertEqual(config.opencode.local_retry_timeout_s, DEFAULT_LOCAL_RETRY_TIMEOUT_S)

    def test_load_config_defaults_to_non_interactive_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "bot_config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "telegram": {"bot_token": "token", "chat_id": "1"},
                        "opencode_remote": {"project_dir": str(ROOT)},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            with patch.dict("os.environ", {}, clear=True):
                config = load_config(config_path)

        self.assertTrue(config.opencode.dangerously_skip_permissions)
        self.assertTrue(sanitized_config(config)["opencode_remote"]["dangerously_skip_permissions"])


if __name__ == "__main__":
    unittest.main()
