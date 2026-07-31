#!/usr/bin/env python3
"""Roll up complete facts and apply bounded retention in one transaction."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2


ADVISORY_LOCK_KEY = 781_190_315
DEFAULT_RETENTION_DAYS = 90


def emit(event: str, **fields) -> None:
    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **fields,
    }
    print(json.dumps(payload, sort_keys=True), flush=True)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect():
    user = os.getenv("DB_DDL_USER", "").strip() or require_env("DB_USER")
    password = os.getenv("DB_DDL_PASSWORD", "").strip() or require_env("DB_PASSWORD")
    return psycopg2.connect(
        host=require_env("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=require_env("DB_NAME"),
        user=user,
        password=password,
        connect_timeout=30,
        options="-c statement_timeout=900000 -c lock_timeout=30000",
    )


def _create_rollup_staging(cursor, cutoff_at: datetime) -> tuple[int, int, int, int]:
    cursor.execute(
        """
        CREATE TEMP TABLE staged_error_kind_rollups ON COMMIT DROP AS
        SELECT
            (window_start AT TIME ZONE 'UTC')::DATE AS rollup_date,
            namespace,
            application,
            fingerprint,
            error_type,
            category,
            subcategory,
            SUM(error_count)::BIGINT AS error_count,
            COUNT(DISTINCT window_start)::INTEGER AS complete_window_count,
            MIN(first_event_at) AS first_event_at,
            MAX(last_event_at) AS last_event_at
        FROM ailog_peak.v_complete_error_kind_counts
        WHERE window_start < %s
        GROUP BY
            (window_start AT TIME ZONE 'UTC')::DATE,
            namespace,
            application,
            fingerprint,
            error_type,
            category,
            subcategory
        """,
        (cutoff_at,),
    )
    cursor.execute(
        """
        CREATE TEMP TABLE staged_namespace_windows ON COMMIT DROP AS
        SELECT
            (window_start AT TIME ZONE 'UTC')::DATE AS rollup_date,
            window_start,
            namespace,
            error_count::BIGINT AS error_count,
            'authoritative_facts'::VARCHAR(30) AS source_kind
        FROM ailog_peak.v_complete_namespace_error_counts
        WHERE window_start < %s
        """,
        (cutoff_at,),
    )
    cursor.execute(
        """
        INSERT INTO staged_namespace_windows (
            rollup_date, window_start, namespace, error_count, source_kind
        )
        SELECT
            (raw_row.timestamp AT TIME ZONE 'UTC')::DATE,
            raw_row.timestamp,
            raw_row.namespace,
            COALESCE(raw_row.error_count, 0)::BIGINT,
            'legacy_peak_raw_data'
        FROM ailog_peak.peak_raw_data raw_row
        WHERE raw_row.timestamp < %s
          AND NOT EXISTS (
              SELECT 1
              FROM staged_namespace_windows authoritative
              WHERE authoritative.window_start = raw_row.timestamp
                AND authoritative.namespace = raw_row.namespace
          )
        """,
        (cutoff_at,),
    )
    cursor.execute(
        """
        CREATE TEMP TABLE staged_namespace_rollups ON COMMIT DROP AS
        SELECT
            rollup_date,
            namespace,
            SUM(error_count)::BIGINT AS error_count,
            COUNT(DISTINCT window_start)::INTEGER AS complete_window_count,
            CASE
                WHEN BOOL_AND(source_kind = 'authoritative_facts')
                    THEN 'authoritative_facts'
                WHEN BOOL_AND(source_kind = 'legacy_peak_raw_data')
                    THEN 'legacy_peak_raw_data'
                ELSE 'mixed'
            END::VARCHAR(30) AS source_kind
        FROM staged_namespace_windows
        GROUP BY rollup_date, namespace
        """
    )
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(error_count), 0)
        FROM ailog_peak.v_complete_error_kind_counts
        WHERE window_start < %s
        """,
        (cutoff_at,),
    )
    source_fact_rows, source_events = cursor.fetchone()
    cursor.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(error_count), 0)
        FROM staged_namespace_windows
        WHERE source_kind = 'legacy_peak_raw_data'
        """
    )
    legacy_raw_rows, legacy_raw_events = cursor.fetchone()
    return (
        int(source_fact_rows),
        int(source_events),
        int(legacy_raw_rows),
        int(legacy_raw_events),
    )


def _upsert_rollups(cursor) -> int:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM staged_namespace_rollups staged
        JOIN ailog_peak.daily_namespace_rollups persisted
          USING (rollup_date, namespace)
        WHERE staged.complete_window_count <> 96
           OR staged.source_kind <> 'authoritative_facts'
        """
    )
    unsafe_replays = cursor.fetchone()[0]
    if unsafe_replays:
        raise RuntimeError(
            "Late data overlaps an existing daily rollup without a complete "
            f"96-window authoritative replay ({unsafe_replays} namespace-day rows)"
        )

    cursor.execute(
        """
        CREATE TEMP TABLE staged_rollup_replacements ON COMMIT DROP AS
        SELECT staged.rollup_date, staged.namespace
        FROM staged_namespace_rollups staged
        JOIN ailog_peak.daily_namespace_rollups persisted
          USING (rollup_date, namespace)
        """
    )
    cursor.execute(
        """
        DELETE FROM ailog_peak.daily_error_kind_rollups persisted
        USING staged_rollup_replacements replacement
        WHERE persisted.rollup_date = replacement.rollup_date
          AND persisted.namespace = replacement.namespace
        """
    )
    cursor.execute(
        """
        DELETE FROM ailog_peak.daily_namespace_rollups persisted
        USING staged_rollup_replacements replacement
        WHERE persisted.rollup_date = replacement.rollup_date
          AND persisted.namespace = replacement.namespace
        """
    )

    cursor.execute(
        """
        INSERT INTO ailog_peak.daily_error_kind_rollups (
            rollup_date, namespace, application, fingerprint, error_type,
            category, subcategory, error_count, complete_window_count,
            first_event_at, last_event_at, refreshed_at
        )
        SELECT
            rollup_date, namespace, application, fingerprint, error_type,
            category, subcategory, error_count, complete_window_count,
            first_event_at, last_event_at, NOW()
        FROM staged_error_kind_rollups
        """
    )
    error_kind_rows = cursor.rowcount

    cursor.execute(
        """
        INSERT INTO ailog_peak.daily_namespace_rollups (
            rollup_date, namespace, error_count, complete_window_count,
            source_kind, refreshed_at
        )
        SELECT
            rollup_date, namespace, error_count, complete_window_count,
            source_kind, NOW()
        FROM staged_namespace_rollups
        """
    )
    return error_kind_rows + cursor.rowcount


