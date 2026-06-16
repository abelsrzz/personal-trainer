#!/usr/bin/env python3
"""Import / reconcile file-backed structured runtime data into PostgreSQL.

Idempotent and checksum-aware: safe to run as the compose ``migrate`` one-shot,
on a timer to pick up opencode/agent file edits, and as the one-time server
cutover importer.

Scope is structured runtime data only. Garmin raw imports
(``training/completed/imports/garmin/**``) and static knowledge files stay
file-only by design and are never imported here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from psycopg import Connection
from psycopg.types.json import Jsonb

try:
    from scripts.storage.db import connection, sql_enabled, wait_for_database
    from scripts.storage.schema import ensure_schema
except ModuleNotFoundError:  # pragma: no cover - direct execution
    sys.path.append(str(Path(__file__).resolve().parents[2]))
    from scripts.storage.db import connection, sql_enabled, wait_for_database
    from scripts.storage.schema import ensure_schema


ROOT = Path(__file__).resolve().parents[2]

# Directory roots scanned recursively for structured runtime files.
SCAN_ROOTS = [
    "athlete",
    "races",
    "training/planned/workouts",
    "training/completed/activities",
    "training/completed/reviews",
    "training/completed/feedback",
    "system/state",
]
# Individual runtime files outside the scanned roots that the web app reads.
EXTRA_FILES = [
    "planning/coach_decision.json",
    "planning/cycles/active.yaml",
]

TEXT_SUFFIXES = {".yaml", ".yml", ".json", ".md"}
# Static templates / knowledge that live under runtime roots but are not data.
SKIP_NAMES = {
    "library_run_templates.yaml",
    "workout_template.yaml",
    "activity_template.yaml",
    "review_template.md",
}
SKIP_SUFFIXES = {".example", ".pdf", ".pyc", ".pyo", ".log", ".lock"}
SKIP_DIRS = {".git", ".venv", ".pytest_cache", "__pycache__", "imports"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write to PostgreSQL. Without it, prints a dry-run summary.")
    parser.add_argument("--validate", action="store_true", help="Validate row coverage after applying.")
    parser.add_argument("--prune", action="store_true", help="Delete DB rows whose source file no longer exists.")
    parser.add_argument("--db-timeout", type=int, default=60, help="Seconds to wait for PostgreSQL.")
    return parser.parse_args()


def rel_path(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def should_skip(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return True
    if path.name in SKIP_NAMES:
        return True
    if path.suffix not in TEXT_SUFFIXES:
        return True
    if any(path.name.endswith(suffix) for suffix in SKIP_SUFFIXES):
        return True
    return False


def candidate_paths() -> list[Path]:
    paths: list[Path] = []
    for root_name in SCAN_ROOTS:
        root = ROOT / root_name
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and not should_skip(path):
                    paths.append(path)
    for file_name in EXTRA_FILES:
        path = ROOT / file_name
        if path.is_file() and not should_skip(path):
            paths.append(path)
    return sorted(set(paths))


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_kind(path: Path) -> str:
    if path.suffix in {".yaml", ".yml"}:
        return "yaml"
    if path.suffix == ".json":
        return "json"
    if path.suffix == ".md":
        return "markdown"
    return "text"


def load_payload(path: Path) -> Any:
    if path.suffix in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def parse_iso_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def json_ready(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def as_jsonb(value: Any) -> Jsonb:
    return Jsonb(json_ready(value))


# --- upserts ---------------------------------------------------------------

def upsert_artifact(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    content_text = path.read_text(encoding="utf-8") if path.suffix == ".md" else None
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO artifacts(path, kind, payload, content_text, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE SET
                kind = EXCLUDED.kind, payload = EXCLUDED.payload,
                content_text = EXCLUDED.content_text, checksum = EXCLUDED.checksum,
                updated_at = now()
            """,
            (rel_path(path), artifact_kind(path), as_jsonb(payload) if payload is not None else None, content_text, digest),
        )


def upsert_athlete_document(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    if path.suffix not in {".yaml", ".yml"}:
        return
    key = rel_path(path).removeprefix("athlete/").removesuffix(path.suffix)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO athlete_documents(key, source_path, payload, checksum)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET
                source_path = EXCLUDED.source_path, payload = EXCLUDED.payload,
                checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (key, rel_path(path), as_jsonb(payload), digest),
        )


