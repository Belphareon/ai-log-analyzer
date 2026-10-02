"""First-class, idempotent namespace peak decisions and contributors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


DECISION_DETECTOR_VERSION = "namespace_pxx_cap_decision_v1"
WINDOW_MINUTES = 15


class PeakDecisionInvariantError(ValueError):
    """Raised when a namespace decision cannot be reconciled."""


def _utc_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise PeakDecisionInvariantError(f"{label} is not an ISO timestamp") from error
    else:
        raise PeakDecisionInvariantError(f"{label} is required")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PeakDecisionInvariantError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise PeakDecisionInvariantError(f"invalid numeric value: {value!r}") from error


def _count(value: Any) -> int:
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as error:
        raise PeakDecisionInvariantError(f"invalid count: {value!r}") from error
    if count < 0:
        raise PeakDecisionInvariantError(f"count must not be negative: {count}")
    return count


def _decision_identity(
    stream_key: str,
    namespace: str,
    window_start: datetime,
    detector_version: str,
    threshold_snapshot_id: str,
) -> str:
    identity = {
        "stream_key": stream_key,
        "signal_namespace": namespace,
        "window_start_utc": window_start.isoformat(),
        "detector_version": detector_version,
        "threshold_snapshot_id": threshold_snapshot_id,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_contributors(values: Iterable[Mapping[str, Any]]) -> Tuple[dict[str, Any], ...]:
    contributors = []
    for value in values or ():
        fingerprint = str(value.get("fingerprint") or "").strip()
        if not fingerprint:
            continue
        contributor = {
            "fingerprint": fingerprint,
            "error_type": str(value.get("error_type") or ""),
            "normalized_message": str(value.get("normalized_message") or "")[:500],
            "contribution": _count(value.get("contribution")),
            "baseline": _number(value.get("baseline")),
            "threshold": _number(value.get("threshold")),
            "anomaly_score": _number(value.get("anomaly_score")),
            "method": str(value.get("method") or "unknown"),
            "is_anomalous": bool(value.get("is_anomalous")),
            "apps": sorted({str(app) for app in (value.get("apps") or ()) if str(app)}),
        }
        contributors.append(contributor)
    return tuple(sorted(contributors, key=lambda item: (
        not item["is_anomalous"],
        -item["contribution"],
        item["fingerprint"],
    )))


@dataclass(frozen=True)
class NamespacePeakDecision:
    """One auditable verdict for one namespace and one 15-minute window."""

    window_decision_id: str
    stream_key: str
    signal_namespace: str
    window_start_utc: datetime
    window_end_utc: datetime
    detector_version: str
    threshold_snapshot_id: str
    namespace_raw_lines: int
    p93_threshold: Optional[float]
    cap_threshold: Optional[float]
    effective_threshold: Optional[float]
    triggered_by: Optional[str]
    is_peak: bool
    verdict_reason: str
    diagnosis_status: str
    contributors: Tuple[dict[str, Any], ...] = ()
    contract_hash: str = ""
    peak_identifier: str = ""
    run_id: str = ""

    def validate(self) -> None:
        if not self.window_decision_id:
            raise PeakDecisionInvariantError("window_decision_id is required")
        if not self.stream_key or not self.signal_namespace:
            raise PeakDecisionInvariantError("stream_key and signal_namespace are required")
        if self.window_end_utc - self.window_start_utc != timedelta(minutes=WINDOW_MINUTES):
            raise PeakDecisionInvariantError("namespace decisions must cover exactly 15 minutes")
        if self.namespace_raw_lines < 0:
            raise PeakDecisionInvariantError("namespace_raw_lines must not be negative")
        if self.is_peak and not self.peak_identifier:
            raise PeakDecisionInvariantError("peak decisions require peak_identifier")
        if self.diagnosis_status not in {"diagnosed", "undiagnosed"}:
            raise PeakDecisionInvariantError(
                f"invalid diagnosis_status: {self.diagnosis_status}"
            )
        for contributor in self.contributors:
            if contributor["contribution"] < 0:
                raise PeakDecisionInvariantError("contributor contribution must not be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_decision_id": self.window_decision_id,
            "stream_key": self.stream_key,
            "signal_namespace": self.signal_namespace,
            "window_start_utc": self.window_start_utc.isoformat(),
            "window_end_utc": self.window_end_utc.isoformat(),
            "detector_version": self.detector_version,
            "threshold_snapshot_id": self.threshold_snapshot_id,
            "namespace_raw_lines": self.namespace_raw_lines,
            "p93_threshold": self.p93_threshold,
            "cap_threshold": self.cap_threshold,
            "effective_threshold": self.effective_threshold,
            "triggered_by": self.triggered_by,
            "is_peak": self.is_peak,
            "is_namespace_peak": self.is_peak,
            "verdict_reason": self.verdict_reason,
            "diagnosis_status": self.diagnosis_status,
            "contributors": list(self.contributors),
            "contract_hash": self.contract_hash,
            "peak_identifier": self.peak_identifier,
            "run_id": self.run_id,
        }


def decision_from_dict(value: Mapping[str, Any]) -> NamespacePeakDecision:
    """Restore a serialized decision without recalculating its verdict."""
    window_start = _utc_datetime(
        value.get("window_start_utc") or value.get("window_start"),
        "window_start_utc",
    )
    window_end = _utc_datetime(
        value.get("window_end_utc") or value.get("window_end"),
        "window_end_utc",
    )
    decision = NamespacePeakDecision(
        window_decision_id=str(value.get("window_decision_id") or ""),
        stream_key=str(value.get("stream_key") or ""),
        signal_namespace=str(
            value.get("signal_namespace") or value.get("namespace") or ""
        ),
        window_start_utc=window_start,
        window_end_utc=window_end,
        detector_version=str(value.get("detector_version") or DECISION_DETECTOR_VERSION),
        threshold_snapshot_id=str(value.get("threshold_snapshot_id") or ""),
        namespace_raw_lines=_count(
            value.get("namespace_raw_lines", value.get("namespace_total"))
        ),
        p93_threshold=_number(value.get("p93_threshold")),
        cap_threshold=_number(value.get("cap_threshold")),
        effective_threshold=_number(value.get("effective_threshold")),
        triggered_by=str(value.get("triggered_by") or "") or None,
        is_peak=bool(value.get("is_peak", value.get("is_namespace_peak", False))),
        verdict_reason=str(value.get("verdict_reason") or "below_threshold"),
        diagnosis_status=str(value.get("diagnosis_status") or "undiagnosed"),
        contributors=_normalize_contributors(
            value.get("contributors") or value.get("family_decisions") or ()
        ),
        contract_hash=str(value.get("contract_hash") or ""),
        peak_identifier=str(value.get("peak_identifier") or "") if value.get("is_peak", value.get("is_namespace_peak", False)) else "",
        run_id=str(value.get("run_id") or ""),
    )
    decision.validate()
    return decision


def decision_from_audit(
    audit: Mapping[str, Any],
    *,
    stream_key: str = "live",
    window_end: Any = None,
    contract_hash: str = "",
    run_id: str = "",
) -> NamespacePeakDecision:
    """Convert legacy Phase C audit output into the first-class contract."""
    window_start = _utc_datetime(audit.get("window_start"), "window_start")
    end = (
        _utc_datetime(window_end, "window_end")
        if window_end is not None
        else window_start + timedelta(minutes=WINDOW_MINUTES)
    )
    namespace = str(audit.get("namespace") or "").strip()
    is_peak = bool(audit.get("is_peak", audit.get("is_namespace_peak", False)))
    contributors = _normalize_contributors(audit.get("family_decisions") or ())
    diagnosis_status = "diagnosed" if audit.get("owner_fingerprint") else "undiagnosed"
    if not is_peak:
        verdict_reason = str(audit.get("verdict_reason") or "below_threshold")
    elif diagnosis_status == "diagnosed":
        verdict_reason = str(audit.get("verdict_reason") or "peak_diagnosed")
    else:
        verdict_reason = str(audit.get("verdict_reason") or "peak_undiagnosed")
    detector_version = str(
        audit.get("detector_version")
        or next(
            (
                item.get("detector_version")
                for item in (audit.get("family_decisions") or ())
                if item.get("detector_version")
            ),
            DECISION_DETECTOR_VERSION,
        )
    )
    snapshot_id = str(audit.get("threshold_snapshot_id") or "")
    peak_identifier = str(audit.get("peak_identifier") or "") if is_peak else ""
    decision = NamespacePeakDecision(
        window_decision_id=_decision_identity(
            stream_key,
            namespace,
            window_start,
            detector_version,
            snapshot_id,
        ),
        stream_key=stream_key,
        signal_namespace=namespace,
        window_start_utc=window_start,
        window_end_utc=end,
        detector_version=detector_version,
        threshold_snapshot_id=snapshot_id,
        namespace_raw_lines=_count(audit.get("namespace_total")),
        p93_threshold=_number(audit.get("p93_threshold")),
        cap_threshold=_number(audit.get("cap_threshold")),
        effective_threshold=_number(
            audit.get("effective_threshold")
            if audit.get("effective_threshold") is not None
            else min(
                value
                for value in (
                    _number(audit.get("p93_threshold")),
                    _number(audit.get("cap_threshold")),
                )
                if value is not None
            )
            if any(
                value is not None
                for value in (
                    _number(audit.get("p93_threshold")),
                    _number(audit.get("cap_threshold")),
                )
            )
            else None
        ),
        triggered_by=str(audit.get("triggered_by") or "") or None,
        is_peak=is_peak,
        verdict_reason=verdict_reason,
        diagnosis_status=diagnosis_status,
        contributors=contributors,
        contract_hash=contract_hash,
        peak_identifier=peak_identifier,
        run_id=run_id,
    )
    decision.validate()
    return decision


def materialize_namespace_decisions(
    audits: Sequence[Mapping[str, Any]],
    monitored_namespaces: Iterable[str],
    *,
    window_start: Any,
    stream_key: str = "live",
    contract_hash: str = "",
    run_id: str = "",
) -> Tuple[NamespacePeakDecision, ...]:
    """Return exactly one decision per monitored namespace for one window."""
    start = _utc_datetime(window_start, "window_start")
    by_namespace = {
        str(audit.get("namespace") or ""): audit
        for audit in audits
        if str(audit.get("namespace") or "")
    }
    decisions = []
    for namespace in sorted({str(value).strip() for value in monitored_namespaces if str(value).strip()}):
        audit = by_namespace.get(namespace)
        if audit is None:
            audit = {
                "window_start": start,
                "namespace": namespace,
                "namespace_total": 0,
                "is_namespace_peak": False,
                "verdict_reason": "below_min_volume",
                "family_decisions": [],
            }
        decisions.append(
            decision_from_audit(
                audit,
                stream_key=stream_key,
                contract_hash=contract_hash,
                run_id=run_id,
            )
        )
    return tuple(decisions)


def materialize_decision_windows(
    audits: Sequence[Mapping[str, Any]],
    monitored_namespaces: Iterable[str],
    *,
    window_starts: Iterable[Any],
    stream_key: str = "live",
    contract_hash: str = "",
    run_id: str = "",
) -> Tuple[NamespacePeakDecision, ...]:
    """Materialize dense namespace decisions for every supplied 15m bucket."""
    normalized_starts = sorted({
        _utc_datetime(value, "window_start")
        for value in window_starts
    })
    if not normalized_starts:
        raise PeakDecisionInvariantError("at least one window_start is required")

    decisions = []
    for start in normalized_starts:
        matching_audits = [
            audit
            for audit in audits
            if _utc_datetime(audit.get("window_start"), "audit.window_start") == start
        ]
        decisions.extend(
            materialize_namespace_decisions(
                matching_audits,
                monitored_namespaces,
                window_start=start,
                stream_key=stream_key,
                contract_hash=contract_hash,
                run_id=run_id,
            )
        )
    return tuple(decisions)


def densify_decision_windows(
    existing: Iterable[Mapping[str, Any]],
    monitored_namespaces: Iterable[str],
    *,
    window_starts: Iterable[Any],
    stream_key: str = "live",
    contract_hash: str = "",
    run_id: str = "",
) -> Tuple[NamespacePeakDecision, ...]:
    """Fill missing namespace/window pairs without recalculating existing verdicts."""
    defaults = materialize_decision_windows(
        [],
        monitored_namespaces,
        window_starts=window_starts,
        stream_key=stream_key,
        contract_hash=contract_hash,
        run_id=run_id,
    )
    restored = [decision_from_dict(value) for value in existing or ()]
    decisions = {
        (decision.stream_key, decision.window_start_utc, decision.signal_namespace): decision
        for decision in restored
    }
    for decision in defaults:
        decisions.setdefault(
            (decision.stream_key, decision.window_start_utc, decision.signal_namespace),
            decision,
        )
    return tuple(sorted(
        decisions.values(),
        key=lambda decision: (decision.window_start_utc, decision.signal_namespace),
    ))


def build_decision_rows(
    decisions: Iterable[NamespacePeakDecision],
    run_id: str,
) -> list[tuple[Any, ...]]:
    rows = []
    identities = set()
    for decision in decisions:
        decision.validate()
        identity = (decision.stream_key, decision.window_start_utc, decision.signal_namespace)
        if decision.window_decision_id in identities or identity in identities:
            raise PeakDecisionInvariantError(f"duplicate namespace decision: {identity}")
        identities.add(decision.window_decision_id)
        identities.add(identity)
        rows.append((
            run_id,
            decision.window_decision_id,
            decision.stream_key,
            decision.signal_namespace,
            decision.window_start_utc,
            decision.window_end_utc,
            decision.detector_version,
            decision.threshold_snapshot_id or None,
            decision.namespace_raw_lines,
            decision.p93_threshold,
            decision.cap_threshold,
            decision.effective_threshold,
            decision.triggered_by,
            decision.is_peak,
            decision.verdict_reason,
            decision.diagnosis_status,
            decision.contract_hash,
            decision.peak_identifier or None,
        ))
    return sorted(rows, key=lambda row: (row[4], row[3]))


def build_contributor_rows(
    decisions: Iterable[NamespacePeakDecision],
    run_id: str,
) -> list[tuple[Any, ...]]:
    rows = []
    identities = set()
    for decision in decisions:
        for contributor in decision.contributors:
            identity = (decision.window_decision_id, contributor["fingerprint"])
            if identity in identities:
                raise PeakDecisionInvariantError(f"duplicate contributor: {identity}")
            identities.add(identity)
            rows.append((
                run_id,
                decision.window_decision_id,
                contributor["fingerprint"],
                contributor["error_type"],
                contributor["normalized_message"],
                contributor["contribution"],
                contributor["baseline"],
                contributor["threshold"],
                contributor["anomaly_score"],
                contributor["method"],
                contributor["is_anomalous"],
                json.dumps(contributor["apps"], sort_keys=True),
            ))
    return sorted(rows, key=lambda row: (row[1], row[2]))