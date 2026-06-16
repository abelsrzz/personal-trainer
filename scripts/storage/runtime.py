from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from scripts.storage.db import connect, sql_enabled


def enabled() -> bool:
    return sql_enabled()


# --- serialization helpers -------------------------------------------------

def json_checksum(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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


def normalize_key(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# --- generic artifact mirror (path-keyed) ----------------------------------
# Used by legacy_support.load_*/write_* so callers keep passing relative file
# paths while the data round-trips through Postgres.

def get_artifact(path: str, kind: str) -> Any:
    """Return the stored payload/content for a relative path, or None if absent.

    For json/yaml artifacts returns the decoded payload dict/list; for markdown
    or text returns content_text.
    """
    with connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT kind, payload, content_text FROM artifacts WHERE path = %s",
            (path,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    if kind in {"json", "yaml"}:
        return row.get("payload")
    return row.get("content_text")


def put_artifact(path: str, kind: str, payload: Any = None, content_text: str | None = None) -> None:
    checksum = json_checksum(payload) if payload is not None else json_checksum(content_text)
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO artifacts(path, kind, payload, content_text, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (path) DO UPDATE SET
                kind = EXCLUDED.kind,
                payload = EXCLUDED.payload,
                content_text = EXCLUDED.content_text,
                checksum = EXCLUDED.checksum,
                updated_at = now()
            """,
            (path, kind, as_jsonb(payload) if payload is not None else None, content_text, checksum),
        )
        conn.commit()


def artifact_exists(path: str) -> bool:
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM artifacts WHERE path = %s", (path,))
        return cursor.fetchone() is not None


# --- generic keyed collections (web-managed state) -------------------------

def list_keyed_payloads(table: str, key_column: str) -> dict[str, dict[str, Any]]:
    with connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT {key_column} AS key, payload FROM {table} ORDER BY {key_column}")
        rows = cursor.fetchall()
    return {normalize_key(row["key"]): row["payload"] for row in rows if isinstance(row.get("payload"), dict)}


def upsert_keyed_payload(table: str, key_column: str, key: str, payload: dict[str, Any]) -> None:
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {table}({key_column}, payload)
            VALUES (%s, %s)
            ON CONFLICT ({key_column}) DO UPDATE SET
                payload = EXCLUDED.payload,
                updated_at = now()
            """,
            (key, as_jsonb(payload)),
        )
        conn.commit()


def delete_keyed_payload(table: str, key_column: str, key: str) -> None:
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE {key_column} = %s", (key,))
        conn.commit()


def replace_keyed_collection(table: str, key_column: str, items: dict[str, Any]) -> None:
    """Make ``table`` exactly match ``items`` (used when a web action rewrites
    the whole aggregate JSON document)."""
    with connect() as conn, conn.cursor() as cursor:
        keys = [normalize_key(key) for key in items.keys()]
        if keys:
            cursor.execute(f"DELETE FROM {table} WHERE {key_column} <> ALL(%s)", (keys,))
        else:
            cursor.execute(f"DELETE FROM {table}")
        for key, payload in items.items():
            if not isinstance(payload, dict):
                continue
            cursor.execute(
                f"""
                INSERT INTO {table}({key_column}, payload)
                VALUES (%s, %s)
                ON CONFLICT ({key_column}) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = now()
                """,
                (normalize_key(key), as_jsonb(payload)),
            )
        conn.commit()


# --- typed list helpers for the web read paths -----------------------------

def list_planned_workouts() -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT slug, source_path, payload FROM planned_workouts "
            "ORDER BY schedule_date NULLS LAST, name NULLS LAST, slug"
        )
        return [dict(row) for row in cursor.fetchall()]


def list_races() -> list[dict[str, Any]]:
    with connect() as conn, conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT id, source_path, payload FROM races "
            "ORDER BY race_date NULLS LAST, name NULLS LAST, id"
        )
        return [dict(row) for row in cursor.fetchall()]


def list_completed_feedback() -> dict[str, dict[str, Any]]:
    return list_keyed_payloads("completed_feedback", "slug")


def upsert_completed_feedback(slug: str, payload: dict[str, Any]) -> None:
    source_path = f"training/completed/feedback/{slug}.feedback.json"
    with connect() as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO completed_feedback(slug, source_path, feedback_date, payload, checksum)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                source_path = EXCLUDED.source_path,
                feedback_date = EXCLUDED.feedback_date,
                payload = EXCLUDED.payload,
                checksum = EXCLUDED.checksum,
                updated_at = now()
            """,
            (slug, source_path, payload.get("date"), as_jsonb(payload), json_checksum(payload)),
        )
        conn.commit()
