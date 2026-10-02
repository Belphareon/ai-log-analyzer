#!/usr/bin/env python3
"""Transactional persistence for complete analysis runs."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from .peak_decision import (
        build_contributor_rows,
        build_decision_rows,
        decision_from_dict,
    )
except ImportError:  # pragma: no cover - direct script execution
    from peak_decision import build_contributor_rows, build_decision_rows, decision_from_dict


WINDOW_MINUTES = 15
try:
    from ..analysis.operational_cause import CAUSE_SIGNATURE_VERSION
except ImportError:  # pragma: no cover - direct script execution
    from analysis.operational_cause import CAUSE_SIGNATURE_VERSION


class PersistenceInvariantError(RuntimeError):
    """Raised when source, pipeline, and persisted quantities cannot reconcile."""


@contextmanager
def stream_advisory_lock(
    connection_factory: Callable[[], Any],
    stream_key: str,
):
    """Hold one stream lock for load, correlation, and persistence."""
    connection = connection_factory()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (stream_key,),
        )
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


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


def load_peak_episodes_before(
    connection_factory: Callable[[], Any],
    *,
    stream_key: str,
    before_window_start: datetime,
) -> List[dict[str, Any]]:
    """Load event-time episode state used to seed the next correlation run."""
    if before_window_start.tzinfo is None or before_window_start.utcoffset() is None:
        raise PersistenceInvariantError('before_window_start must be timezone-aware')
    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT episode_id, stream_key, cause_signature,
                       signature_version, state, first_window_start_utc,
                       last_window_start_utc, resolved_at_utc,
                       current_raw_error_lines, cumulative_raw_error_lines,
                       current_operation_occurrences,
                       cumulative_operation_occurrences,
                       diagnosis_confidence, active_namespaces,
                       material_change_reasons, non_peak_windows,
                      previous_episode_id,
                      COALESCE((
                          SELECT ARRAY_AGG(window_decision_id)
                          FROM ailog_peak.peak_episode_windows w
                          WHERE w.episode_id = p.episode_id
                      ), ARRAY[]::CHAR(64)[])
                FROM ailog_peak.peak_episodes
                  AS p
                WHERE stream_key = %s
                  AND last_window_start_utc < %s
                ORDER BY last_window_start_utc ASC, episode_id ASC
                """,
                (stream_key, before_window_start),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    return [
        {
            'episode_id': str(row[0]),
            'stream_key': row[1],
            'cause_signature': row[2] or 'unresolved',
            'cause_signature_version': row[3],
            'state': row[4],
            'first_window_start_utc': row[5],
            'last_window_start_utc': row[6],
            'resolved_at_utc': row[7],
            'current_raw_error_lines': row[8],
            'cumulative_raw_error_lines': row[9],
            'current_operation_occurrences': row[10],
            'cumulative_operation_occurrences': row[11],
            'diagnosis_confidence': row[12],
            'active_namespaces': row[13] or [],
            'material_change_reasons': row[14] or [],
            'non_peak_windows': row[15] or 0,
            'previous_episode_id': str(row[16]) if row[16] else None,
            'seen_window_ids': {str(item).strip() for item in (row[17] or [])},
        }
        for row in rows
    ]


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


def build_namespace_peak_decision_rows(collection, run_id: str) -> List[tuple]:
    """Build authoritative decision rows from the pipeline's serialized contract."""
    payloads = getattr(collection, 'namespace_peak_decisions', None) or []
    if not payloads:
        return []
    decisions = [decision_from_dict(payload) for payload in payloads]
    return build_decision_rows(decisions, run_id)


def build_namespace_peak_contributor_rows(collection, run_id: str) -> List[tuple]:
    """Build all contributor rows without collapsing them to one owner."""
    payloads = getattr(collection, 'namespace_peak_decisions', None) or []
    if not payloads:
        return []
    decisions = [decision_from_dict(payload) for payload in payloads]
    return build_contributor_rows(decisions, run_id)


def _episode_timestamp(value: Any, label: str) -> datetime:
    return _coerce_datetime(value, label)


