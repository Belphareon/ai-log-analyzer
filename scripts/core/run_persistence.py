#!/usr/bin/env python3
"""Transactional persistence for complete analysis runs."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


WINDOW_MINUTES = 15


class PersistenceInvariantError(RuntimeError):
    """Raised when source, pipeline, and persisted quantities cannot reconcile."""


def build_query_hash(source_index: str, monitored_namespaces: Iterable[str]) -> str:
    contract = {
        'source_index': source_index,
        'namespaces': sorted(set(monitored_namespaces)),
        'level': 'ERROR',
        'window_semantics': '[start,end)',
        'fact_grain': '15m/namespace/application/fingerprint',
    }
    payload = json.dumps(contract, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _require_aware_aligned_window(window_start: datetime, window_end: datetime) -> None:
    for label, value in (('window_start', window_start), ('window_end', window_end)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise PersistenceInvariantError(f'{label} must be timezone-aware')
        if value.second or value.microsecond or value.minute % WINDOW_MINUTES:
            raise PersistenceInvariantError(f'{label} must align to a 15-minute boundary')
    if window_end <= window_start:
        raise PersistenceInvariantError('window_end must be after window_start')


def _coerce_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise PersistenceInvariantError(f'{label} is not a datetime')
    if result.tzinfo is None or result.utcoffset() is None:
        raise PersistenceInvariantError(f'{label} must be timezone-aware')
    return result


def _window_starts(window_start: datetime, window_end: datetime) -> List[datetime]:
    _require_aware_aligned_window(window_start, window_end)
    buckets = []
    current = window_start
    while current < window_end:
        buckets.append(current)
        current += timedelta(minutes=WINDOW_MINUTES)
    return buckets


def build_error_kind_rows(collection, run_id: str) -> List[tuple]:
    rows = []
    identities = set()
    for fact in collection.error_kind_facts:
        bucket = _coerce_datetime(fact.get('window_start'), 'fact.window_start')
        first_seen = _coerce_datetime(fact.get('first_event_at'), 'fact.first_event_at')
        last_seen = _coerce_datetime(fact.get('last_event_at'), 'fact.last_event_at')
        count = int(fact.get('error_count', 0))
        if count <= 0:
            raise PersistenceInvariantError('error-kind facts must have a positive error_count')
        if last_seen < first_seen:
            raise PersistenceInvariantError('fact last_event_at precedes first_event_at')

        namespace = str(fact.get('namespace') or 'unknown')
        application = str(fact.get('application') or 'unknown')
        fingerprint = str(fact.get('fingerprint') or '')
        if not fingerprint:
            raise PersistenceInvariantError('error-kind fact is missing fingerprint')
        identity = (bucket, namespace, application, fingerprint)
        if identity in identities:
            raise PersistenceInvariantError(f'duplicate error-kind fact identity: {identity}')
        identities.add(identity)

        metadata_quality = str(fact.get('metadata_quality') or 'unknown')
        if metadata_quality not in {'structured', 'derived', 'unknown'}:
            raise PersistenceInvariantError(f'invalid metadata_quality: {metadata_quality}')
        rows.append((
            run_id,
            bucket,
            namespace,
            application,
            fingerprint,
            str(fact.get('error_type') or 'UnknownError'),
            str(fact.get('category') or 'unknown'),
            str(fact.get('subcategory') or 'unclassified'),
            count,
            first_seen,
            last_seen,
            str(fact.get('sample_message') or '')[:2000],
            metadata_quality,
        ))
    return sorted(rows, key=lambda row: (row[1], row[2], row[3], row[4]))


def build_namespace_rows(
    error_kind_rows: Sequence[tuple],
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    monitored_namespaces: Iterable[str],
) -> List[tuple]:
    namespaces = sorted(set(namespace for namespace in monitored_namespaces if namespace))
    if not namespaces:
        raise PersistenceInvariantError('monitored namespace scope is empty')

    buckets = _window_starts(window_start, window_end)
    bucket_set = set(buckets)
    namespace_set = set(namespaces)
    totals: Dict[Tuple[datetime, str], int] = defaultdict(int)
    for row in error_kind_rows:
        bucket, namespace, count = row[1], row[2], row[8]
        if bucket not in bucket_set:
            raise PersistenceInvariantError(f'fact bucket outside run window: {bucket.isoformat()}')
        if namespace not in namespace_set:
            raise PersistenceInvariantError(f'fact namespace outside monitored scope: {namespace}')
        totals[(bucket, namespace)] += count

    return [
        (run_id, bucket, namespace, totals.get((bucket, namespace), 0))
        for bucket in buckets
        for namespace in namespaces
    ]


def validate_reconciliation(
    expected_count: Optional[int],
    fetched_count: int,
    processed_count: int,
    error_kind_rows: Sequence[tuple],
    namespace_rows: Sequence[tuple],
) -> int:
    if expected_count is None:
        raise PersistenceInvariantError('expected source count is required for a complete run')
    quantities = {
        'expected': int(expected_count),
        'fetched': int(fetched_count),
        'processed': int(processed_count),
        'error_kind_events': sum(row[8] for row in error_kind_rows),
        'namespace_events': sum(row[3] for row in namespace_rows),
    }
    if any(value < 0 for value in quantities.values()):
        raise PersistenceInvariantError(f'negative reconciliation quantity: {quantities}')
    if len(set(quantities.values())) != 1:
        raise PersistenceInvariantError(f'run quantities do not reconcile: {quantities}')
    return quantities['error_kind_events']


def build_incident_rows(
    collection,
    error_kind_rows: Sequence[tuple],
    run_id: str,
    run_type: str,
) -> List[tuple]:
    incidents = {incident.fingerprint: incident for incident in collection.incidents}
    grouped: Dict[Tuple[datetime, str, str], Dict[str, Any]] = {}
    for fact in error_kind_rows:
        bucket, namespace, application, fingerprint, count = (
            fact[1], fact[2], fact[3], fact[4], fact[8]
        )
        if fingerprint not in incidents:
            raise PersistenceInvariantError(
                f'fact fingerprint has no incident: {fingerprint}'
            )
        key = (bucket, namespace, fingerprint)
        row = grouped.setdefault(key, {'count': 0, 'apps': defaultdict(int)})
        row['count'] += count
        row['apps'][application] += count

    rows = []
    for (bucket, namespace, fingerprint), aggregate in sorted(grouped.items()):
        incident = incidents[fingerprint]
        apps = sorted(aggregate['apps'])
        top_app = min(apps, key=lambda app: (-aggregate['apps'][app], app))
        versions = sorted(getattr(incident, 'versions', []) or [])
        rows.append((
            run_id,
            bucket,
            bucket,
            bucket.weekday(),
            bucket.hour,
            bucket.minute // WINDOW_MINUTES,
            namespace,
            fingerprint,
            aggregate['count'],
            aggregate['count'],
            incident.stats.baseline_rate if incident.stats.baseline_rate > 0 else None,
            incident.flags.is_new,
            incident.flags.is_spike,
            incident.flags.is_burst,
            incident.flags.is_cross_namespace,
            incident.flags.is_regression,
            incident.flags.is_cascade,
            incident.error_type or '',
            (incident.normalized_message or '')[:500],
            run_type,
            incident.score,
            incident.severity.value,
            top_app,
            versions[-1] if versions else None,
            apps,
        ))
    return rows


def build_detection_rows(
    collection,
    error_kind_rows: Sequence[tuple],
    run_id: str,
) -> List[tuple]:
    incidents = {incident.fingerprint: incident for incident in collection.incidents}
    fact_identities = sorted({
        (fact[1], fact[2], fact[4])
        for fact in error_kind_rows
    })
    rows = []
    identities = set()
    for bucket, namespace, fingerprint in fact_identities:
        incident = incidents[fingerprint]
        flags = {
            'is_new': incident.flags.is_new,
            'is_spike': incident.flags.is_spike,
            'is_burst': incident.flags.is_burst,
            'is_cross_namespace': incident.flags.is_cross_namespace,
            'is_regression': incident.flags.is_regression,
            'is_cascade': incident.flags.is_cascade,
        }
        for evidence in incident.evidence:
            identity = (bucket, namespace, fingerprint, evidence.rule)
            if identity in identities:
                raise PersistenceInvariantError(f'duplicate detection event identity: {identity}')
            identities.add(identity)
            details = dict(evidence.details or {})
            snapshot_id = details.get('threshold_snapshot_id')
            rows.append((
                run_id,
                bucket,
                namespace,
                fingerprint,
                evidence.rule,
                str(details.get('detector_version') or 'pipeline_v1'),
                evidence.current,
                evidence.threshold,
                snapshot_id or None,
                json.dumps(flags, sort_keys=True),
                evidence.message or '',
                json.dumps({
                    'baseline': evidence.baseline,
                    'current': evidence.current,
                    'threshold': evidence.threshold,
                    'details': details,
                }, sort_keys=True),
            ))
    return rows


def _default_execute_values(cursor, statement: str, rows: Sequence[tuple], page_size: int) -> None:
    from psycopg2.extras import execute_values

    execute_values(cursor, statement, rows, page_size=page_size)


def persist_analysis_run(
    connection_factory: Callable[[], Any],
    collection,
    run_type: str,
    window_start: datetime,
    window_end: datetime,
    monitored_namespaces: Iterable[str],
    expected_count: Optional[int],
    fetched_count: int,
    source_index: str,
    code_version: Optional[str] = None,
    query_hash: Optional[str] = None,
    execute_values_fn: Optional[Callable[..., None]] = None,
) -> Dict[str, int]:
    """Persist all run data and mark it complete only after exact reconciliation."""
    if run_type not in {'regular', 'backfill'}:
        raise PersistenceInvariantError(f'unsupported run_type: {run_type}')
    if not collection or not collection.run_id:
        raise PersistenceInvariantError('collection.run_id is required')

    namespaces = sorted(set(monitored_namespaces))
    run_id = collection.run_id
    processed_count = int(collection.input_records)
    query_hash = query_hash or build_query_hash(source_index, namespaces)
    code_version = code_version or os.getenv('IMAGE_TAG') or collection.pipeline_version
    error_kind_rows = build_error_kind_rows(collection, run_id)
    namespace_rows = build_namespace_rows(
        error_kind_rows, run_id, window_start, window_end, namespaces
    )
    persisted_event_count = validate_reconciliation(
        expected_count,
        fetched_count,
        processed_count,
        error_kind_rows,
        namespace_rows,
    )
    incident_rows = build_incident_rows(collection, error_kind_rows, run_id, run_type)
    detection_rows = build_detection_rows(collection, error_kind_rows, run_id)
    execute_values_fn = execute_values_fn or _default_execute_values

    connection = connection_factory()
    cursor = connection.cursor()
    running_committed = False
    try:
        cursor.execute(
            """
            UPDATE ailog_peak.analysis_runs
            SET status = 'failed', completed_at = NOW(), error_code = 'abandoned_run',
                error_message = 'Stale running attempt superseded by a retry'
            WHERE run_type = %s AND window_start = %s AND window_end = %s
              AND query_hash = %s AND status = 'running'
              AND started_at < NOW() - INTERVAL '6 hours'
            """,
            (run_type, window_start, window_end, query_hash),
        )
        cursor.execute(
            """
            SELECT run_id
            FROM ailog_peak.analysis_runs
            WHERE run_type = %s AND window_start = %s AND window_end = %s
              AND query_hash = %s AND status = 'complete'
              AND superseded_by_run_id IS NULL
            ORDER BY completed_at DESC, started_at DESC
            LIMIT 1
            FOR UPDATE
            """,
            (run_type, window_start, window_end, query_hash),
        )
        existing = cursor.fetchone()
        replay_of_run_id = existing[0] if existing else None
        cursor.execute(
            """
            INSERT INTO ailog_peak.analysis_runs
                (run_id, run_type, window_start, window_end, query_hash,
                 source_index, code_version, status, expected_count,
                 fetched_count, processed_count, replay_of_run_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'running', %s, %s, %s, %s)
            """,
            (
                run_id, run_type, window_start, window_end, query_hash,
                source_index, code_version, expected_count, fetched_count,
                processed_count, replay_of_run_id,
            ),
        )
        connection.commit()
        running_committed = True

        if error_kind_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.error_kind_counts
                    (run_id, window_start, namespace, application, fingerprint,
                     error_type, category, subcategory, error_count,
                     first_event_at, last_event_at, sample_message, metadata_quality)
                VALUES %s
                ON CONFLICT (run_id, window_start, namespace, application, fingerprint)
                DO UPDATE SET
                    error_type = EXCLUDED.error_type,
                    category = EXCLUDED.category,
                    subcategory = EXCLUDED.subcategory,
                    error_count = EXCLUDED.error_count,
                    first_event_at = EXCLUDED.first_event_at,
                    last_event_at = EXCLUDED.last_event_at,
                    sample_message = EXCLUDED.sample_message,
                    metadata_quality = EXCLUDED.metadata_quality
            """, error_kind_rows, page_size=1000)

        execute_values_fn(cursor, """
            INSERT INTO ailog_peak.namespace_error_counts
                (run_id, window_start, namespace, error_count)
            VALUES %s
            ON CONFLICT (run_id, window_start, namespace)
            DO UPDATE SET error_count = EXCLUDED.error_count
        """, namespace_rows, page_size=1000)

        peak_raw_rows = [
            (
                bucket,
                bucket.weekday(),
                bucket.hour,
                bucket.minute // WINDOW_MINUTES,
                namespace,
                count,
                count,
            )
            for _, bucket, namespace, count in namespace_rows
        ]
        execute_values_fn(cursor, """
            INSERT INTO ailog_peak.peak_raw_data
                (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
                 error_count, original_value)
            VALUES %s
            ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
            DO UPDATE SET error_count = EXCLUDED.error_count,
                          original_value = EXCLUDED.original_value
        """, peak_raw_rows, page_size=1000)

        if incident_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.peak_investigation
                    (run_id, window_start, timestamp, day_of_week, hour_of_day,
                     quarter_hour, namespace, fingerprint, original_value,
                     reference_value, baseline_mean, is_new, is_spike, is_burst,
                     is_cross_namespace, is_regression, is_cascade, error_type,
                     error_message, detection_method, score, severity, app_name,
                     app_version, affected_services)
                VALUES %s
                ON CONFLICT (run_id, window_start, namespace, fingerprint)
                DO UPDATE SET
                    original_value = EXCLUDED.original_value,
                    reference_value = EXCLUDED.reference_value,
                    baseline_mean = EXCLUDED.baseline_mean,
                    is_new = EXCLUDED.is_new,
                    is_spike = EXCLUDED.is_spike,
                    is_burst = EXCLUDED.is_burst,
                    is_cross_namespace = EXCLUDED.is_cross_namespace,
                    is_regression = EXCLUDED.is_regression,
                    is_cascade = EXCLUDED.is_cascade,
                    error_type = EXCLUDED.error_type,
                    error_message = EXCLUDED.error_message,
                    score = EXCLUDED.score,
                    severity = EXCLUDED.severity,
                    app_name = EXCLUDED.app_name,
                    app_version = EXCLUDED.app_version,
                    affected_services = EXCLUDED.affected_services
            """, incident_rows, page_size=1000)

        if detection_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.detection_events
                    (run_id, window_start, namespace, fingerprint, detector_type,
                     detector_version, evaluated_value, threshold_value,
                     threshold_snapshot_id, flags, explanation, evidence)
                VALUES %s
                ON CONFLICT (run_id, window_start, namespace, fingerprint, detector_type)
                DO UPDATE SET
                    detector_version = EXCLUDED.detector_version,
                    evaluated_value = EXCLUDED.evaluated_value,
                    threshold_value = EXCLUDED.threshold_value,
                    threshold_snapshot_id = EXCLUDED.threshold_snapshot_id,
                    flags = EXCLUDED.flags,
                    explanation = EXCLUDED.explanation,
                    evidence = EXCLUDED.evidence
            """, detection_rows, page_size=1000)

        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(error_count), 0) "
            "FROM ailog_peak.error_kind_counts WHERE run_id = %s",
            (run_id,),
        )
        stored_fact_rows, stored_fact_events = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(error_count), 0) "
            "FROM ailog_peak.namespace_error_counts WHERE run_id = %s",
            (run_id,),
        )
        stored_namespace_rows, stored_namespace_events = cursor.fetchone()
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.peak_investigation WHERE run_id = %s",
            (run_id,),
        )
        stored_incident_rows = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.detection_events WHERE run_id = %s",
            (run_id,),
        )
        stored_detection_rows = cursor.fetchone()[0]
        stored = (
            int(stored_fact_rows),
            int(stored_fact_events),
            int(stored_namespace_rows),
            int(stored_namespace_events),
            int(stored_incident_rows),
            int(stored_detection_rows),
        )
        expected_stored = (
            len(error_kind_rows),
            persisted_event_count,
            len(namespace_rows),
            persisted_event_count,
            len(incident_rows),
            len(detection_rows),
        )
        if stored != expected_stored:
            raise PersistenceInvariantError(
                f'database row reconciliation failed: stored={stored}, expected={expected_stored}'
            )

        cursor.execute(
            """
            UPDATE ailog_peak.analysis_runs
            SET status = 'superseded', superseded_by_run_id = %s,
                completed_at = COALESCE(completed_at, NOW())
            WHERE run_type = %s AND window_start = %s AND window_end = %s
              AND query_hash = %s AND status = 'complete'
              AND superseded_by_run_id IS NULL AND run_id <> %s
            """,
            (run_id, run_type, window_start, window_end, query_hash, run_id),
        )
        cursor.execute(
            """
            UPDATE ailog_peak.analysis_runs
            SET status = 'complete', persisted_event_count = %s,
                fact_row_count = %s, incident_count = %s,
                completed_at = NOW(), error_code = NULL, error_message = NULL
            WHERE run_id = %s AND status = 'running'
            """,
            (persisted_event_count, len(error_kind_rows), len(incident_rows), run_id),
        )
        if cursor.rowcount != 1:
            raise PersistenceInvariantError('running ledger row was not completed exactly once')
        connection.commit()
        return {
            'persisted_events': persisted_event_count,
            'fact_rows': len(error_kind_rows),
            'namespace_rows': len(namespace_rows),
            'incident_rows': len(incident_rows),
            'detection_rows': len(detection_rows),
        }
    except Exception as exc:
        connection.rollback()
        if running_committed:
            try:
                cursor.execute(
                    """
                    UPDATE ailog_peak.analysis_runs
                    SET status = 'failed', completed_at = NOW(),
                        error_code = %s, error_message = %s
                    WHERE run_id = %s AND status = 'running'
                    """,
                    (exc.__class__.__name__, str(exc)[:2000], run_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()