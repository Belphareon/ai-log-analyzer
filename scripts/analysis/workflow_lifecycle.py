"""Fail-closed diagnostics for queue-event lifecycle loops."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo


_QUEUE_ID_RE = re.compile(r"queueEventId=(?P<queue_id>[A-Za-z0-9_-]+)")
_THIS_EVENT_RE = re.compile(r"\bthis event (?P<queue_id>[A-Za-z0-9_-]+)\b", re.I)
_EVENT_ID_RE = re.compile(
    r"\bevent\s+[A-Z][A-Z_]+\((?P<queue_id>[A-Za-z0-9_-]+)\)", re.I
)
_EVENT_TRANSITION_RE = re.compile(
    r"\b(?:event\s+[A-Z_]+\(|event\s+[^\s]+\()(?P<queue_id>[A-Za-z0-9_-]+)\)"
    r".*?\bfrom (?P<from_state>[A-Z_]+) to (?P<to_state>[A-Z_]+)\b",
    re.I,
)
_DELAYED_TO_RE = re.compile(r"\bdelayedTo=(?P<value>[^,}\s]+)")
_CREATED_AT_RE = re.compile(r"\bcreatedAt=(?P<value>[^,}\s]+)")
_TYPE_RE = re.compile(r"\btype=(?P<value>[A-Z_]+)")
_EVENT_TYPE_RE = re.compile(r"\bevent (?P<value>[A-Z_]+)\(")
_PREDECESSOR_BLOCK_RE = re.compile(r"\bPrior events are \[(?P<events>.*?)]\.", re.I)
_PREDECESSOR_ID_RE = re.compile(r"\b(?P<queue_id>[A-Za-z0-9_-]+)\s+[A-Z][A-Z_]+/")
_STATUS_RE = re.compile(r"\bstatus=(?P<value>[A-Z_]+)")
_LIFECYCLE_TIMEZONE = ZoneInfo("Europe/Prague")


def _source_value(source: Dict[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        if path in source and source[path] is not None:
            return source[path]
        current: Any = source
        for part in path.split('.'):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return default


def _parse_datetime(value: Any, naive_timezone=timezone.utc) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=naive_timezone)
    return parsed


@dataclass(frozen=True)
class WorkflowIdentity:
    topic: str
    namespace: str
    queue_event_id: str

    @property
    def key(self) -> str:
        return f"{self.topic}|{self.namespace}|{self.queue_event_id}"


@dataclass
class LifecycleFetchStats:
    source_cluster: str
    source_index: str
    scope: str
    expected_count: Optional[int] = None
    fetched_count: int = 0
    processed_count: int = 0
    query_count: int = 0
    complete: bool = False
    truncated: bool = False
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_cluster": self.source_cluster,
            "source_index": self.source_index,
            "scope": self.scope,
            "expected_count": self.expected_count,
            "fetched_count": self.fetched_count,
            "processed_count": self.processed_count,
            "query_count": self.query_count,
            "complete": self.complete,
            "truncated": self.truncated,
            "reason": self.reason,
        }


@dataclass
class LifecycleEvent:
    identity: WorkflowIdentity
    observed_at: datetime
    es_index: str
    es_id: str
    source_cluster: str
    message: str
    event_kind: str
    level: str = ""
    application: str = "unknown"
    pod_name: str = "unknown"
    trace_id: str = ""
    event_type: str = ""
    state_from: str = ""
    state_to: str = ""
    delayed_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
    predecessor_event_ids: List[str] = field(default_factory=list)
    without_delaying: bool = False


@dataclass
class WorkflowIncident:
    identity: WorkflowIdentity
    source_cluster: str
    source_indices: List[str]
    fetch_window_start: datetime
    fetch_window_end: datetime
    fetch_stats: LifecycleFetchStats
    first_seen: datetime
    last_seen: datetime
    attempt_count: int = 0
    processing_to_registered_count: int = 0
    without_delaying_count: int = 0
    stale_delay_count: int = 0
    predecessor_event_ids: List[str] = field(default_factory=list)
    predecessor_completed_event_ids: List[str] = field(default_factory=list)
    pod_counts: Dict[str, int] = field(default_factory=dict)
    evidence_es_ids: List[str] = field(default_factory=list)
    evidence: List[LifecycleEvent] = field(default_factory=list)
    confidence: str = "low"
    alert_eligible: bool = False
    loop_detected: bool = False
    incomplete: bool = False

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.last_seen - self.first_seen).total_seconds())

    @property
    def attempts_per_second(self) -> float:
        duration = self.duration_seconds
        return self.attempt_count / duration if duration else float(self.attempt_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "topic": self.identity.topic,
                "namespace": self.identity.namespace,
                "queue_event_id": self.identity.queue_event_id,
            },
            "source_cluster": self.source_cluster,
            "source_indices": list(self.source_indices),
            "fetch_window_start": self.fetch_window_start.isoformat(),
            "fetch_window_end": self.fetch_window_end.isoformat(),
            "fetch_stats": self.fetch_stats.to_dict(),
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "duration_seconds": round(self.duration_seconds, 3),
            "attempt_count": self.attempt_count,
            "attempts_per_second": round(self.attempts_per_second, 3),
            "processing_to_registered_count": self.processing_to_registered_count,
            "without_delaying_count": self.without_delaying_count,
            "stale_delay_count": self.stale_delay_count,
            "predecessor_event_ids": list(self.predecessor_event_ids),
            "predecessor_completed_event_ids": list(self.predecessor_completed_event_ids),
            "pod_counts": dict(self.pod_counts),
            "evidence_es_ids": list(self.evidence_es_ids),
            "confidence": self.confidence,
            "alert_eligible": self.alert_eligible,
            "loop_detected": self.loop_detected,
            "incomplete": self.incomplete,
        }


def _extract_queue_id(message: str) -> Optional[str]:
    for pattern in (_QUEUE_ID_RE, _THIS_EVENT_RE, _EVENT_ID_RE, _EVENT_TRANSITION_RE):
        match = pattern.search(message)
        if match:
            return match.group("queue_id")
    return None


def _event_kind(message: str, state_from: str, state_to: str) -> str:
    lowered = message.lower()
    if "start processing of queued event" in lowered or "will be processing" in lowered:
        return "processing_started"
    if "prior unprocessed events" in lowered:
        return "predecessor_blocked"
    if "back to registered status, without delaying" in lowered:
        return "registered_without_delay"
    if state_from == "PROCESSING" and state_to == "REGISTERED":
        return "processing_to_registered"
    if state_to == "COMPLETED" or "finished to status statuswithdescription(status=completed" in lowered:
        return "completed"
    return "lifecycle_observation"


def parse_lifecycle_event(
    document: Dict[str, Any],
    source_cluster: str,
) -> Optional[LifecycleEvent]:
    source = document.get("_source", document)
    message = str(_source_value(source, "message", default="") or "")
    queue_event_id = _extract_queue_id(message)
    if not queue_event_id:
        return None

    observed_at = _parse_datetime(_source_value(source, "@timestamp", "timestamp"))
    topic = str(_source_value(source, "topic", default="") or "")
    namespace = str(_source_value(source, "kubernetes.namespace", "namespace", default="") or "")
    if not observed_at or not topic or not namespace:
        return None

    transition = _EVENT_TRANSITION_RE.search(message)
    state_from = transition.group("from_state").upper() if transition else ""
    state_to = transition.group("to_state").upper() if transition else ""
    if not state_to:
        status = _STATUS_RE.search(message)
        state_to = status.group("value").upper() if status else ""

    predecessor_event_ids: List[str] = []
    blocked = _PREDECESSOR_BLOCK_RE.search(message)
    if blocked:
        predecessor_event_ids = list(dict.fromkeys(
            match.group("queue_id")
            for match in _PREDECESSOR_ID_RE.finditer(blocked.group("events"))
            if match.group("queue_id") != queue_event_id
        ))

    event_type_match = _TYPE_RE.search(message) or _EVENT_TYPE_RE.search(message)
    delayed_match = _DELAYED_TO_RE.search(message)
    created_match = _CREATED_AT_RE.search(message)
    return LifecycleEvent(
        identity=WorkflowIdentity(topic, namespace, queue_event_id),
        observed_at=observed_at,
        es_index=str(document.get("_index") or ""),
        es_id=str(document.get("_id") or ""),
        source_cluster=source_cluster,
        message=message,
        event_kind=_event_kind(message, state_from, state_to),
        level=str(_source_value(source, "level", default="") or ""),
        application=str(_source_value(source, "application.name", "service.name", default="unknown") or "unknown"),
        pod_name=str(_source_value(source, "kubernetes.pod.name", default="unknown") or "unknown"),
        trace_id=str(_source_value(source, "traceId", "trace.id", default="") or ""),
        event_type=event_type_match.group("value") if event_type_match else "",
        state_from=state_from,
        state_to=state_to,
        # Queue payload timestamps omit an offset and are logged in Prague time.
        delayed_to=(
            _parse_datetime(delayed_match.group("value"), _LIFECYCLE_TIMEZONE)
            if delayed_match else None
        ),
        created_at=(
            _parse_datetime(created_match.group("value"), _LIFECYCLE_TIMEZONE)
            if created_match else None
        ),
        predecessor_event_ids=predecessor_event_ids,
        without_delaying="without delaying" in message.lower(),
    )


def analyze_workflow_events(
    events: Iterable[LifecycleEvent],
    fetch_stats: LifecycleFetchStats,
    fetch_window_start: datetime,
    fetch_window_end: datetime,
    min_retries: int = 3,
) -> List[WorkflowIncident]:
    by_identity: Dict[WorkflowIdentity, List[LifecycleEvent]] = defaultdict(list)
    for event in events:
        by_identity[event.identity].append(event)

    completed: Dict[WorkflowIdentity, datetime] = {}
    for identity, identity_events in by_identity.items():
        completed_at = [
            event.observed_at
            for event in identity_events
            if event.event_kind == "completed"
        ]
        if completed_at:
            completed[identity] = max(completed_at)

    incidents: List[WorkflowIncident] = []
    for identity, identity_events in sorted(by_identity.items(), key=lambda item: item[0].key):
        ordered = sorted(identity_events, key=lambda event: (event.observed_at, event.es_id))
        current_delayed_to: Optional[datetime] = None
        attempts = 0
        returns = 0
        without_delay = 0
        stale_delay = 0
        predecessor_ids: List[str] = []
        pod_counts: Counter = Counter()
        evidence_ids: List[str] = []
        for event in ordered:
            if event.delayed_to:
                current_delayed_to = event.delayed_to
            if event.event_kind == "processing_started":
                attempts += 1
            if event.event_kind == "processing_to_registered":
                returns += 1
            if event.without_delaying:
                without_delay += 1
                if current_delayed_to and current_delayed_to <= event.observed_at:
                    stale_delay += 1
            predecessor_ids.extend(event.predecessor_event_ids)
            pod_counts[event.pod_name] += 1
            if event.es_id and event.es_id not in evidence_ids and len(evidence_ids) < 50:
                evidence_ids.append(event.es_id)

        predecessor_ids = list(dict.fromkeys(predecessor_ids))
        predecessor_completed = []
        for predecessor_id in predecessor_ids:
            predecessor_identity = WorkflowIdentity(identity.topic, identity.namespace, predecessor_id)
            completed_at = completed.get(predecessor_identity)
            if completed_at and completed_at >= ordered[-1].observed_at:
                predecessor_completed.append(predecessor_id)

        loop_detected = (
            attempts >= min_retries
            and returns >= min_retries - 1
            and without_delay >= min_retries - 1
            and stale_delay >= min_retries - 1
        )
        complete_evidence = bool(fetch_stats.complete and not fetch_stats.truncated)
        if loop_detected and complete_evidence and predecessor_ids and predecessor_completed:
            confidence = "high"
        elif loop_detected and complete_evidence:
            confidence = "medium"
        elif loop_detected:
            confidence = "partial"
        else:
            confidence = "low"

        incidents.append(WorkflowIncident(
            identity=identity,
            source_cluster=ordered[0].source_cluster,
            source_indices=sorted({event.es_index for event in ordered if event.es_index}),
            fetch_window_start=fetch_window_start,
            fetch_window_end=fetch_window_end,
            fetch_stats=fetch_stats,
            first_seen=ordered[0].observed_at,
            last_seen=ordered[-1].observed_at,
            attempt_count=attempts,
            processing_to_registered_count=returns,
            without_delaying_count=without_delay,
            stale_delay_count=stale_delay,
            predecessor_event_ids=predecessor_ids,
            predecessor_completed_event_ids=predecessor_completed,
            pod_counts=dict(sorted(pod_counts.items())),
            evidence_es_ids=evidence_ids,
            evidence=ordered[:50],
            confidence=confidence,
            alert_eligible=confidence == "high",
            loop_detected=loop_detected,
            incomplete=not complete_evidence,
        ))
    return incidents