def build_peak_episode_rows(collection) -> List[tuple]:
    rows = []
    identities = set()
    for episode in getattr(collection, 'peak_episodes', None) or []:
        episode_id = str(episode.get('episode_id') or '')
        if not episode_id or episode_id in identities:
            raise PersistenceInvariantError(f'invalid or duplicate episode_id: {episode_id!r}')
        identities.add(episode_id)
        state = str(episode.get('state') or '')
        if state not in {'START', 'CONTINUATION', 'EXPANSION', 'ESCALATION', 'RECOVERY', 'RESOLVED', 'RECURRENCE'}:
            raise PersistenceInvariantError(f'invalid episode state: {state}')
        confidence = str(episode.get('diagnosis_confidence') or 'low')
        if confidence not in {'low', 'medium', 'high'}:
            raise PersistenceInvariantError(f'invalid episode confidence: {confidence}')
        first_window = _episode_timestamp(
            episode.get('first_window_start_utc'), 'episode.first_window_start_utc'
        )
        last_window = _episode_timestamp(
            episode.get('last_window_start_utc'), 'episode.last_window_start_utc'
        )
        resolved_at = (
            _episode_timestamp(episode.get('resolved_at_utc'), 'episode.resolved_at_utc')
            if episode.get('resolved_at_utc') else None
        )
        rows.append((
            episode_id,
            str(episode.get('stream_key') or ''),
            str(episode.get('cause_signature') or '') or None,
            str(episode.get('cause_signature_version') or CAUSE_SIGNATURE_VERSION),
            state,
            first_window,
            last_window,
            resolved_at,
            int(episode.get('current_raw_error_lines') or 0),
            int(episode.get('cumulative_raw_error_lines') or 0),
            episode.get('current_operation_occurrences'),
            episode.get('cumulative_operation_occurrences'),
            confidence,
            json.dumps(sorted(episode.get('active_namespaces') or [])),
            json.dumps(sorted(episode.get('material_change_reasons') or [])),
            int(episode.get('non_peak_windows') or 0),
            episode.get('previous_episode_id') or None,
        ))
    return sorted(rows, key=lambda row: row[0])


def build_peak_episode_window_rows(collection) -> List[tuple]:
    rows = []
    identities = set()
    for transition in getattr(collection, 'peak_episode_transitions', None) or []:
        identity = (
            str(transition.get('episode_id') or ''),
            str(transition.get('window_decision_id') or ''),
            str(transition.get('cause_signature') or ''),
        )
        if not all(identity) or identity in identities:
            raise PersistenceInvariantError(f'invalid or duplicate episode window: {identity}')
        identities.add(identity)
        confidence = str(transition.get('confidence') or 'low')
        if confidence not in {'low', 'medium', 'high'}:
            raise PersistenceInvariantError(f'invalid episode-window confidence: {confidence}')
        state = str(transition.get('state') or '')
        if state not in {'START', 'CONTINUATION', 'EXPANSION', 'ESCALATION', 'RECOVERY', 'RESOLVED', 'RECURRENCE'}:
            raise PersistenceInvariantError(f'invalid episode-window state: {state}')
        rows.append((
            identity[0],
            identity[1],
            identity[2],
            CAUSE_SIGNATURE_VERSION,
            state,
            str(transition.get('correlation_method') or 'unknown'),
            str(transition.get('correlation_version') or 'unknown'),
            confidence,
            int(transition.get('allocated_raw_error_lines') or 0),
            int(transition.get('unexplained_raw_lines') or 0),
            json.dumps(sorted(transition.get('contributor_fingerprints') or [])),
            json.dumps(sorted(transition.get('material_change_reasons') or [])),
        ))
    return sorted(rows, key=lambda row: (row[0], row[1], row[2]))


def build_peak_episode_transition_rows(collection) -> List[tuple]:
    rows = []
    identities = set()
    for transition in getattr(collection, 'peak_episode_transitions', None) or []:
        identity = (
            str(transition.get('episode_id') or ''),
            str(transition.get('window_decision_id') or ''),
            str(transition.get('state') or ''),
        )
        if not all(identity) or identity in identities:
            raise PersistenceInvariantError(f'invalid or duplicate episode transition: {identity}')
        identities.add(identity)
        rows.append((
            identity[0],
            identity[1],
            transition.get('previous_state'),
            identity[2],
            ','.join(transition.get('material_change_reasons') or ())
            or str(transition.get('correlation_method') or 'event_time_transition'),
            transition.get('previous_raw_error_lines'),
            int(transition.get('current_raw_error_lines') or 0),
            int(transition.get('cumulative_raw_error_lines') or 0),
        ))
    return sorted(rows, key=lambda row: (row[0], row[1], row[3]))


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


