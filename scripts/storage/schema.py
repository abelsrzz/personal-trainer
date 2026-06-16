from __future__ import annotations

from psycopg import Connection


# Scope: structured runtime data only. Garmin raw imports
# (training/completed/imports/garmin/**) and static knowledge files stay
# file-only by design, so no tables exist for them here.
SCHEMA_SQL = """
-- Generic path-keyed mirror of every structured runtime file. Backs the
-- transparent load_*/write_* routing in legacy_support so callers keep using
-- relative file paths while reads/writes hit the DB.
CREATE TABLE IF NOT EXISTS artifacts (
    path text PRIMARY KEY,
    kind text NOT NULL,
    payload jsonb,
    content_text text,
    checksum text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifacts_kind_idx ON artifacts(kind);

CREATE TABLE IF NOT EXISTS athlete_documents (
    key text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS races (
    id text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    name text,
    race_date date,
    priority text,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS races_race_date_idx ON races(race_date);

CREATE TABLE IF NOT EXISTS planned_workouts (
    slug text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    schedule_date date,
    sport text,
    name text,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS planned_workouts_schedule_date_idx ON planned_workouts(schedule_date);

CREATE TABLE IF NOT EXISTS completed_activities (
    slug text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    activity_id text,
    garmin_activity_id bigint,
    activity_date date,
    title text,
    activity_type text,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS completed_activities_activity_date_idx ON completed_activities(activity_date);
CREATE INDEX IF NOT EXISTS completed_activities_garmin_activity_id_idx ON completed_activities(garmin_activity_id);

CREATE TABLE IF NOT EXISTS completed_reviews (
    slug text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    review_date date,
    activity_name text,
    garmin_activity_id bigint,
    analysis jsonb NOT NULL,
    review_markdown text,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS completed_reviews_review_date_idx ON completed_reviews(review_date);

CREATE TABLE IF NOT EXISTS completed_feedback (
    slug text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    feedback_date date,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Web-managed collections. Each row is one logical entry; the aggregate JSON
-- file (system/state/*.json) is still dual-written for the agent + git.
CREATE TABLE IF NOT EXISTS daily_checkins (
    day date PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS planned_workout_actions (
    slug text PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS planned_workout_replans (
    slug text PRIMARY KEY,
    payload jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Catch-all for the remaining system/state/*.json runtime documents
-- (athlete_state, contexts, freshness, automation health, feeds, ...).
CREATE TABLE IF NOT EXISTS system_state (
    key text PRIMARY KEY,
    source_path text UNIQUE NOT NULL,
    payload jsonb NOT NULL,
    checksum text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


def ensure_schema(conn: Connection) -> None:
    with conn.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)
