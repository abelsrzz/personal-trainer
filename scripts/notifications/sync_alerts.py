#!/usr/bin/env python3
"""Throttled Telegram alerts for Garmin sync health.

The automatic refresh daemon runs silently every few minutes. When Garmin auth
expires or sync stops completing, nothing surfaced before and the coach would
quietly run on stale data for days. These helpers raise a loud (but throttled)
Telegram alert so the issue is noticed and the athlete can re-authenticate.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.notifications.telegram_utils import send_text_message
except ModuleNotFoundError:  # pragma: no cover - direct script execution path fix
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.notifications.telegram_utils import send_text_message


ROOT = Path(__file__).resolve().parents[2]
ALERT_STATE_PATH = ROOT / "system" / "state" / "sync_alert_state.json"

logger = logging.getLogger("garmin.alerts")

_AUTH_ERROR_MARKERS = (
    "token file not found",
    "garmin_mfa_code",
    "mfa",
    "unauthorized",
    "forbidden",
    "401",
    "403",
    "invalid credentials",
    "authentication",
)


def looks_like_auth_error(text: str | None) -> bool:
    """True when an error message points at expired/missing Garmin auth."""
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in _AUTH_ERROR_MARKERS)


def _load_state() -> dict:
    if not ALERT_STATE_PATH.exists():
        return {}
    try:
        return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - corrupt state should not block alerting
        return {}


def _save_state(state: dict) -> None:
    ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def send_throttled_alert(key: str, message: str, *, min_interval_hours: float = 6.0) -> bool:
    """Send a Telegram alert at most once per ``min_interval_hours`` per ``key``.

    Returns True if a message was actually sent.
    """
    state = _load_state()
    now = datetime.now(timezone.utc)
    last = state.get(key)
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).total_seconds() < min_interval_hours * 3600:
                return False
        except ValueError:
            pass
    try:
        send_text_message(message)
    except Exception as exc:  # noqa: BLE001 - alerting must never crash the caller
        logger.warning("Failed to send sync alert %s: %s", key, exc)
        return False
    state[key] = now.isoformat()
    _save_state(state)
    return True


def notify_token_problem(error: str | None) -> bool:
    return send_throttled_alert(
        "garmin_token",
        "⚠️ Sincronización Garmin bloqueada: token expirado o ausente. "
        "Re-autentica con `GARMIN_MFA_CODE=<codigo> python3 scripts/garmin/sync_garmin.py import-activities --days 1 --limit 1`.\n"
        f"Detalle: {str(error or '').strip()[:300]}",
    )


def notify_sync_gap(gap_hours: float) -> bool:
    return send_throttled_alert(
        "garmin_gap",
        f"⚠️ La sincronización con Garmin no se completa desde hace {gap_hours:.0f} h. "
        "El coach puede estar usando datos viejos; revisa el daemon y la conexión.",
    )
