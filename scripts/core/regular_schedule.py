"""Bounded collection planning for the single regular writer."""

from datetime import datetime, timedelta, timezone

from .run_persistence import build_query_hash


class FactsOnlyDetector:
    def is_peak(self, *_args, **_kwargs):
        return {'is_peak': False, 'is_evaluated': False, 'profile_status': 'missing'}


def plan_collection_windows(
    now: datetime,
    coverage_start: datetime,
    complete_windows: set[datetime],
    *,
    max_windows: int = 8,
    settle_minutes: int = 2,
) -> list[tuple[datetime, bool]]:
    if now.tzinfo is None or coverage_start.tzinfo is None:
        raise ValueError('collection timestamps must be timezone-aware')
    if max_windows < 2 or settle_minutes < 0:
        raise ValueError('max_windows must be at least 2 and settle_minutes nonnegative')
    settled = now.astimezone(timezone.utc) - timedelta(minutes=settle_minutes)
    end = settled.replace(minute=(settled.minute // 15) * 15, second=0, microsecond=0)
    latest = end - timedelta(minutes=15)
    start = coverage_start.astimezone(timezone.utc)
    if start.minute % 15 or start.second or start.microsecond:
        raise ValueError('coverage_start must align to a 15-minute boundary')
    windows = []
    if latest >= start and latest not in complete_windows:
        windows.append((latest, True))
    current = start
    while current < latest and len(windows) < max_windows:
        if current not in complete_windows:
            windows.append((current, False))
        current += timedelta(minutes=15)
    return windows


def load_collection_state(connection, source_index, namespaces, initial_start):
    query_hash = build_query_hash(source_index, namespaces)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ailog_peak.collection_checkpoints (query_hash, coverage_start)
            VALUES (%s, %s) ON CONFLICT (query_hash) DO NOTHING
            """, (query_hash, initial_start),
        )
        cursor.execute(
            'SELECT coverage_start FROM ailog_peak.collection_checkpoints WHERE query_hash = %s',
            (query_hash,),
        )
        coverage_start = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT run_row.window_start, run_row.processed_count
            FROM ailog_peak.analysis_runs run_row
            WHERE run_row.query_hash = %s AND run_row.status = 'complete'
              AND run_row.superseded_by_run_id IS NULL
              AND run_row.window_end = run_row.window_start + INTERVAL '15 minutes'
              AND run_row.window_start >= %s
            ORDER BY run_row.completed_at
            """, (query_hash, coverage_start),
        )
        complete_counts = dict(cursor.fetchall())
    connection.commit()
    return coverage_start, complete_counts


def sync_report_knowledge(connection, source_index, namespaces, registry):
    from psycopg2.extras import Json, execute_values

    query_hash = build_query_hash(source_index, namespaces)
    rows = [
        (query_hash, key, list(problem.fingerprints), Json(problem.to_dict()))
        for key, problem in registry.problems.items()
    ]
    rows.extend(
        (query_hash, 'peak:' + key, [], Json(dict(peak.to_dict(), _report_kind='peak')))
        for key, peak in getattr(registry, 'peaks', {}).items()
    )
    with connection.cursor() as cursor:
        if rows:
            execute_values(cursor, """
                INSERT INTO ailog_peak.report_knowledge (query_hash, problem_key, fingerprints, payload)
                VALUES %s
                ON CONFLICT (query_hash, problem_key) DO UPDATE SET
                    fingerprints = EXCLUDED.fingerprints, payload = EXCLUDED.payload,
                    updated_at = NOW()
            """, rows, page_size=500)
    connection.commit()


def load_live_completion(connection, query_hash):
    with connection.cursor() as cursor:
        cursor.execute('SELECT last_live_window FROM ailog_peak.collection_checkpoints WHERE query_hash = %s', (query_hash,))
        completed = cursor.fetchone()[0]
    connection.commit()
    return completed


def mark_live_completion(connection, query_hash, window_start):
    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE ailog_peak.collection_checkpoints
            SET last_live_window = GREATEST(last_live_window, %s)
            WHERE query_hash = %s
        """, (window_start, query_hash))
    connection.commit()