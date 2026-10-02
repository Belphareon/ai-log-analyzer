"""Build operator-facing cause families from peak alert evidence."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_WRAPPER_PATTERNS = (
    re.compile(r"\berror handled\b", re.IGNORECASE),
    re.compile(r"\bhandle fault\b", re.IGNORECASE),
    re.compile(r"\bgeneral error\b", re.IGNORECASE),
    re.compile(r"\ban unexpected error occurred\b", re.IGNORECASE),
)
_TECHNICAL_PATTERNS = (
    re.compile(r"optimisticlock", re.IGNORECASE),
    re.compile(r"timeout|timed out", re.IGNORECASE),
    re.compile(r"connection (?:refused|reset)", re.IGNORECASE),
    re.compile(r"deadlock|sql(?:exception|state)", re.IGNORECASE),
)
_BUSINESS_PATTERNS = (
    re.compile(r"\bnot found\b", re.IGNORECASE),
    re.compile(r"\bdoes not exist\b", re.IGNORECASE),
    re.compile(r"\bvalidation\b|\binvalid\b", re.IGNORECASE),
    re.compile(r"\baccess denied\b|accessdeniedexception", re.IGNORECASE),
)
_EXPECTED_PATTERNS = (
    re.compile(r"\bresult\s*[:=]\s*cancelled\b", re.IGNORECASE),
    re.compile(r"\bcancelled by (?:the )?user\b", re.IGNORECASE),
)
_STATUS_PATTERN = re.compile(
    r"(?:->|status(?:\s+code)?\s*[:=]?|http(?:\s+status)?\s*)\s*([1-5]\d{2})\b",
    re.IGNORECASE,
)
_OPERATION_PATTERN = re.compile(
    r"(?:[\w.$]+[#.])([A-Za-z][\w$]+)\s*(?:\([^)]*\))?\s*(?:->|$)"
)
_VOLATILE_VALUE_PATTERN = re.compile(
    r"\b(?:[0-9a-f]{16,}|\d{6,}|[0-9a-f]{8}-[0-9a-f-]{27,})\b",
    re.IGNORECASE,
)

CAUSE_SIGNATURE_VERSION = "operational_cause_v1"


@dataclass(frozen=True)
class OperationalCauseFamily:
    signature: str
    canonical_cause: str
    root_app: str
    operation: str
    outward_status: Optional[int]
    assessment: str
    confidence: str
    next_action: str
    raw_error_lines: int
    traced_error_lines: int
    unsegmented_error_lines: int
    unique_operations: Optional[int]
    amplification: Optional[float]
    app_counts: Dict[str, int]
    namespace_counts: Dict[str, int]
    representative_trace_id: str
    trace_ids: Tuple[str, ...]
    operation_count_method: str = "trace_id"
    operation_count_confidence: str = "medium"
    operation_count_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CauseFamilyAnalysis:
    families: Tuple[OperationalCauseFamily, ...]
    source_raw_error_lines: int
    segmented_error_lines: int
    unsegmented_error_lines: int
    unique_operations: Optional[int]

    def validate(self) -> None:
        for family in self.families:
            if (
                family.traced_error_lines + family.unsegmented_error_lines
                != family.raw_error_lines
            ):
                raise ValueError(
                    "cause-family coverage failed: "
                    f"signature={family.signature}, "
                    f"traced={family.traced_error_lines}, "
                    f"unsegmented={family.unsegmented_error_lines}, "
                    f"raw={family.raw_error_lines}"
                )
            if (
                family.unique_operations is not None
                and family.unique_operations < len(family.trace_ids)
            ):
                raise ValueError(
                    "cause-family operation count is smaller than trace evidence: "
                    f"signature={family.signature}"
                )
            if (
                family.unique_operations is None
                and family.operation_count_method != "unavailable"
            ):
                raise ValueError(
                    "unknown operation count must use unavailable method: "
                    f"signature={family.signature}"
                )
            if (
                family.unique_operations is not None
                and family.operation_count_method == "unavailable"
            ):
                raise ValueError(
                    "known operation count cannot use unavailable method: "
                    f"signature={family.signature}"
                )

        represented = sum(family.raw_error_lines for family in self.families)
        if represented != self.source_raw_error_lines:
            raise ValueError(
                "cause-family reconciliation failed: "
                f"represented={represented}, source={self.source_raw_error_lines}"
            )
        if self.segmented_error_lines + self.unsegmented_error_lines != self.source_raw_error_lines:
            raise ValueError(
                "trace coverage reconciliation failed: "
                f"segmented={self.segmented_error_lines}, "
                f"unsegmented={self.unsegmented_error_lines}, "
                f"source={self.source_raw_error_lines}"
            )
        traced_families = [
            family for family in self.families if family.traced_error_lines > 0
        ]
        expected_operations = (
            None
            if any(family.unique_operations is None for family in traced_families)
            else sum(family.unique_operations or 0 for family in traced_families)
        )
        if self.unique_operations != expected_operations:
            raise ValueError(
                "operation-count reconciliation failed: "
                f"reported={self.unique_operations}, expected={expected_operations}"
            )


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _is_wrapper(message: str) -> bool:
    return any(pattern.search(message) for pattern in _WRAPPER_PATTERNS)


def _candidate_messages(
    payload: Mapping[str, Any],
) -> Iterable[Tuple[str, str, str]]:
    root_cause = payload.get("root_cause") or {}
    if isinstance(root_cause, Mapping):
        yield (
            _clean_text(root_cause.get("message")),
            "root",
            _clean_text(root_cause.get("service")),
        )
    yield _clean_text(payload.get("root_cause_text")), "root", ""

    for step in payload.get("trace_steps", ()) or ():
        if isinstance(step, Mapping):
            yield (
                _clean_text(step.get("message")),
                "trace",
                _clean_text(step.get("app") or step.get("service")),
            )

    yield _clean_text(payload.get("behavior_text")), "behavior", ""
    yield _clean_text(payload.get("detail_message")), "behavior", ""
    yield _clean_text(payload.get("error_class")), "fallback", ""


def _message_score(message: str, source: str) -> Tuple[int, int]:
    if not message:
        return (-1000, 0)
    score = {"root": 40, "trace": 30, "behavior": 10, "fallback": 0}.get(source, 0)
    if _is_wrapper(message):
        score -= 80
    if any(pattern.search(message) for pattern in _TECHNICAL_PATTERNS):
        score += 45
    if any(pattern.search(message) for pattern in _BUSINESS_PATTERNS):
        score += 35
    if _STATUS_PATTERN.search(message):
        score += 5
    return (score, min(len(message), 500))


def _select_canonical_evidence(payload: Mapping[str, Any]) -> Tuple[str, str]:
    candidates = {
        (message, source, app)
        for message, source, app in _candidate_messages(payload)
        if message
    }
    if not candidates:
        return "Unknown cause", ""
    message, _source, app = max(
        candidates,
        key=lambda item: _message_score(item[0], item[1]),
    )
    return message, app


def select_canonical_cause(payload: Mapping[str, Any]) -> str:
    return _select_canonical_evidence(payload)[0]


def _root_app(payload: Mapping[str, Any]) -> str:
    root_cause = payload.get("root_cause") or {}
    if isinstance(root_cause, Mapping):
        service = _clean_text(root_cause.get("service"))
        if service and service != "?":
            return service
    app_counts = payload.get("app_counts") or payload.get("all_app_counts") or {}
    if isinstance(app_counts, Mapping) and app_counts:
        return str(max(app_counts.items(), key=lambda item: (int(item[1] or 0), item[0]))[0])
    return "unknown-app"


def _operation(messages: Sequence[str]) -> str:
    for message in messages:
        match = _OPERATION_PATTERN.search(message)
        if match:
            return match.group(1)
    return "unknown-operation"


def _outward_status(messages: Sequence[str]) -> Optional[int]:
    for message in messages:
        match = _STATUS_PATTERN.search(message)
        if match:
            return int(match.group(1))
    return None


def _assessment(messages: Sequence[str], status: Optional[int]) -> Tuple[str, str]:
    combined = " | ".join(messages)
    if any(pattern.search(combined) for pattern in _TECHNICAL_PATTERNS):
        return "technical_failure", "high"
    if any(pattern.search(combined) for pattern in _EXPECTED_PATTERNS):
        return "expected_outcome_logged_as_error", "medium"
    if any(pattern.search(combined) for pattern in _BUSINESS_PATTERNS):
        return "business_rejection", "medium"
    if status is not None and status >= 500:
        return "technical_failure", "medium"
    return "unknown", "low"


def _next_action(assessment: str, canonical_cause: str, root_app: str) -> str:
    if assessment == "expected_outcome_logged_as_error":
        return (
            "Confirm the business/API contract; if the outcome is expected, "
            "downgrade its log level before suppressing alerts."
        )
    if assessment == "technical_failure":
        if re.search(r"optimisticlock", canonical_cause, re.IGNORECASE):
            return (
                f"Inspect concurrent updates in {root_app} and verify optimistic-lock "
                "retry and idempotency."
            )
        return f"Inspect {root_app} around the representative trace and verify recovery behavior."
    if assessment == "business_rejection":
        return (
            "Validate the referenced domain data and confirm that the outward status "
            "matches the API contract."
        )
    return "Inspect the representative trace and assign an owner classification."


def _normalized_signature_part(value: str) -> str:
    normalized = _VOLATILE_VALUE_PATTERN.sub("<ID>", value.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def build_cause_family(payload: Mapping[str, Any]) -> OperationalCauseFamily:
    canonical_cause, cause_app = _select_canonical_evidence(payload)
    messages = [
        message
        for message, _source, _app in _candidate_messages(payload)
        if message
    ]
    root_app = cause_app or _root_app(payload)
    operation = _operation(messages)
    outward_status = _outward_status(messages)
    assessment, confidence = _assessment(messages, outward_status)

    trace_counts = payload.get("trace_counts") or {}
    if isinstance(trace_counts, Mapping):
        trace_ids = tuple(sorted(str(trace_id) for trace_id in trace_counts if trace_id))
    else:
        trace_ids = ()
    representative_trace_id = _clean_text(payload.get("trace_id"))
    if representative_trace_id and representative_trace_id not in trace_ids:
        trace_ids = tuple(sorted((*trace_ids, representative_trace_id)))

    if "unique_operations" in payload:
        value = payload.get("unique_operations")
        unique_operations = max(0, int(value)) if value is not None else None
    else:
        unique_operations = len(trace_ids) or None
    operation_count_method = _clean_text(
        payload.get("operation_count_method")
    ) or ("trace_id" if unique_operations is not None else "unavailable")
    operation_count_confidence = _clean_text(
        payload.get("operation_count_confidence")
    ) or ("medium" if unique_operations is not None else "low")
    operation_count_reason = _clean_text(payload.get("operation_count_reason"))
    raw_error_lines = max(0, int(payload.get("error_count", 0) or 0))
    traced_error_lines = min(
        raw_error_lines,
        sum(max(0, int(value or 0)) for value in trace_counts.values()),
    )
    unsegmented_error_lines = raw_error_lines - traced_error_lines
    amplification = (
        round(traced_error_lines / unique_operations, 1)
        if unique_operations
        else None
    )
    signature_source = "|".join(
        (
            _normalized_signature_part(root_app),
            _normalized_signature_part(canonical_cause),
            _normalized_signature_part(operation),
            str(outward_status or "unknown"),
        )
    )
    signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()[:20]

    return OperationalCauseFamily(
        signature=signature,
        canonical_cause=canonical_cause,
        root_app=root_app,
        operation=operation,
        outward_status=outward_status,
        assessment=assessment,
        confidence=confidence,
        next_action=_next_action(assessment, canonical_cause, root_app),
        raw_error_lines=raw_error_lines,
        traced_error_lines=traced_error_lines,
        unsegmented_error_lines=unsegmented_error_lines,
        unique_operations=unique_operations,
        amplification=amplification,
        app_counts={
            str(key): int(value or 0)
            for key, value in (payload.get("app_counts") or {}).items()
        },
        namespace_counts={
            str(key): int(value or 0)
            for key, value in (payload.get("namespace_counts") or {}).items()
        },
        representative_trace_id=representative_trace_id or (trace_ids[0] if trace_ids else ""),
        trace_ids=trace_ids,
        operation_count_method=operation_count_method,
        operation_count_confidence=operation_count_confidence,
        operation_count_reason=operation_count_reason,
    )


def merge_cause_families(
    left: OperationalCauseFamily,
    right: OperationalCauseFamily,
    *,
    same_events: bool,
) -> OperationalCauseFamily:
    """Merge aliases or repeated occurrences without hiding a better cause."""
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    assessment_rank = {
        "unknown": 0,
        "expected_outcome_logged_as_error": 1,
        "business_rejection": 2,
        "technical_failure": 3,
    }
    preferred = max(
        (left, right),
        key=lambda family: (
            confidence_rank.get(family.confidence, 0),
            assessment_rank.get(family.assessment, 0),
            len(family.canonical_cause),
        ),
    )

    def merge_counts(
        first: Mapping[str, int], second: Mapping[str, int]
    ) -> Dict[str, int]:
        keys = set(first) | set(second)
        return {
            key: (
                max(int(first.get(key, 0)), int(second.get(key, 0)))
                if same_events
                else int(first.get(key, 0)) + int(second.get(key, 0))
            )
            for key in sorted(keys)
        }

    trace_ids = tuple(sorted(set(left.trace_ids) | set(right.trace_ids)))
    raw_error_lines = (
        max(left.raw_error_lines, right.raw_error_lines)
        if same_events
        else left.raw_error_lines + right.raw_error_lines
    )
    traced_error_lines = (
        max(left.traced_error_lines, right.traced_error_lines)
        if same_events
        else left.traced_error_lines + right.traced_error_lines
    )
    unsegmented_error_lines = (
        max(left.unsegmented_error_lines, right.unsegmented_error_lines)
        if same_events
        else left.unsegmented_error_lines + right.unsegmented_error_lines
    )
    if same_events:
        known_operation_counts = [
            count
            for count in (left.unique_operations, right.unique_operations)
            if count is not None
        ]
        unique_operations = max(known_operation_counts) if known_operation_counts else None
    else:
        left_unknown = left.traced_error_lines > 0 and left.unique_operations is None
        right_unknown = right.traced_error_lines > 0 and right.unique_operations is None
        unique_operations = (
            None
            if left_unknown or right_unknown
            else (left.unique_operations or 0) + (right.unique_operations or 0) or None
        )
    operation_evidence = [
        family
        for family in (left, right)
        if family.traced_error_lines > 0
    ]
    operation_count_method = (
        "unavailable"
        if unique_operations is None
        else (
            operation_evidence[0].operation_count_method
            if operation_evidence
            and len({family.operation_count_method for family in operation_evidence}) == 1
            else "mixed"
        )
    )
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    operation_count_confidence = (
        "low"
        if unique_operations is None
        else min(
            (family.operation_count_confidence for family in operation_evidence),
            key=lambda value: confidence_rank.get(value, 0),
            default="low",
        )
    )
    operation_count_reason = "; ".join(dict.fromkeys(
        family.operation_count_reason
        for family in operation_evidence
        if family.operation_count_reason
    ))
    amplification = (
        round(traced_error_lines / unique_operations, 1)
        if unique_operations
        else None
    )
    representative_trace_id = (
        preferred.representative_trace_id
        or (trace_ids[0] if trace_ids else "")
    )

    return OperationalCauseFamily(
        signature=preferred.signature,
        canonical_cause=preferred.canonical_cause,
        root_app=preferred.root_app,
        operation=preferred.operation,
        outward_status=preferred.outward_status,
        assessment=preferred.assessment,
        confidence=preferred.confidence,
        next_action=preferred.next_action,
        raw_error_lines=raw_error_lines,
        traced_error_lines=traced_error_lines,
        unsegmented_error_lines=unsegmented_error_lines,
        unique_operations=unique_operations,
        amplification=amplification,
        app_counts=merge_counts(left.app_counts, right.app_counts),
        namespace_counts=merge_counts(left.namespace_counts, right.namespace_counts),
        representative_trace_id=representative_trace_id,
        trace_ids=trace_ids,
        operation_count_method=operation_count_method,
        operation_count_confidence=operation_count_confidence,
        operation_count_reason=operation_count_reason,
    )


def _incident_count(incident: Any) -> int:
    stats = getattr(incident, "stats", None)
    value = getattr(stats, "current_count", 0) if stats is not None else 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _timeline_payload(
    timeline: Any,
    raw_error_lines: int,
    context_timeline: Any = None,
) -> Dict[str, Any]:
    from .trace_timeline import estimate_operation_occurrences

    error_events = [
        event
        for event in (getattr(timeline, "events", None) or [])
        if str(getattr(event, "level", "ERROR") or "ERROR").upper() in {"ERROR", "FATAL"}
    ]
    evidence_events = list(error_events)
    if context_timeline is not None:
        evidence_events.extend(getattr(context_timeline, "events", None) or [])
    app_counts = Counter(
        str(getattr(event, "app", "") or "unknown-app")
        for event in error_events
    )
    namespace_counts = Counter(
        str(getattr(event, "namespace", "") or "")
        for event in error_events
        if getattr(event, "namespace", "")
    )
    trace_id = str(getattr(timeline, "trace_id", "") or "")
    operation_estimate = estimate_operation_occurrences(
        timeline,
        context_timeline=context_timeline,
        expected_error_lines=raw_error_lines,
    )
    return {
        "error_count": raw_error_lines,
        "trace_counts": {trace_id: raw_error_lines} if trace_id else {},
        "trace_id": trace_id,
        "trace_steps": [
            {
                "app": str(getattr(event, "app", "") or "unknown-app"),
                "message": str(getattr(event, "message", "") or ""),
            }
            for event in evidence_events
        ],
        "app_counts": dict(app_counts),
        "namespace_counts": dict(namespace_counts),
        "unique_operations": operation_estimate.count,
        "operation_count_method": operation_estimate.method,
        "operation_count_confidence": operation_estimate.confidence,
        "operation_count_reason": operation_estimate.reason,
    }


def _incident_fallback_payload(incident: Any, raw_error_lines: int) -> Dict[str, Any]:
    app_counts = getattr(incident, "app_event_counts", {}) or {}
    top_app = (
        str(max(app_counts.items(), key=lambda item: (int(item[1] or 0), item[0]))[0])
        if app_counts else "unknown-app"
    )
    return {
        "error_count": raw_error_lines,
        "error_class": str(getattr(incident, "error_type", "") or "unknown"),
        "root_cause": {
            "service": top_app,
            "message": str(getattr(incident, "normalized_message", "") or "Unknown cause"),
        },
        "trace_counts": {},
        "app_counts": {},
        "namespace_counts": {},
        "unique_operations": None,
        "operation_count_method": "unavailable",
        "operation_count_confidence": "low",
        "operation_count_reason": "trace coverage unavailable",
    }


def build_daily_cause_analysis(
    problems: Mapping[str, Any],
    timelines: Mapping[str, Any],
    ownership: Mapping[str, Any],
    trace_pattern_index: Optional[Mapping[str, Any]] = None,
) -> CauseFamilyAnalysis:
    """Build daily cause families at operation grain with exact raw-line coverage."""
    all_incidents = [
        incident
        for problem in problems.values()
        for incident in (getattr(problem, "incidents", None) or [])
    ]
    source_raw_error_lines = sum(_incident_count(incident) for incident in all_incidents)
    trace_line_counts: Counter = Counter()
    for incident in all_incidents:
        for trace_id, count in (getattr(incident, "trace_event_counts", {}) or {}).items():
            if trace_id:
                trace_line_counts[str(trace_id)] += max(0, int(count or 0))

    owned_trace_ids = {
        str(trace_id)
        for summary in ownership.values()
        for trace_id in (getattr(summary, "owned_trace_ids", None) or [])
        if trace_id
    }
    available_trace_ids = sorted(owned_trace_ids & set(timelines) & set(trace_line_counts))
    families_by_signature: Dict[str, OperationalCauseFamily] = {}
    segmented_error_lines = 0

    for trace_id in available_trace_ids:
        raw_error_lines = int(trace_line_counts[trace_id])
        if raw_error_lines <= 0:
            continue
        pattern = (trace_pattern_index or {}).get(trace_id)
        context_timeline = getattr(pattern, "representative", None) if pattern else None
        if (
            context_timeline is not None
            and str(getattr(context_timeline, "trace_id", "") or "") != trace_id
        ):
            context_timeline = None
        from .trace_timeline import segment_operation_timelines

        segments, operation_estimate = segment_operation_timelines(
            timelines[trace_id],
            context_timeline=context_timeline,
            expected_error_lines=raw_error_lines,
        )
        segment_counts = [
            len(segment.error_timeline.events)
            for segment in segments
        ]
        if operation_estimate.method == "root_span":
            if sum(segment_counts) != raw_error_lines:
                raise ValueError(
                    "operation segments do not reconcile to trace count: "
                    f"trace={trace_id}, segments={sum(segment_counts)}, "
                    f"raw={raw_error_lines}"
                )
            raw_counts = segment_counts
        else:
            raw_counts = [raw_error_lines]

        for segment, segment_raw_lines in zip(segments, raw_counts):
            family = build_cause_family(
                _timeline_payload(
                    segment.error_timeline,
                    segment_raw_lines,
                    context_timeline=segment.context_timeline,
                )
            )
            existing = families_by_signature.get(family.signature)
            families_by_signature[family.signature] = (
                merge_cause_families(existing, family, same_events=False)
                if existing else family
            )
        segmented_error_lines += raw_error_lines

    represented_trace_ids = set(available_trace_ids)
    unsegmented_error_lines = 0
    for incident in all_incidents:
        incident_raw = _incident_count(incident)
        represented = sum(
            max(0, int(count or 0))
            for trace_id, count in (getattr(incident, "trace_event_counts", {}) or {}).items()
            if str(trace_id) in represented_trace_ids
        )
        remainder = incident_raw - represented
        if remainder < 0:
            raise ValueError(
                "incident trace counts exceed raw count: "
                f"fingerprint={getattr(incident, 'fingerprint', 'unknown')}, "
                f"raw={incident_raw}, represented={represented}"
            )
        if remainder == 0:
            continue
        family = build_cause_family(_incident_fallback_payload(incident, remainder))
        family = replace(
            family,
            traced_error_lines=0,
            unsegmented_error_lines=remainder,
            unique_operations=None,
            amplification=None,
            trace_ids=(),
            representative_trace_id="",
            operation_count_method="unavailable",
            operation_count_confidence="low",
            operation_count_reason="trace coverage unavailable",
        )
        unsegmented_error_lines += remainder
        existing = families_by_signature.get(family.signature)
        families_by_signature[family.signature] = (
            merge_cause_families(existing, family, same_events=False)
            if existing else family
        )

    families = tuple(sorted(
        families_by_signature.values(),
        key=lambda family: (
            -family.raw_error_lines,
            family.root_app,
            family.canonical_cause,
        ),
    ))
    traced_families = [
        family for family in families if family.traced_error_lines > 0
    ]
    unique_operations = (
        None
        if any(family.unique_operations is None for family in traced_families)
        else sum(family.unique_operations or 0 for family in traced_families)
    )
    analysis = CauseFamilyAnalysis(
        families=families,
        source_raw_error_lines=source_raw_error_lines,
        segmented_error_lines=segmented_error_lines,
        unsegmented_error_lines=unsegmented_error_lines,
        unique_operations=unique_operations,
    )
    analysis.validate()
    return analysis


def build_collection_cause_analysis(collection: Any) -> CauseFamilyAnalysis:
    """Build and attach the authoritative per-run cause analysis."""
    from .problem_aggregator import aggregate_by_problem_key
    from .trace_timeline import assign_trace_ownership

    problems = aggregate_by_problem_key(collection.incidents)
    timelines = getattr(collection, "trace_timelines", {}) or {}
    ownership = assign_trace_ownership(problems, timelines) if timelines else {}
    analysis = build_daily_cause_analysis(
        problems,
        timelines,
        ownership,
        getattr(collection, "trace_pattern_index", {}) or {},
    )
    if analysis.source_raw_error_lines != int(collection.input_records):
        raise ValueError(
            "collection cause-family count mismatch: "
            f"families={analysis.source_raw_error_lines}, "
            f"input={collection.input_records}"
        )
    collection.cause_analysis = analysis
    return analysis