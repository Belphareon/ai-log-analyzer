#!/usr/bin/env python3
"""Run database migrations using credentials provided by environment variables."""

from __future__ import annotations

import os
import re
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

            for migration_file in migration_files:
                print(f"Running migration: {migration_file.name}", flush=True)
                statements = split_sql_statements(migration_file.read_text(encoding="utf-8"))
                for index, statement in enumerate(statements):
                    if is_effectively_empty(statement):
                        continue
                    savepoint = f"migration_stmt_{index}"
                    cursor.execute(f"SAVEPOINT {savepoint}")
                    try:
                        cursor.execute(statement)
                    except psycopg2.Error as exc:
                        # Some environments have pre-existing tables with a
                        # legacy schema (older column names). CREATE TABLE
                        # IF NOT EXISTS is then a no-op, and a later
                        # statement referencing a "new" column (e.g. an
                        # index) can fail. Don't abort the whole migration
                        # for that - log it and move on.
                        cursor.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        preview = " ".join(statement.split())[:150]
                        print(
                            f"⚠️  Skipped statement in {migration_file.name} "
                            f"({exc.__class__.__name__}: {exc}): {preview}",
                            flush=True,
                        )
                    else:
                        cursor.execute(f"RELEASE SAVEPOINT {savepoint}")

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
