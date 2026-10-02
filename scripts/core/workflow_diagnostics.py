"""Independent, fail-closed workflow lifecycle diagnostic orchestration."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List

try:
    from analysis.workflow_lifecycle import (
        LifecycleFetchStats,
        analyze_workflow_events,
        parse_lifecycle_event,
    )
    from core.fetch_lifecycle import fetch_lifecycle_context, probe_lifecycle
    from core.workflow_persistence import persist_workflow_run
except ModuleNotFoundError:
    from scripts.analysis.workflow_lifecycle import (
        LifecycleFetchStats,
        analyze_workflow_events,
        parse_lifecycle_event,
    )
    from scripts.core.fetch_lifecycle import fetch_lifecycle_context, probe_lifecycle
    from scripts.core.workflow_persistence import persist_workflow_run


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _partial_probe_stats(probe) -> LifecycleFetchStats:
    return LifecycleFetchStats(
        source_cluster=os.getenv("ES_HOST", "unknown"),
        source_index=os.getenv("ES_INDEX", "unknown"),
        scope="lifecycle-probe",
        expected_count=probe.expected_count,
        fetched_count=probe.fetched_count,
        processed_count=0,
        query_count=1,
        complete=False,
        truncated=probe.truncated,
        reason=probe.reason or "lifecycle probe did not yield a complete candidate scope",
    )


def _format_alert(incident) -> str:
    identity = incident.identity
    predecessor_ids = ", ".join(incident.predecessor_event_ids) or "none"
    completed_ids = ", ".join(incident.predecessor_completed_event_ids) or "none"
    pods = ", ".join(
        f"{pod}({count})" for pod, count in sorted(
            incident.pod_counts.items(), key=lambda item: (-item[1], item[0])
        )
    ) or "unknown"
    return "\n".join([
        "Workflow lifecycle hot loop detected",
        f"Scope: {identity.topic} / {identity.namespace}",
        f"Queue event: {identity.queue_event_id}",
        f"Attempts: {incident.attempt_count} over {incident.duration_seconds:.1f}s "
        f"({incident.attempts_per_second:.2f}/s)",
        f"PROCESSING -> REGISTERED: {incident.processing_to_registered_count}",
        f"Without delay with stale due time: {incident.stale_delay_count}",
        f"Predecessors: {predecessor_ids}",
        f"Completed predecessors: {completed_ids}",
        f"Pods: {pods}",
        f"Evidence: {', '.join(incident.evidence_es_ids[:5])}",
    ])


def _get_email_notifier():
    try:
        from core.email_notifier import EmailNotifier
    except ModuleNotFoundError:
        from scripts.core.email_notifier import EmailNotifier
    return EmailNotifier()


def run_workflow_lifecycle_diagnostics(
    window_start: datetime,
    window_end: datetime,
    connection_factory: Callable[[], Any],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run lifecycle diagnostics without relying on ERROR records or trace IDs.

    Lifecycle failures never trigger an alert. They are persisted as `partial`
    when enough information exists for an audit record, while the regular ERROR
    pipeline remains free to continue its independent work.
    """
    result: Dict[str, Any] = {
        "status": "disabled",
        "probe": {},
        "fetch": {},
        "incidents": [],
        "alerted": [],
    }
    if not _enabled("LIFECYCLE_ANALYSIS_ENABLED"):
        return result

    date_from = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_to = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    probe = probe_lifecycle(date_from, date_to)
    result["probe"] = {
        "scope_count": len(probe.scopes),
        "expected_count": probe.expected_count,
        "fetched_count": probe.fetched_count,
        "truncated": probe.truncated,
        "reason": probe.reason,
    }
    run_id = f"lifecycle-{window_start.strftime('%Y%m%d-%H%M')}-{uuid.uuid4().hex[:8]}"

    if not probe.scopes:
        if probe.expected_count or probe.reason or probe.truncated:
            stats = _partial_probe_stats(probe)
            result["fetch"] = stats.to_dict()
            if not dry_run:
                try:
                    result["persistence"] = persist_workflow_run(
                        connection_factory, run_id, window_start, window_end, stats, []
                    )
                except Exception as error:
                    result.update(status="failed", error=f"Lifecycle probe persistence failed: {error}")
                    return result
            result["status"] = "partial"
            return result
        result["status"] = "no_candidates"
        return result

    documents, stats = fetch_lifecycle_context(probe.scopes, date_from, date_to)
    if probe.truncated:
        stats.complete = False
        stats.truncated = True
        probe_reason = probe.reason or "lifecycle probe scope discovery was capped"
        stats.reason = "; ".join(
            part for part in (stats.reason, probe_reason) if part
        )
    events = [
        event
        for document in documents
        if (event := parse_lifecycle_event(document, stats.source_cluster)) is not None
    ]
    stats.processed_count = len(events)
    min_retries = int(os.getenv("LIFECYCLE_MIN_RETRIES", "3"))
    if min_retries < 2:
        raise ValueError("LIFECYCLE_MIN_RETRIES must be at least 2")
    incidents = analyze_workflow_events(
        events, stats, window_start, window_end, min_retries=min_retries
    )
    result["fetch"] = stats.to_dict()
    result["incidents"] = [incident.to_dict() for incident in incidents]

    if dry_run:
        result["status"] = "dry_run_complete" if stats.complete else "dry_run_partial"
        return result

    try:
        persistence = persist_workflow_run(
            connection_factory, run_id, window_start, window_end, stats, incidents
        )
    except Exception as error:
        result.update(status="failed", error=f"Lifecycle persistence failed: {error}")
        return result
    result["persistence"] = persistence
    result["status"] = persistence["status"]

    if not stats.complete or not _enabled("LIFECYCLE_ALERT_ENABLED"):
        return result
    eligible = [
        incident for incident in incidents
        if incident.identity.key in set(persistence["alert_eligible"])
    ]
    if not eligible:
        return result
    try:
        notifier = _get_email_notifier()
        if notifier.is_enabled():
            for incident in eligible:
                if notifier.send_workflow_lifecycle_alert(_format_alert(incident)):
                    result["alerted"].append(incident.identity.key)
    except Exception as error:
        result["alert_error"] = str(error)
    return result