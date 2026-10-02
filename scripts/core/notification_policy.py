"""Policy decisions are separate from provider delivery outcomes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Tuple


POLICY_VERSION = "peak_notification_policy_v1"
STATE_ORDER = {
    "START": 0,
    "RECURRENCE": 1,
    "EXPANSION": 2,
    "ESCALATION": 3,
    "CONTINUATION": 4,
    "RECOVERY": 5,
    "RESOLVED": 6,
}


def _stable_id(*parts: Any) -> str:
    payload = json.dumps([str(part or "") for part in parts], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NotificationDecision:
    notification_decision_id: str
    episode_id: str
    window_decision_id: str
    stream_key: str
    destination: str
    policy_outcome: str
    episode_state: str
    candidate_reason: str
    detail_rank: Optional[int] = None
    detail_limit: Optional[int] = None
    test_origin_label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.policy_outcome not in {
            "primary_send",
            "digest_only",
            "route_suppressed",
            "no_material_change",
        }:
            raise ValueError(f"invalid notification policy outcome: {self.policy_outcome}")
        if self.episode_state not in STATE_ORDER:
            raise ValueError(f"invalid notification episode state: {self.episode_state}")
        if not self.episode_id or not self.window_decision_id:
            raise ValueError("notification decision identity is incomplete")
        if not self.stream_key or not self.destination:
            raise ValueError("notification decision routing is incomplete")

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_decision_id": self.notification_decision_id,
            "episode_id": self.episode_id,
            "window_decision_id": self.window_decision_id,
            "stream_key": self.stream_key,
            "destination": self.destination,
            "policy_outcome": self.policy_outcome,
            "episode_state": self.episode_state,
            "candidate_reason": self.candidate_reason,
            "detail_rank": self.detail_rank,
            "detail_limit": self.detail_limit,
            "test_origin_label": self.test_origin_label,
            "metadata": dict(self.metadata),
            "policy_version": POLICY_VERSION,
        }


def _rank(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    state = str(candidate.get("episode_state") or "CONTINUATION")
    assessment = str(candidate.get("assessment") or "unknown")
    assessment_rank = {"technical_failure": 0, "business_rejection": 1, "unknown": 2}.get(
        assessment, 3
    )
    confidence_rank = {"high": 0, "medium": 1, "low": 2}.get(
        str(candidate.get("confidence") or "low"), 3
    )
    return (
        STATE_ORDER.get(state, 99),
        assessment_rank,
        -float(candidate.get("namespace_ratio") or 0),
        -int(candidate.get("unique_operation_occurrences") or 0),
        confidence_rank,
        str(candidate.get("episode_id") or ""),
    )


def _material_change(candidate: Mapping[str, Any]) -> bool:
    return bool(
        candidate.get("material_change_reasons")
        or candidate.get("cause_changed")
        or candidate.get("outcome_changed")
        or candidate.get("heartbeat_due")
    )


def decide_notification_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    destination: str = "operator_primary",
    detail_limit: int = 3,
) -> Tuple[NotificationDecision, ...]:
    """Create one terminal policy decision for every candidate.

    The detail limit only changes the amount of primary detail. It never removes
    a candidate from the decision funnel or from the digest summary.
    """
    values = [dict(candidate) for candidate in candidates]
    ranked = sorted(values, key=_rank)
    decisions = []
    for rank, candidate in enumerate(ranked, 1):
        episode_state = str(candidate.get("episode_state") or "CONTINUATION")
        episode_id = str(candidate.get("episode_id") or "")
        window_decision_id = str(candidate.get("window_decision_id") or "")
        stream_key = str(candidate.get("stream_key") or "live")
        if candidate.get("route_suppressed"):
            outcome = "route_suppressed"
            reason = str(candidate.get("route_suppression_reason") or "route_policy")
        elif episode_state in {"START", "RECURRENCE", "EXPANSION", "ESCALATION"}:
            outcome = "primary_send"
            reason = episode_state.lower()
        elif episode_state == "CONTINUATION":
            if candidate.get("no_material_change"):
                outcome = "no_material_change"
                reason = str(candidate.get("no_material_change_reason") or "no_material_change")
            else:
                outcome = "primary_send" if _material_change(candidate) else "digest_only"
                reason = "material_change" if outcome == "primary_send" else "stable_continuation"
        else:
            outcome = "digest_only"
            reason = episode_state.lower()

        if outcome == "primary_send" and detail_limit > 0 and rank > detail_limit:
            outcome = "digest_only"
            reason = f"detail_limit_{detail_limit}"

        test_origin = str(
            candidate.get("test_origin_label")
            or candidate.get("test_originator_application")
            or ""
        )
        metadata = {
            "policy_version": POLICY_VERSION,
            "is_test_origin": bool(test_origin),
            "material_change_reasons": list(candidate.get("material_change_reasons") or []),
        }
        decision = NotificationDecision(
            notification_decision_id=_stable_id(
                stream_key,
                episode_id,
                window_decision_id,
                destination,
            ),
            episode_id=episode_id,
            window_decision_id=window_decision_id,
            stream_key=stream_key,
            destination=destination,
            policy_outcome=outcome,
            episode_state=episode_state,
            candidate_reason=reason,
            detail_rank=rank,
            detail_limit=detail_limit,
            test_origin_label=test_origin,
            metadata=metadata,
        )
        decision.validate()
        decisions.append(decision)
    return tuple(decisions)


def decision_summary(decisions: Iterable[NotificationDecision]) -> dict[str, int]:
    summary = {
        "candidates": 0,
        "primary_send": 0,
        "digest_only": 0,
        "route_suppressed": 0,
        "no_material_change": 0,
    }
    for decision in decisions:
        summary["candidates"] += 1
        summary[decision.policy_outcome] += 1
    return summary