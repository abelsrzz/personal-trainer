"""Thread-safe progress state for the planning pipeline.

Imported by the pipeline to report steps, and by the web app to expose
/api/plan/progress. No external dependencies.
"""
from __future__ import annotations

import threading
from datetime import datetime

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "step": 0,
    "total": 5,
    "label": "",
    "status": "idle",   # idle | running | done | error
    "message": "",
    "updated_at": "",
}

_TOTAL_STEPS = 5


def update(step: int, label: str, total: int = _TOTAL_STEPS) -> None:
    """Report that the pipeline has reached a new step."""
    with _lock:
        _state.update({
            "running": True,
            "step": step,
            "total": total,
            "label": label,
            "status": "running",
            "updated_at": datetime.now().isoformat(),
        })


def finish(ok: bool, message: str = "") -> None:
    """Mark the pipeline as done (ok) or failed (error)."""
    with _lock:
        _state.update({
            "running": False,
            "step": _state["total"] if ok else _state["step"],
            "label": message or ("Completado" if ok else "Error"),
            "status": "done" if ok else "error",
            "message": message,
            "updated_at": datetime.now().isoformat(),
        })


def reset() -> None:
    """Reset to idle — call before starting a new operation."""
    with _lock:
        _state.update({
            "running": False,
            "step": 0,
            "total": _TOTAL_STEPS,
            "label": "",
            "status": "idle",
            "message": "",
            "updated_at": "",
        })


def get() -> dict:
    """Return a snapshot of the current state."""
    with _lock:
        return dict(_state)
