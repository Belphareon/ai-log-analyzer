#!/usr/bin/env python3
"""Run database migrations using credentials provided by environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg2


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def run_migrations() -> None:
    migration_files = sorted(MIGRATIONS_DIR.glob("[0-9]*.sql"))
    if not migration_files:
        raise RuntimeError(f"No numeric migrations found in {MIGRATIONS_DIR}")

    ddl_role = os.getenv("DB_DDL_ROLE", "").strip()
    app_role = os.getenv("DB_APP_ROLE", "role_ailog_analyzer_app").strip()

    with connect() as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            if ddl_role:
                cursor.execute(f"SET ROLE {quote_identifier(ddl_role)}")

            for migration_file in migration_files:
                print(f"Running migration: {migration_file.name}", flush=True)
                cursor.execute(migration_file.read_text(encoding="utf-8"))

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