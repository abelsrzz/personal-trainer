"""SQL storage backend for runtime structured data.

The project keeps its file-based representation (git-tracked, edited by the
opencode agent) and mirrors structured runtime data into PostgreSQL for fast
relational reads from the web app. Writes are dual-written to both the files
and the DB; agent file edits are reconciled back into the DB by the idempotent
``migrate_files_to_sql`` importer.

Garmin raw imports and static knowledge files intentionally stay file-only.
"""
