#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "telegram" / "bot_config.yaml"


@dataclass(frozen=True)
class TelegramRuntimeConfig:
    bot_token: str
    chat_id: str
    caption_prefix: str
    allowed_chat_ids: tuple[str, ...]
    timezone: str
    morning_brief_time: str
    quiet_hours_start: str
    quiet_hours_end: str
    notifications_enabled: bool
    status_chat_ids: tuple[str, ...]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _clean_ids(items: Any, fallback: str) -> tuple[str, ...]:
    if not isinstance(items, list):
        items = [fallback]
    values = tuple(str(item).strip() for item in items if str(item).strip())
    return values or (fallback,)


def load_telegram_config(path: Path = DEFAULT_CONFIG_PATH) -> TelegramRuntimeConfig:
    data = load_yaml(path) if path.exists() else {}
    telegram = data.get("telegram", {}) if isinstance(data.get("telegram"), dict) else {}
    notifications = data.get("notifications", {}) if isinstance(data.get("notifications"), dict) else {}
    bot_token = str(os.getenv("TELEGRAM_BOT_TOKEN") or telegram.get("bot_token") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or telegram.get("chat_id") or "").strip()
    if not bot_token or not chat_id:
        raise ValueError("telegram.bot_token and telegram.chat_id are required")
    allowed_chat_ids = _clean_ids(telegram.get("allowed_chat_ids") or [chat_id], chat_id)
    status_chat_ids = _clean_ids(notifications.get("status_chat_ids") or list(allowed_chat_ids), chat_id)
    return TelegramRuntimeConfig(
        bot_token=bot_token,
        chat_id=chat_id,
        caption_prefix=str(telegram.get("caption_prefix") or "Running Coach").strip(),
        allowed_chat_ids=allowed_chat_ids,
        timezone=str(notifications.get("timezone") or "Europe/Madrid").strip(),
        morning_brief_time=str(notifications.get("morning_brief_time") or "07:30").strip(),
        quiet_hours_start=str(notifications.get("quiet_hours_start") or "23:00").strip(),
        quiet_hours_end=str(notifications.get("quiet_hours_end") or "07:00").strip(),
        notifications_enabled=bool(notifications.get("enabled", True)),
        status_chat_ids=status_chat_ids,
    )


def telegram_api_url(config: TelegramRuntimeConfig, method: str) -> str:
    return f"https://api.telegram.org/bot{config.bot_token}/{method}"


def telegram_request(config: TelegramRuntimeConfig, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = urllib.parse.urlencode({key: value for key, value in payload.items() if value is not None}).encode("utf-8")
    request = urllib.request.Request(telegram_api_url(config, method), data=data, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram API returned failure: {parsed}")
    return parsed


def send_text_message(text: str, *, chat_id: str | None = None, config: TelegramRuntimeConfig | None = None, disable_notification: bool = False) -> dict[str, Any]:
    runtime = config or load_telegram_config()
    if not runtime.notifications_enabled:
        return {"ok": True, "skipped": True, "reason": "notifications_disabled"}
    return telegram_request(
        runtime,
        "sendMessage",
        {
            "chat_id": chat_id or runtime.chat_id,
            "text": text.strip() or "(sin contenido)",
            "disable_notification": "true" if disable_notification else None,
        },
    )