def upsert_race(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    race = payload.get("race", payload) if isinstance(payload, dict) else {}
    if not isinstance(race, dict):
        return
    race_id = text_or_none(race.get("id")) or path.stem
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO races(id, source_path, name, race_date, priority, payload, checksum)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                source_path = EXCLUDED.source_path, name = EXCLUDED.name,
                race_date = EXCLUDED.race_date, priority = EXCLUDED.priority,
                payload = EXCLUDED.payload, checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (race_id, rel_path(path), text_or_none(race.get("name")), parse_iso_date(race.get("date")),
             text_or_none(race.get("priority")), as_jsonb(race), digest),
        )


def upsert_planned_workout(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    workout = payload.get("workout") if isinstance(payload, dict) else None
    if not isinstance(workout, dict):
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO planned_workouts(slug, source_path, schedule_date, sport, name, payload, checksum)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                source_path = EXCLUDED.source_path, schedule_date = EXCLUDED.schedule_date,
                sport = EXCLUDED.sport, name = EXCLUDED.name, payload = EXCLUDED.payload,
                checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (path.stem, rel_path(path),
             parse_iso_date(workout.get("schedule_date") or workout.get("date")),
             text_or_none(workout.get("sport") or workout.get("type")),
             text_or_none(workout.get("name") or workout.get("title")),
             as_jsonb(workout), digest),
        )


def upsert_completed_activity(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    activity = payload.get("activity") if isinstance(payload, dict) else None
    if not isinstance(activity, dict):
        return
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completed_activities(slug, source_path, activity_id, garmin_activity_id,
                activity_date, title, activity_type, payload, checksum)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                source_path = EXCLUDED.source_path, activity_id = EXCLUDED.activity_id,
                garmin_activity_id = EXCLUDED.garmin_activity_id, activity_date = EXCLUDED.activity_date,
                title = EXCLUDED.title, activity_type = EXCLUDED.activity_type,
                payload = EXCLUDED.payload, checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (path.stem, rel_path(path), text_or_none(activity.get("id")),
             int_or_none(activity.get("garmin_activity_id")), parse_iso_date(activity.get("date")),
             text_or_none(activity.get("title")), text_or_none(activity.get("type")),
             as_jsonb(activity), digest),
        )