def _assert_rollup_reconciliation(cursor) -> None:
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM staged_error_kind_rollups staged
        LEFT JOIN ailog_peak.daily_error_kind_rollups persisted
          USING (
              rollup_date, namespace, application, fingerprint,
              error_type, category, subcategory
          )
        WHERE persisted.rollup_date IS NULL
           OR persisted.error_count <> staged.error_count
           OR persisted.complete_window_count <> staged.complete_window_count
           OR persisted.first_event_at <> staged.first_event_at
           OR persisted.last_event_at <> staged.last_event_at
        """
    )
    error_kind_mismatches = cursor.fetchone()[0]
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM staged_namespace_rollups staged
        LEFT JOIN ailog_peak.daily_namespace_rollups persisted
          USING (rollup_date, namespace)
        WHERE persisted.rollup_date IS NULL
           OR persisted.error_count <> staged.error_count
           OR persisted.complete_window_count <> staged.complete_window_count
           OR persisted.source_kind <> staged.source_kind
        """
    )
    namespace_mismatches = cursor.fetchone()[0]
    if error_kind_mismatches or namespace_mismatches:
        raise RuntimeError(
            "Rollup reconciliation failed: "
            f"error_kind_mismatches={error_kind_mismatches}, "
            f"namespace_mismatches={namespace_mismatches}"
        )