def build_cause_family_rows(
    collection,
    run_id: str,
    window_start: datetime,
) -> List[tuple]:
    analysis = getattr(collection, 'cause_analysis', None)
    if analysis is None:
        return []

    try:
        analysis.validate()
    except ValueError as error:
        raise PersistenceInvariantError(str(error)) from error

    source_count = int(analysis.source_raw_error_lines)
    processed_count = int(collection.input_records)
    if source_count != processed_count:
        raise PersistenceInvariantError(
            'cause-family source count does not match processed count: '
            f'cause_families={source_count}, processed={processed_count}'
        )

    rows = []
    signatures = set()
    valid_assessments = {
        'technical_failure',
        'business_rejection',
        'expected_outcome_logged_as_error',
        'unknown',
    }
    valid_confidences = {'low', 'medium', 'high'}
    for family in analysis.families:
        signature = str(family.signature or '')
        if not signature or signature in signatures:
            raise PersistenceInvariantError(
                f'invalid or duplicate cause signature: {signature!r}'
            )
        signatures.add(signature)

        raw_lines = int(family.raw_error_lines)
        traced_lines = int(family.traced_error_lines)
        unsegmented_lines = int(family.unsegmented_error_lines)
        if raw_lines <= 0 or traced_lines < 0 or unsegmented_lines < 0:
            raise PersistenceInvariantError(
                f'invalid cause-family counts for {signature}'
            )
        if traced_lines + unsegmented_lines != raw_lines:
            raise PersistenceInvariantError(
                f'cause-family coverage does not reconcile for {signature}'
            )
        if family.assessment not in valid_assessments:
            raise PersistenceInvariantError(
                f'invalid cause-family assessment: {family.assessment}'
            )
        if family.confidence not in valid_confidences:
            raise PersistenceInvariantError(
                f'invalid cause-family confidence: {family.confidence}'
            )

        unique_operations = (
            int(family.unique_operations)
            if family.unique_operations is not None else None
        )
        trace_ids = [str(trace_id) for trace_id in family.trace_ids if trace_id]
        if unique_operations is not None and unique_operations < len(trace_ids):
            raise PersistenceInvariantError(
                f'cause-family operation count is smaller than represented trace IDs for {signature}'
            )
        operation_count_method = str(family.operation_count_method or '')
        operation_count_confidence = str(family.operation_count_confidence or '')
        if operation_count_method not in {'root_span', 'trace_id', 'mixed', 'unavailable'}:
            raise PersistenceInvariantError(
                f'invalid operation-count method for {signature}: {operation_count_method}'
            )
        if operation_count_confidence not in valid_confidences:
            raise PersistenceInvariantError(
                f'invalid operation-count confidence for {signature}: '
                f'{operation_count_confidence}'
            )
        if unique_operations is None and operation_count_method != 'unavailable':
            raise PersistenceInvariantError(
                f'unknown operation count must use unavailable method for {signature}'
            )
        if unique_operations is not None and operation_count_method == 'unavailable':
            raise PersistenceInvariantError(
                f'known operation count cannot use unavailable method for {signature}'
            )
        for label, counts in (
            ('application', family.app_counts),
            ('namespace', family.namespace_counts),
        ):
            normalized_counts = [int(value or 0) for value in counts.values()]
            if any(value < 0 for value in normalized_counts):
                raise PersistenceInvariantError(
                    f'negative {label} count for cause family {signature}'
                )
            if sum(normalized_counts) > raw_lines:
                raise PersistenceInvariantError(
                    f'{label} counts exceed raw lines for cause family {signature}'
                )

        rows.append((
            run_id,
            window_start,
            signature,
            CAUSE_SIGNATURE_VERSION,
            str(family.canonical_cause or 'Unknown cause')[:4000],
            str(family.root_app or 'unknown-app')[:255],
            str(family.operation or 'unknown-operation')[:255],
            family.outward_status,
            family.assessment,
            family.confidence,
            raw_lines,
            traced_lines,
            unsegmented_lines,
            unique_operations,
            family.amplification,
            json.dumps(family.app_counts, sort_keys=True),
            json.dumps(family.namespace_counts, sort_keys=True),
            str(family.representative_trace_id or ''),
            json.dumps(trace_ids),
            operation_count_method,
            operation_count_confidence,
            str(family.operation_count_reason or '')[:2000],
            str(family.next_action or '')[:4000],
        ))

    if sum(row[10] for row in rows) != source_count:
        raise PersistenceInvariantError(
            'cause-family rows do not reconcile to their source count'
        )
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
    connection: Optional[Any] = None,
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
    cause_family_rows = build_cause_family_rows(collection, run_id, window_start)
    namespace_peak_decision_rows = build_namespace_peak_decision_rows(collection, run_id)
    namespace_peak_contributor_rows = build_namespace_peak_contributor_rows(collection, run_id)
    peak_episode_rows = build_peak_episode_rows(collection)
    peak_episode_window_rows = build_peak_episode_window_rows(collection)
    peak_episode_transition_rows = build_peak_episode_transition_rows(collection)
    execute_values_fn = execute_values_fn or _default_execute_values

    owns_connection = connection is None
    connection = connection or connection_factory()
    cursor = connection.cursor()
    running_committed = False
    savepoint_name = 'peak_run_persistence'
    try:
        stream_keys = {
            str(row[2])
            for row in namespace_peak_decision_rows
            if row[2]
        }
        stream_keys.update(
            str(row[1])
            for row in peak_episode_rows
            if row[1]
        )
        if owns_connection:
            for stream_key in sorted(stream_keys):
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (stream_key,),
                )
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
        if owns_connection:
            connection.commit()
        else:
            cursor.execute(f'SAVEPOINT {savepoint_name}')
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

        if namespace_peak_decision_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.namespace_peak_decisions
                    (run_id, window_decision_id, stream_key, signal_namespace,
                     window_start_utc, window_end_utc, detector_version,
                     threshold_snapshot_id, namespace_raw_lines, p93_threshold,
                     cap_threshold, effective_threshold, triggered_by, is_peak,
                     verdict_reason, diagnosis_status, contract_hash, peak_identifier)
                VALUES %s
                ON CONFLICT (window_decision_id)
                DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    stream_key = EXCLUDED.stream_key,
                    signal_namespace = EXCLUDED.signal_namespace,
                    window_start_utc = EXCLUDED.window_start_utc,
                    window_end_utc = EXCLUDED.window_end_utc,
                    detector_version = EXCLUDED.detector_version,
                    threshold_snapshot_id = EXCLUDED.threshold_snapshot_id,
                    namespace_raw_lines = EXCLUDED.namespace_raw_lines,
                    p93_threshold = EXCLUDED.p93_threshold,
                    cap_threshold = EXCLUDED.cap_threshold,
                    effective_threshold = EXCLUDED.effective_threshold,
                    triggered_by = EXCLUDED.triggered_by,
                    is_peak = EXCLUDED.is_peak,
                    verdict_reason = EXCLUDED.verdict_reason,
                    diagnosis_status = EXCLUDED.diagnosis_status,
                    contract_hash = EXCLUDED.contract_hash,
                    peak_identifier = EXCLUDED.peak_identifier
            """, namespace_peak_decision_rows, page_size=1000)

        if namespace_peak_contributor_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.namespace_peak_contributors
                    (run_id, window_decision_id, fingerprint, error_type,
                     normalized_message, contribution, baseline, threshold,
                     anomaly_score, method, is_anomalous, apps)
                VALUES %s
                ON CONFLICT (window_decision_id, fingerprint)
                DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    error_type = EXCLUDED.error_type,
                    normalized_message = EXCLUDED.normalized_message,
                    contribution = EXCLUDED.contribution,
                    baseline = EXCLUDED.baseline,
                    threshold = EXCLUDED.threshold,
                    anomaly_score = EXCLUDED.anomaly_score,
                    method = EXCLUDED.method,
                    is_anomalous = EXCLUDED.is_anomalous,
                    apps = EXCLUDED.apps
            """, namespace_peak_contributor_rows, page_size=1000)

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

        if cause_family_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.cause_family_facts
                    (run_id, window_start, cause_signature, signature_version,
                     canonical_cause, root_application, operation, outward_status,
                     assessment, confidence, raw_error_lines, traced_error_lines,
                     unsegmented_error_lines, unique_operations, amplification,
                     app_counts, namespace_counts, representative_trace_id,
                     trace_ids, operation_count_method,
                     operation_count_confidence, operation_count_reason,
                     next_action)
                VALUES %s
                ON CONFLICT (run_id, cause_signature)
                DO UPDATE SET
                    signature_version = EXCLUDED.signature_version,
                    canonical_cause = EXCLUDED.canonical_cause,
                    root_application = EXCLUDED.root_application,
                    operation = EXCLUDED.operation,
                    outward_status = EXCLUDED.outward_status,
                    assessment = EXCLUDED.assessment,
                    confidence = EXCLUDED.confidence,
                    raw_error_lines = EXCLUDED.raw_error_lines,
                    traced_error_lines = EXCLUDED.traced_error_lines,
                    unsegmented_error_lines = EXCLUDED.unsegmented_error_lines,
                    unique_operations = EXCLUDED.unique_operations,
                    amplification = EXCLUDED.amplification,
                    app_counts = EXCLUDED.app_counts,
                    namespace_counts = EXCLUDED.namespace_counts,
                    representative_trace_id = EXCLUDED.representative_trace_id,
                    trace_ids = EXCLUDED.trace_ids,
                    operation_count_method = EXCLUDED.operation_count_method,
                    operation_count_confidence = EXCLUDED.operation_count_confidence,
                    operation_count_reason = EXCLUDED.operation_count_reason,
                    next_action = EXCLUDED.next_action
            """, cause_family_rows, page_size=1000)

        if peak_episode_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.peak_episodes
                    (episode_id, stream_key, cause_signature, signature_version,
                     state, first_window_start_utc, last_window_start_utc,
                     resolved_at_utc, current_raw_error_lines,
                     cumulative_raw_error_lines, current_operation_occurrences,
                     cumulative_operation_occurrences, diagnosis_confidence,
                     active_namespaces, material_change_reasons, non_peak_windows,
                     previous_episode_id)
                VALUES %s
                ON CONFLICT (episode_id)
                DO UPDATE SET
                    state = EXCLUDED.state,
                    last_window_start_utc = EXCLUDED.last_window_start_utc,
                    resolved_at_utc = EXCLUDED.resolved_at_utc,
                    current_raw_error_lines = EXCLUDED.current_raw_error_lines,
                    cumulative_raw_error_lines = EXCLUDED.cumulative_raw_error_lines,
                    current_operation_occurrences = EXCLUDED.current_operation_occurrences,
                    cumulative_operation_occurrences = EXCLUDED.cumulative_operation_occurrences,
                    diagnosis_confidence = EXCLUDED.diagnosis_confidence,
                    active_namespaces = EXCLUDED.active_namespaces,
                    material_change_reasons = EXCLUDED.material_change_reasons,
                    non_peak_windows = EXCLUDED.non_peak_windows,
                    previous_episode_id = EXCLUDED.previous_episode_id,
                    updated_at = NOW()
            """, peak_episode_rows, page_size=1000)

        if peak_episode_window_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.peak_episode_windows
                    (episode_id, window_decision_id, cause_signature,
                     signature_version, transition_state, correlation_method,
                     correlation_version, correlation_confidence,
                     allocated_raw_error_lines, unexplained_raw_lines,
                     contributor_fingerprints, material_change_reasons)
                VALUES %s
                ON CONFLICT (episode_id, window_decision_id, cause_signature)
                DO UPDATE SET
                    transition_state = EXCLUDED.transition_state,
                    correlation_method = EXCLUDED.correlation_method,
                    correlation_version = EXCLUDED.correlation_version,
                    correlation_confidence = EXCLUDED.correlation_confidence,
                    allocated_raw_error_lines = EXCLUDED.allocated_raw_error_lines,
                    unexplained_raw_lines = EXCLUDED.unexplained_raw_lines,
                    contributor_fingerprints = EXCLUDED.contributor_fingerprints,
                    material_change_reasons = EXCLUDED.material_change_reasons
            """, peak_episode_window_rows, page_size=1000)

        if peak_episode_transition_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.peak_episode_transitions
                    (episode_id, window_decision_id, previous_state, next_state,
                     transition_reason, previous_raw_error_lines,
                     current_raw_error_lines, cumulative_raw_error_lines)
                VALUES %s
                ON CONFLICT (episode_id, window_decision_id, next_state)
                DO NOTHING
            """, peak_episode_transition_rows, page_size=1000)

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
        cursor.execute(
            "SELECT COUNT(*), COALESCE(SUM(raw_error_lines), 0) "
            "FROM ailog_peak.cause_family_facts WHERE run_id = %s",
            (run_id,),
        )
        stored_cause_rows, stored_cause_events = cursor.fetchone()
        if namespace_peak_decision_rows:
            cursor.execute(
                "SELECT COUNT(*) FROM ailog_peak.namespace_peak_decisions "
                "WHERE run_id = %s",
                (run_id,),
            )
            stored_decision_rows = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM ailog_peak.namespace_peak_contributors "
                "WHERE run_id = %s",
                (run_id,),
            )
            stored_contributor_rows = int(cursor.fetchone()[0])
        else:
            stored_decision_rows = 0
            stored_contributor_rows = 0
        if peak_episode_rows:
            cursor.execute(
                "SELECT COUNT(*) FROM ailog_peak.peak_episodes WHERE episode_id IN "
                "(SELECT DISTINCT episode_id FROM ailog_peak.peak_episode_windows "
                "WHERE window_decision_id IN (SELECT window_decision_id FROM "
                "ailog_peak.namespace_peak_decisions WHERE run_id = %s))",
                (run_id,),
            )
            stored_episode_rows = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM ailog_peak.peak_episode_windows WHERE "
                "window_decision_id IN (SELECT window_decision_id FROM "
                "ailog_peak.namespace_peak_decisions WHERE run_id = %s)",
                (run_id,),
            )
            stored_episode_window_rows = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM ailog_peak.peak_episode_transitions WHERE "
                "window_decision_id IN (SELECT window_decision_id FROM "
                "ailog_peak.namespace_peak_decisions WHERE run_id = %s)",
                (run_id,),
            )
            stored_episode_transition_rows = int(cursor.fetchone()[0])
        else:
            stored_episode_rows = 0
            stored_episode_window_rows = 0
            stored_episode_transition_rows = 0
        stored = (
            int(stored_fact_rows),
            int(stored_fact_events),
            int(stored_namespace_rows),
            int(stored_namespace_events),
            int(stored_incident_rows),
            int(stored_detection_rows),
            int(stored_cause_rows),
            int(stored_cause_events),
            stored_decision_rows,
            stored_contributor_rows,
            stored_episode_rows,
            stored_episode_window_rows,
            stored_episode_transition_rows,
        )
        expected_stored = (
            len(error_kind_rows),
            persisted_event_count,
            len(namespace_rows),
            persisted_event_count,
            len(incident_rows),
            len(detection_rows),
            len(cause_family_rows),
            int(getattr(getattr(collection, 'cause_analysis', None), 'source_raw_error_lines', 0)),
            len(namespace_peak_decision_rows),
            len(namespace_peak_contributor_rows),
            len(peak_episode_rows),
            len(peak_episode_window_rows),
            len(peak_episode_transition_rows),
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
        if owns_connection:
            connection.commit()
        return {
            'persisted_events': persisted_event_count,
            'fact_rows': len(error_kind_rows),
            'namespace_rows': len(namespace_rows),
            'incident_rows': len(incident_rows),
            'detection_rows': len(detection_rows),
            'cause_family_rows': len(cause_family_rows),
            'namespace_peak_decision_rows': len(namespace_peak_decision_rows),
            'namespace_peak_contributor_rows': len(namespace_peak_contributor_rows),
            'peak_episode_rows': len(peak_episode_rows),
            'peak_episode_window_rows': len(peak_episode_window_rows),
            'peak_episode_transition_rows': len(peak_episode_transition_rows),
        }
    except Exception as exc:
        if owns_connection:
            connection.rollback()
        if running_committed:
            try:
                if not owns_connection:
                    cursor.execute(f'ROLLBACK TO SAVEPOINT {savepoint_name}')
                cursor.execute(
                    """
                    UPDATE ailog_peak.analysis_runs
                    SET status = 'failed', completed_at = NOW(),
                        error_code = %s, error_message = %s
                    WHERE run_id = %s AND status = 'running'
                    """,
                    (exc.__class__.__name__, str(exc)[:2000], run_id),
                )
                if owns_connection:
                    connection.commit()
            except Exception:
                connection.rollback()
        raise
    finally:
        cursor.close()
        if owns_connection:
            connection.close()