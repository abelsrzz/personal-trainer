from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection


def database_url() -> str:
    """Build the Postgres DSN from DATABASE_URL or POSTGRES_* parts."""
    url = str(os.getenv("DATABASE_URL") or "").strip()
    if url:
        return url
    db = os.getenv("POSTGRES_DB") or "personal_trainer"
    user = os.getenv("POSTGRES_USER") or "personal_trainer"
    password = os.getenv("POSTGRES_PASSWORD") or "personal_trainer"
    host = os.getenv("POSTGRES_HOST") or "db"
    port = os.getenv("POSTGRES_PORT") or "5432"
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def sql_enabled() -> bool:
    """True when STORAGE_BACKEND=sql. Anything else keeps pure-file behavior."""
    return str(os.getenv("STORAGE_BACKEND") or "file").strip().lower() == "sql"


def connect() -> Connection:
    return psycopg.connect(database_url())


def wait_for_database(timeout_s: int = 60, interval_s: float = 1.0) -> Connection:
    """Block until Postgres accepts a connection (used by the migrate one-shot)."""
    deadline = time.monotonic() + max(1, timeout_s)
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return connect()
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(interval_s)
    if last_error:
        raise last_error
    return connect()


@contextmanager
def connection() -> Iterator[Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