def upsert_completed_review(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    if not isinstance(payload, dict):
        return
    slug = path.stem.removesuffix(".analysis")
    planned = payload.get("planned") if isinstance(payload.get("planned"), dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    markdown_path = path.with_name(f"{slug}.md")
    review_markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else None
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completed_reviews(slug, source_path, review_date, activity_name,
                garmin_activity_id, analysis, review_markdown, checksum)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                source_path = EXCLUDED.source_path, review_date = EXCLUDED.review_date,
                activity_name = EXCLUDED.activity_name, garmin_activity_id = EXCLUDED.garmin_activity_id,
                analysis = EXCLUDED.analysis, review_markdown = EXCLUDED.review_markdown,
                checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (slug, rel_path(path), parse_iso_date(planned.get("date") or payload.get("date")),
             text_or_none(summary.get("activity_name") or planned.get("name")),
             int_or_none(summary.get("activity_id") or payload.get("garmin_activity_id")),
             as_jsonb(payload), review_markdown, digest),
        )


def upsert_completed_feedback(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    if not isinstance(payload, dict):
        return
    slug = path.name.removesuffix(".feedback.json")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completed_feedback(slug, source_path, feedback_date, payload, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                source_path = EXCLUDED.source_path, feedback_date = EXCLUDED.feedback_date,
                payload = EXCLUDED.payload, checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (slug, rel_path(path), parse_iso_date(payload.get("date")), as_jsonb(payload), digest),
        )


def upsert_state_collection(conn: Connection, table: str, key_field: str, items: dict[str, Any]) -> None:
    if not isinstance(items, dict):
        return
    with conn.cursor() as cursor:
        for key, payload in items.items():
            if not isinstance(payload, dict):
                continue
            cursor.execute(
                f"""
                INSERT INTO {table}({key_field}, payload)
                VALUES (%s, %s)
                ON CONFLICT ({key_field}) DO UPDATE SET
                    payload = EXCLUDED.payload, updated_at = now()
                """,
                (key, as_jsonb(payload)),
            )


def upsert_system_state(conn: Connection, path: Path, payload: Any, digest: str) -> None:
    if not isinstance(payload, dict):
        return
    key = rel_path(path).removeprefix("system/state/").removesuffix(".json")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO system_state(key, source_path, payload, checksum)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET
                source_path = EXCLUDED.source_path, payload = EXCLUDED.payload,
                checksum = EXCLUDED.checksum, updated_at = now()
            """,
            (key, rel_path(path), as_jsonb(payload), digest),
        )


# --- classification / routing ---------------------------------------------

def classify_expected(path: Path, payload: Any) -> list[str]:
    rel = rel_path(path)
    tables = ["artifacts"]
    if rel.startswith("athlete/") and path.suffix in {".yaml", ".yml"}:
        tables.append("athlete_documents")
    if rel.startswith("races/") and path.suffix in {".yaml", ".yml"}:
        tables.append("races")
    if rel.startswith("training/planned/workouts/") and path.suffix in {".yaml", ".yml"}:
        tables.append("planned_workouts")
    if rel.startswith("training/completed/activities/") and path.suffix in {".yaml", ".yml"}:
        tables.append("completed_activities")
    if rel.startswith("training/completed/reviews/") and path.name.endswith(".analysis.json"):
        tables.append("completed_reviews")
    if rel.startswith("training/completed/feedback/") and path.name.endswith(".feedback.json"):
        tables.append("completed_feedback")
    if rel.startswith("system/state/") and path.suffix == ".json" and isinstance(payload, dict):
        tables.append("system_state")
    return tables


def import_path(conn: Connection, path: Path, expected: dict[str, list[str]]) -> None:
    payload = load_payload(path)
    digest = checksum(path)
    rel = rel_path(path)
    upsert_artifact(conn, path, payload, digest)
    for table in classify_expected(path, payload):
        expected[table].append(rel)

    if rel.startswith("athlete/"):
        upsert_athlete_document(conn, path, payload, digest)
    elif rel.startswith("races/"):
        upsert_race(conn, path, payload, digest)
    elif rel.startswith("training/planned/workouts/"):
        upsert_planned_workout(conn, path, payload, digest)
    elif rel.startswith("training/completed/activities/"):
        upsert_completed_activity(conn, path, payload, digest)
    elif rel.startswith("training/completed/reviews/") and path.name.endswith(".analysis.json"):
        upsert_completed_review(conn, path, payload, digest)
    elif rel.startswith("training/completed/feedback/") and path.name.endswith(".feedback.json"):
        upsert_completed_feedback(conn, path, payload, digest)
    elif rel == "system/state/planned_workout_actions.json" and isinstance(payload, dict):
        upsert_state_collection(conn, "planned_workout_actions", "slug", payload.get("workouts") or {})
        upsert_system_state(conn, path, payload, digest)
    elif rel == "system/state/planned_workout_replans.json" and isinstance(payload, dict):
        upsert_state_collection(conn, "planned_workout_replans", "slug", payload.get("workouts") or {})
        upsert_system_state(conn, path, payload, digest)
    elif rel == "system/state/daily_checkins.json" and isinstance(payload, dict):
        upsert_state_collection(conn, "daily_checkins", "day", payload.get("days") or {})
        upsert_system_state(conn, path, payload, digest)
    elif rel.startswith("system/state/") and path.suffix == ".json":
        upsert_system_state(conn, path, payload, digest)


# --- live dual-write hooks (called from legacy_support writers) ------------

_SPECIALIZED_TABLES = (
    "athlete_documents", "races", "planned_workouts", "completed_activities",
    "completed_reviews", "completed_feedback", "system_state",
)
_SCHEMA_READY = False


def _in_scope(rel: str) -> bool:
    if rel in EXTRA_FILES:
        return True
    return any(rel == root or rel.startswith(root + "/") for root in SCAN_ROOTS)


def _resolve(abs_path: Any) -> Path | None:
    path = Path(abs_path)
    if not path.is_absolute():
        path = ROOT / path
    try:
        path = path.resolve()
        path.relative_to(ROOT)
    except (ValueError, OSError):
        return None
    return path


def mirror_file(abs_path: Any) -> None:
    """Write-through one structured file into the DB (no-op unless SQL backend)."""
    global _SCHEMA_READY
    if not sql_enabled():
        return
    path = _resolve(abs_path)
    if path is None or not path.is_file() or should_skip(path):
        return
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    if not _in_scope(rel):
        return
    with connection() as conn:
        if not _SCHEMA_READY:
            ensure_schema(conn)
            _SCHEMA_READY = True
        import_path(conn, path, defaultdict(list))


def mirror_delete(abs_path: Any) -> None:
    """Drop a structured file's rows from the DB (no-op unless SQL backend)."""
    if not sql_enabled():
        return
    path = _resolve(abs_path)
    if path is None:
        return
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    if not _in_scope(rel):
        return
    with connection() as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM artifacts WHERE path = %s", (rel,))
        for table in _SPECIALIZED_TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE source_path = %s", (rel,))
        conn.commit()


def prune_missing(conn: Connection, present_paths: set[str]) -> dict[str, int]:
    """Delete DB rows whose source file no longer exists (handles agent/web deletes)."""
    removed: dict[str, int] = {}
    with conn.cursor() as cursor:
        cursor.execute("SELECT path FROM artifacts")
        stale = [row[0] for row in cursor.fetchall() if row[0] not in present_paths]
        if stale:
            cursor.execute("DELETE FROM artifacts WHERE path = ANY(%s)", (stale,))
            removed["artifacts"] = len(stale)
            for table in _SPECIALIZED_TABLES:
                cursor.execute(f"DELETE FROM {table} WHERE source_path = ANY(%s)", (stale,))
    conn.commit()
    return removed


def dry_run_summary(paths: list[Path]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for path in paths:
        try:
            payload = load_payload(path)
        except (OSError, json.JSONDecodeError, yaml.YAMLError):
            counts["unreadable"] += 1
            continue
        for table in classify_expected(path, payload):
            counts[table] += 1
    return dict(sorted(counts.items()))


def validate_import(conn: Connection, expected: dict[str, list[str]]) -> dict[str, Any]:
    table_path_column = {
        "artifacts": "path", "athlete_documents": "source_path", "races": "source_path",
        "planned_workouts": "source_path", "completed_activities": "source_path",
        "completed_reviews": "source_path", "completed_feedback": "source_path",
        "system_state": "source_path",
    }
    report: dict[str, Any] = {}
    ok = True
    with conn.cursor() as cursor:
        for table, paths in sorted(expected.items()):
            if not paths:
                continue
            column = table_path_column[table]
            cursor.execute(f"SELECT count(*) FROM {table} WHERE {column} = ANY(%s)", (paths,))
            actual = int(cursor.fetchone()[0])
            expected_count = len(set(paths))
            table_ok = actual == expected_count
            ok = ok and table_ok
            report[table] = {"expected": expected_count, "actual": actual, "ok": table_ok}
    report["ok"] = ok
    return report


def main() -> None:
    args = parse_args()
    paths = candidate_paths()
    if not args.apply:
        print(json.dumps({"mode": "dry-run", "files": len(paths), "counts": dry_run_summary(paths)}, indent=2))
        return

    expected: dict[str, list[str]] = defaultdict(list)
    conn = wait_for_database(timeout_s=args.db_timeout)
    try:
        ensure_schema(conn)
        for path in paths:
            import_path(conn, path, expected)
        conn.commit()
        payload: dict[str, Any] = {"mode": "apply", "files": len(paths),
                                   "counts": {k: len(set(v)) for k, v in sorted(expected.items())}}
        if args.prune:
            payload["pruned"] = prune_missing(conn, {rel_path(p) for p in paths})
        if args.validate:
            payload["validation"] = validate_import(conn, expected)
            if not payload["validation"].get("ok"):
                print(json.dumps(payload, indent=2))
                raise SystemExit(1)
        print(json.dumps(payload, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
