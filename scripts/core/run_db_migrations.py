#!/usr/bin/env python3
"""Run database migrations using credentials provided by environment variables."""

from __future__ import annotations

import os
import re
import hashlib
import time
from pathlib import Path

import psycopg2

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Matches an (optionally tagged) dollar-quote delimiter, e.g. $$ or $tag$.
DOLLAR_QUOTE_RE = re.compile(r"\$[A-Za-z_]*\$")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def quote_identifier(identifier: str) -> str:
    if not IDENTIFIER_RE.match(identifier):
        raise RuntimeError(f"Unsafe PostgreSQL identifier in DB role: {identifier!r}")
    return identifier


def connect():
    return psycopg2.connect(
        host=require_env("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=require_env("DB_NAME"),
        user=require_env("DB_DDL_USER"),
        password=require_env("DB_DDL_PASSWORD"),
        connect_timeout=30,
        options="-c statement_timeout=300000",
    )


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on top-level semicolons.

    Respects dollar-quoted blocks (``$$ ... $$`` / ``$tag$ ... $tag$``) used by
    PL/pgSQL functions and DO blocks, so semicolons inside them don't cause a
    premature split.
    """
    statements = []
    current: list[str] = []
    dollar_tag: str | None = None
    i, n = 0, len(sql)
    while i < n:
        if dollar_tag is None:
            match = DOLLAR_QUOTE_RE.match(sql, i)
            if match:
                dollar_tag = match.group(0)
                current.append(dollar_tag)
                i = match.end()
                continue
            char = sql[i]
            if char == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                i += 1
                continue
            current.append(char)
            i += 1
        else:
            if sql.startswith(dollar_tag, i):
                current.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            current.append(sql[i])
            i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def is_effectively_empty(statement: str) -> bool:
    """True if a SQL fragment contains only line comments/whitespace."""
    for line in statement.splitlines():
        code = line.split("--", 1)[0].strip()
        if code:
            return False
    return True


def migration_checksum(migration_file: Path) -> str:
    return hashlib.sha256(migration_file.read_bytes()).hexdigest()


def ensure_migration_ledger(cursor) -> None:
    cursor.execute("CREATE SCHEMA IF NOT EXISTS ailog_peak")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ailog_peak.schema_migrations (
            migration_name TEXT PRIMARY KEY,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            execution_ms INTEGER NOT NULL CHECK (execution_ms >= 0)
        )
    """)


def run_migrations() -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))
    if not migration_files:
        raise RuntimeError(f"No numeric migrations found in {MIGRATIONS_DIR}")

    ddl_role = os.getenv("DB_DDL_ROLE", "").strip()
    app_role = os.getenv("DB_APP_ROLE", "role_ailog_analyzer_user").strip()

    with connect() as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            if ddl_role:
                cursor.execute(f"SET ROLE {quote_identifier(ddl_role)}")

            ensure_migration_ledger(cursor)
            connection.commit()

            for migration_file in migration_files:
                checksum = migration_checksum(migration_file)
                cursor.execute(
                    "SELECT checksum FROM ailog_peak.schema_migrations WHERE migration_name = %s",
                    (migration_file.name,),
                )
                applied = cursor.fetchone()
                if applied:
                    if applied[0].strip() != checksum:
                        raise RuntimeError(
                            f"Applied migration changed: {migration_file.name} "
                            f"(database={applied[0].strip()}, file={checksum})"
                        )
                    print(f"Skipping migration: {migration_file.name} (checksum verified)", flush=True)
                    continue

                print(f"Running migration: {migration_file.name}", flush=True)
                started = time.monotonic()
                try:
                    statements = split_sql_statements(migration_file.read_text(encoding="utf-8"))
                    for statement in statements:
                        if is_effectively_empty(statement):
                            continue
                        cursor.execute(statement)

                    execution_ms = max(0, round((time.monotonic() - started) * 1000))
                    cursor.execute(
                        """
                        INSERT INTO ailog_peak.schema_migrations
                            (migration_name, checksum, execution_ms)
                        VALUES (%s, %s, %s)
                        """,
                        (migration_file.name, checksum, execution_ms),
                    )
                    connection.commit()
                except Exception as exc:
                    connection.rollback()
                    raise RuntimeError(
                        f"Migration failed and was rolled back: {migration_file.name}: {exc}"
                    ) from exc

            app_role_identifier = quote_identifier(app_role)
            cursor.execute(f"GRANT USAGE ON SCHEMA ailog_peak TO {app_role_identifier}")
            cursor.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO {app_role_identifier}"
            )
            cursor.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO {app_role_identifier}"
            )
            cursor.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA ailog_peak "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role_identifier}"
            )
            cursor.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA ailog_peak "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {app_role_identifier}"
            )

        connection.commit()

    print("Database migrations completed", flush=True)


if __name__ == "__main__":
    run_migrations()
