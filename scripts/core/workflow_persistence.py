"""Transactional persistence for complete and partial workflow lifecycle runs."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

try:
    from analysis.workflow_lifecycle import LifecycleFetchStats, WorkflowIncident
except ModuleNotFoundError:
    from scripts.analysis.workflow_lifecycle import LifecycleFetchStats, WorkflowIncident


class WorkflowPersistenceInvariantError(RuntimeError):
    """Raised when lifecycle persistence would violate the fail-closed contract."""


def _default_execute_values(cursor, statement: str, rows: Sequence[tuple], page_size: int) -> None:
    from psycopg2.extras import execute_values

    execute_values(cursor, statement, rows, page_size=page_size)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowPersistenceInvariantError(f"{label} must be timezone-aware")


def _run_status(stats: LifecycleFetchStats) -> str:
    if stats.complete and not stats.truncated and stats.expected_count == stats.fetched_count:
        return "complete"
    return "partial"


def _incident_rows(
    run_id: str,
    incidents: Iterable[WorkflowIncident],
    run_complete: bool,
) -> List[tuple]:
    rows = []
    identities = set()
    for incident in incidents:
        key = incident.identity.key
        if key in identities:
            raise WorkflowPersistenceInvariantError(f"duplicate workflow incident: {key}")
        identities.add(key)
        _require_aware(incident.first_seen, "incident.first_seen")
        _require_aware(incident.last_seen, "incident.last_seen")
        if incident.last_seen < incident.first_seen:
            raise WorkflowPersistenceInvariantError(f"workflow incident has negative duration: {key}")
        alert_eligible = bool(run_complete and incident.alert_eligible)
        rows.append((
            run_id,
            incident.identity.topic,
            incident.identity.namespace,
            incident.identity.queue_event_id,
            incident.source_cluster,
            json.dumps(incident.source_indices),
            incident.first_seen,
            incident.last_seen,
            incident.attempt_count,
            incident.processing_to_registered_count,
            incident.without_delaying_count,
            incident.stale_delay_count,
            json.dumps(incident.predecessor_event_ids),
            json.dumps(incident.predecessor_completed_event_ids),
            json.dumps(incident.pod_counts, sort_keys=True),
            incident.confidence,
            incident.loop_detected,
            alert_eligible,
            incident.incomplete or not run_complete,
        ))
    return rows


def _evidence_rows(run_id: str, incidents: Iterable[WorkflowIncident]) -> List[tuple]:
    rows = []
    identities = set()
    for incident in incidents:
        for event in incident.evidence:
            if not event.es_index or not event.es_id:
                continue
            key = (
                incident.identity.topic,
                incident.identity.namespace,
                incident.identity.queue_event_id,
                event.es_index,
                event.es_id,
            )
            if key in identities:
                continue
            identities.add(key)
            rows.append((
                run_id,
                incident.identity.topic,
                incident.identity.namespace,
                incident.identity.queue_event_id,
                event.es_index,
                event.es_id,
                event.observed_at,
                event.event_kind,
                event.pod_name,
                event.trace_id,
                event.message[:10000],
            ))
    return rows


def persist_workflow_run(
    connection_factory: Callable[[], Any],
    run_id: str,
    window_start: datetime,
    window_end: datetime,
    fetch_stats: LifecycleFetchStats,
    incidents: Sequence[WorkflowIncident],
    code_version: Optional[str] = None,
    execute_values_fn: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """Persist lifecycle evidence before alerting.

    Partial runs are audit records only.  The returned `alert_eligible` can be
    true only after the transaction commits a complete lifecycle run.
    """
    _require_aware(window_start, "window_start")
    _require_aware(window_end, "window_end")
    if window_end <= window_start:
        raise WorkflowPersistenceInvariantError("window_end must be after window_start")
    if not run_id:
        raise WorkflowPersistenceInvariantError("run_id is required")

    run_status = _run_status(fetch_stats)
    run_complete = run_status == "complete"
    incident_rows = _incident_rows(run_id, incidents, run_complete)
    evidence_rows = _evidence_rows(run_id, incidents)
    execute_values_fn = execute_values_fn or _default_execute_values
    connection = connection_factory()
    cursor = connection.cursor()
    running_committed = False
    try:
        cursor.execute(
            """
            INSERT INTO ailog_peak.workflow_lifecycle_runs
                (run_id, window_start, window_end, source_cluster, source_index,
                 scope, status, expected_count, fetched_count, processed_count,
                 query_count, truncated, reason, code_version)
            VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, window_start, window_end, fetch_stats.source_cluster,
                fetch_stats.source_index, fetch_stats.scope, fetch_stats.expected_count,
                fetch_stats.fetched_count, fetch_stats.processed_count,
                fetch_stats.query_count, fetch_stats.truncated, fetch_stats.reason,
                code_version or os.getenv("IMAGE_TAG", "unknown"),
            ),
        )
        connection.commit()
        running_committed = True

        if incident_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.workflow_lifecycle_incidents
                    (run_id, topic, namespace, queue_event_id, source_cluster,
                     source_indices, first_seen, last_seen, attempt_count,
                     processing_to_registered_count, without_delaying_count,
                     stale_delay_count, predecessor_event_ids,
                     predecessor_completed_event_ids, pod_counts, confidence,
                     loop_detected, alert_eligible, incomplete)
                VALUES %s
                ON CONFLICT (run_id, topic, namespace, queue_event_id)
                DO UPDATE SET
                    source_indices = EXCLUDED.source_indices,
                    first_seen = EXCLUDED.first_seen,
                    last_seen = EXCLUDED.last_seen,
                    attempt_count = EXCLUDED.attempt_count,
                    processing_to_registered_count = EXCLUDED.processing_to_registered_count,
                    without_delaying_count = EXCLUDED.without_delaying_count,
                    stale_delay_count = EXCLUDED.stale_delay_count,
                    predecessor_event_ids = EXCLUDED.predecessor_event_ids,
                    predecessor_completed_event_ids = EXCLUDED.predecessor_completed_event_ids,
                    pod_counts = EXCLUDED.pod_counts,
                    confidence = EXCLUDED.confidence,
                    loop_detected = EXCLUDED.loop_detected,
                    alert_eligible = EXCLUDED.alert_eligible,
                    incomplete = EXCLUDED.incomplete
            """, incident_rows, page_size=500)

        if evidence_rows:
            execute_values_fn(cursor, """
                INSERT INTO ailog_peak.workflow_lifecycle_evidence
                    (run_id, topic, namespace, queue_event_id, es_index, es_id,
                     observed_at, event_kind, pod_name, trace_id, message)
                VALUES %s
                ON CONFLICT (run_id, topic, namespace, queue_event_id, es_index, es_id)
                DO UPDATE SET
                    observed_at = EXCLUDED.observed_at,
                    event_kind = EXCLUDED.event_kind,
                    pod_name = EXCLUDED.pod_name,
                    trace_id = EXCLUDED.trace_id,
                    message = EXCLUDED.message
            """, evidence_rows, page_size=500)

        cursor.execute(
            """
            UPDATE ailog_peak.workflow_lifecycle_runs
            SET status = %s, completed_at = NOW()
            WHERE run_id = %s AND status = 'running'
            """,
            (run_status, run_id),
        )
        if cursor.rowcount != 1:
            raise WorkflowPersistenceInvariantError("workflow run was not completed exactly once")
        connection.commit()
        return {
            "run_id": run_id,
            "status": run_status,
            "incident_rows": len(incident_rows),
            "evidence_rows": len(evidence_rows),
            "alert_eligible": [
                incident.identity.key
                for incident in incidents
                if run_complete and incident.alert_eligible
            ],
        }
    except Exception as exc:
        connection.rollback()
        if running_committed:
            try:
                cursor.execute(
                    """
                    UPDATE ailog_peak.workflow_lifecycle_runs
                    SET status = 'failed', completed_at = NOW(), reason = %s
                    WHERE run_id = %s AND status = 'running'
                    """,
                    (str(exc)[:4000], run_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()