def _delete_expired_rows(cursor, cutoff_at: datetime) -> dict[str, int]:
    deleted = {}
    for metric, table, column in (
        ("deleted_fact_rows", "error_kind_counts", "window_start"),
        ("deleted_namespace_rows", "namespace_error_counts", "window_start"),
    ):
        cursor.execute(
            f"DELETE FROM ailog_peak.{table} WHERE {column} < %s",
            (cutoff_at,),
        )
        deleted[metric] = cursor.rowcount

    cursor.execute(
        "DELETE FROM ailog_peak.peak_raw_data WHERE timestamp < %s",
        (cutoff_at,),
    )
    deleted["deleted_peak_raw_rows"] = cursor.rowcount
    return deleted


def run_maintenance(
    connection_factory=connect,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff_at = (current_time.astimezone(timezone.utc) - timedelta(days=retention_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    maintenance_id = str(uuid.uuid4())
    result: dict[str, object] = {
        "maintenance_id": maintenance_id,
        "retention_days": retention_days,
        "cutoff_at": cutoff_at.isoformat(),
        "dry_run": dry_run,
    }
    emit("maintenance_started", **result)

    connection = connection_factory()
    try:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,))
            cursor.execute(
                """
                INSERT INTO ailog_peak.maintenance_runs (
                    maintenance_id, maintenance_type, cutoff_at, status
                ) VALUES (%s, 'daily_rollup_retention', %s, 'running')
                """,
                (maintenance_id, cutoff_at),
            )
            (
                source_fact_rows,
                source_events,
                legacy_raw_rows,
                legacy_raw_events,
            ) = _create_rollup_staging(cursor, cutoff_at)
            rolled_up_rows = _upsert_rollups(cursor)
            _assert_rollup_reconciliation(cursor)
            deleted = _delete_expired_rows(cursor, cutoff_at)
            result.update(
                source_fact_rows=source_fact_rows,
                source_events=source_events,
                legacy_raw_rows=legacy_raw_rows,
                legacy_raw_events=legacy_raw_events,
                rolled_up_rows=rolled_up_rows,
                **deleted,
            )
            cursor.execute(
                """
                UPDATE ailog_peak.maintenance_runs
                SET status = 'complete',
                    source_fact_rows = %s,
                    source_events = %s,
                    rolled_up_rows = %s,
                    deleted_fact_rows = %s,
                    deleted_namespace_rows = %s,
                    deleted_peak_raw_rows = %s,
                    completed_at = NOW()
                WHERE maintenance_id = %s
                """,
                (
                    source_fact_rows,
                    source_events,
                    rolled_up_rows,
                    deleted["deleted_fact_rows"],
                    deleted["deleted_namespace_rows"],
                    deleted["deleted_peak_raw_rows"],
                    maintenance_id,
                ),
            )
        if dry_run:
            connection.rollback()
            emit("maintenance_dry_run_complete", **result)
        else:
            connection.commit()
            emit("maintenance_complete", **result)
        return result
    except Exception as exc:
        connection.rollback()
        if not dry_run:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO ailog_peak.maintenance_runs (
                            maintenance_id, maintenance_type, cutoff_at, status,
                            error_message, completed_at
                        ) VALUES (
                            %s, 'daily_rollup_retention', %s, 'failed', %s, NOW()
                        )
                        """,
                        (maintenance_id, cutoff_at, str(exc)[:4000]),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
        emit(
            "maintenance_failed",
            maintenance_id=maintenance_id,
            cutoff_at=cutoff_at.isoformat(),
            error=str(exc),
        )
        raise
    finally:
        connection.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=int(os.getenv("FACT_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS))),
        help="Days of fine-grained facts to retain (default: %(default)s)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Roll back all changes after validation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_maintenance(retention_days=args.retention_days, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Data maintenance failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())