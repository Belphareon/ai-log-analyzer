"""Deterministic event-time correlation for 15-minute peak episodes."""


from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

try:
    from ..analysis.operational_cause import CAUSE_SIGNATURE_VERSION
except ImportError:  # pragma: no cover - direct script execution
    from analysis.operational_cause import CAUSE_SIGNATURE_VERSION


CORRELATION_VERSION = "peak_episode_correlation_v1"
WINDOW_MINUTES = 15
EPISODE_NAMESPACE = uuid.UUID("4c8f5f8b-2afc-4d8f-a5b1-2f7dbb6e9a16")


def _utc(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{label} is not an ISO timestamp") from error
    else:
        raise ValueError(f"{label} is required")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return result.astimezone(timezone.utc)


def _positive_int(value: Any) -> int:
    return max(0, int(value or 0))


def _stable_episode_id(
    stream_key: str,
    cause_signature: str,
    first_window_start: datetime,
    recurrence: bool,
) -> str:
    suffix = "recurrence" if recurrence else "start"
    identity = "|".join((stream_key, cause_signature or "unresolved", first_window_start.isoformat(), suffix))
    return str(uuid.uuid5(EPISODE_NAMESPACE, identity))


def _unresolved_signature(observation: "PeakObservation") -> str:
    fingerprint_part = ",".join(observation.contributor_fingerprints)
    if not fingerprint_part:
        source = "|".join((
            "no-contributor-evidence",
            observation.signal_namespace,
            observation.window_start_utc.isoformat(),
        ))
    else:
        source = "|".join((observation.root_app, observation.canonical_cause, fingerprint_part))
    return "unresolved:" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class PeakObservation:
    """Cause-bound view of one namespace decision used by episode correlation."""

    window_decision_id: str
    stream_key: str
    signal_namespace: str
    window_start_utc: datetime
    is_peak: bool
    namespace_raw_lines: int
    cause_signature: Optional[str] = None
    cause_signature_version: str = CAUSE_SIGNATURE_VERSION
    cause_family_raw_lines: int = 0
    unique_operation_occurrences: Optional[int] = None
    assessment: str = "unknown"
    confidence: str = "low"
    root_app: str = ""
    canonical_cause: str = ""
    operation: str = "unknown-operation"
    outward_status: Optional[int] = None
    contributor_fingerprints: Tuple[str, ...] = ()
    applications: Tuple[str, ...] = ()
    material_impact: float = 0.0

    def normalized_cause_signature(self) -> str:
        return self.cause_signature or _unresolved_signature(self)

    def validate(self) -> None:
        if not self.window_decision_id or not self.stream_key or not self.signal_namespace:
            raise ValueError("observation identity is incomplete")
        if self.namespace_raw_lines < 0 or self.cause_family_raw_lines < 0:
            raise ValueError("observation counts must not be negative")
        if self.window_start_utc.tzinfo is None or self.window_start_utc.utcoffset() is None:
            raise ValueError("observation window must be timezone-aware")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError(f"invalid observation confidence: {self.confidence}")

    @classmethod
    def from_mapping(
        cls,
        decision: Mapping[str, Any],
        *,
        cause: Optional[Mapping[str, Any]] = None,
    ) -> "PeakObservation":
        cause = cause or {}
        contributors = decision.get("contributors") or ()
        undiagnosed = str(decision.get("diagnosis_status") or "") == "undiagnosed"
        fingerprints = tuple(sorted({
            str(item.get("fingerprint"))
            for item in contributors
            if item.get("fingerprint")
            and (undiagnosed or item.get("is_anomalous", True))
        }))
        applications = tuple(sorted({
            str(app)
            for item in contributors
            for app in (item.get("apps") or ())
            if str(app)
        }))
        return cls(
            window_decision_id=str(decision.get("window_decision_id") or ""),
            stream_key=str(decision.get("stream_key") or ""),
            signal_namespace=str(
                decision.get("signal_namespace") or decision.get("namespace") or ""
            ),
            window_start_utc=_utc(
                decision.get("window_start_utc") or decision.get("window_start"),
                "window_start_utc",
            ),
            is_peak=bool(decision.get("is_peak", decision.get("is_namespace_peak", False))),
            namespace_raw_lines=_positive_int(
                decision.get("namespace_raw_lines", decision.get("namespace_total"))
            ),
            cause_signature=str(cause.get("signature") or decision.get("cause_signature") or "") or None,
            cause_signature_version=str(
                cause.get("signature_version") or decision.get("cause_signature_version") or CAUSE_SIGNATURE_VERSION
            ),
            cause_family_raw_lines=_positive_int(
                cause.get("raw_error_lines", decision.get("cause_family_raw_lines"))
            ),
            unique_operation_occurrences=(
                int(cause["unique_operations"])
                if cause.get("unique_operations") is not None
                else None
            ),
            assessment=str(cause.get("assessment") or "unknown"),
            confidence=str(cause.get("confidence") or decision.get("diagnosis_confidence") or "low"),
            root_app=str(cause.get("root_app") or cause.get("root_application") or ""),
            canonical_cause=str(cause.get("canonical_cause") or ""),
            operation=str(cause.get("operation") or "unknown-operation"),
            outward_status=(
                int(cause["outward_status"])
                if cause.get("outward_status") is not None
                else None
            ),
            contributor_fingerprints=fingerprints,
            applications=applications,
            material_impact=float(
                cause.get("material_impact")
                or cause.get("raw_error_lines")
                or decision.get("namespace_raw_lines")
                or 0
            ),
        )


@dataclass
class PeakEpisode:
    episode_id: str
    stream_key: str
    cause_signature: str
    cause_signature_version: str
    state: str
    first_window_start_utc: datetime
    last_window_start_utc: datetime
    current_raw_error_lines: int
    cumulative_raw_error_lines: int
    current_operation_occurrences: Optional[int]
    cumulative_operation_occurrences: Optional[int]
    diagnosis_confidence: str
    active_namespaces: set[str] = field(default_factory=set)
    material_change_reasons: Tuple[str, ...] = ()
    previous_episode_id: Optional[str] = None
    resolved_at_utc: Optional[datetime] = None
    non_peak_windows: int = 0
    seen_window_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "stream_key": self.stream_key,
            "cause_signature": self.cause_signature,
            "cause_signature_version": self.cause_signature_version,
            "state": self.state,
            "first_window_start_utc": self.first_window_start_utc.isoformat(),
            "last_window_start_utc": self.last_window_start_utc.isoformat(),
            "resolved_at_utc": (
                self.resolved_at_utc.isoformat() if self.resolved_at_utc else None
            ),
            "current_raw_error_lines": self.current_raw_error_lines,
            "cumulative_raw_error_lines": self.cumulative_raw_error_lines,
            "current_operation_occurrences": self.current_operation_occurrences,
            "cumulative_operation_occurrences": self.cumulative_operation_occurrences,
            "diagnosis_confidence": self.diagnosis_confidence,
            "active_namespaces": sorted(self.active_namespaces),
            "material_change_reasons": list(self.material_change_reasons),
            "non_peak_windows": self.non_peak_windows,
            "seen_window_ids": sorted(self.seen_window_ids),
            "previous_episode_id": self.previous_episode_id,
        }


@dataclass(frozen=True)
class EpisodeTransition:
    episode_id: str
    window_decision_id: str
    stream_key: str
    window_start_utc: datetime
    previous_state: Optional[str]
    state: str
    cause_signature: str
    correlation_method: str
    correlation_version: str
    confidence: str
    allocated_raw_error_lines: int
    unexplained_raw_lines: int
    current_raw_error_lines: int
    cumulative_raw_error_lines: int
    previous_raw_error_lines: Optional[int]
    material_change_reasons: Tuple[str, ...] = ()
    contributor_fingerprints: Tuple[str, ...] = ()
    previous_episode_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "window_decision_id": self.window_decision_id,
            "stream_key": self.stream_key,
            "window_start_utc": self.window_start_utc.isoformat(),
            "previous_state": self.previous_state,
            "state": self.state,
            "cause_signature": self.cause_signature,
            "correlation_method": self.correlation_method,
            "correlation_version": self.correlation_version,
            "confidence": self.confidence,
            "allocated_raw_error_lines": self.allocated_raw_error_lines,
            "unexplained_raw_lines": self.unexplained_raw_lines,
            "current_raw_error_lines": self.current_raw_error_lines,
            "cumulative_raw_error_lines": self.cumulative_raw_error_lines,
            "previous_raw_error_lines": self.previous_raw_error_lines,
            "material_change_reasons": list(self.material_change_reasons),
            "contributor_fingerprints": list(self.contributor_fingerprints),
            "previous_episode_id": self.previous_episode_id,
        }


class PeakEpisodeCorrelator:
    """Rebuild the same episode timeline from observations in any input order."""

    def __init__(
        self,
        *,
        resolve_non_peak_windows: int = 2,
        escalation_ratio: float = 1.5,
    ) -> None:
        if resolve_non_peak_windows < 1:
            raise ValueError("resolve_non_peak_windows must be positive")
        self.resolve_non_peak_windows = resolve_non_peak_windows
        self.escalation_ratio = escalation_ratio

    def correlate(
        self,
        observations: Iterable[PeakObservation],
        prior_episodes: Iterable[Mapping[str, Any]] = (),
    ) -> Tuple[PeakEpisode, ...]:
        normalized = []
        for observation in observations:
            observation.validate()
            normalized.append(observation)
        ordered = sorted(normalized, key=lambda item: (
            item.stream_key,
            item.window_start_utc,
            item.signal_namespace,
            item.window_decision_id,
        ))

        episodes: dict[str, PeakEpisode] = {
            episode.episode_id: episode
            for episode in (_episode_from_mapping(value) for value in prior_episodes or ())
        }
        transitions: list[EpisodeTransition] = []
        active_by_stream_cause: dict[tuple[str, str], list[str]] = {}
        for episode in episodes.values():
            active_by_stream_cause.setdefault(
                (episode.stream_key, episode.cause_signature), []
            ).append(episode.episode_id)
        for observation in ordered:
            cause_signature = observation.normalized_cause_signature()
            if observation.is_peak:
                candidates = [
                    episodes[episode_id]
                    for episode_id in active_by_stream_cause.get(
                        (observation.stream_key, cause_signature), []
                    )
                    if episodes[episode_id].state != "RESOLVED"
                ]
            else:
                active_episodes = [
                    episode
                    for episode in episodes.values()
                    if episode.stream_key == observation.stream_key
                    and episode.state != "RESOLVED"
                ]
                candidates = [
                    episode
                    for episode in active_episodes
                    if observation.signal_namespace in episode.active_namespaces
                    or len(active_episodes) == 1
                ]
            episode = self._select_candidate(candidates, observation)
            if observation.is_peak:
                transition = self._apply_peak(
                    episode,
                    observation,
                    cause_signature,
                    episodes,
                    active_by_stream_cause,
                )
            elif episode is not None:
                transition = self._apply_recovery(episode, observation)
            else:
                continue
            if transition.correlation_method != "idempotent_replay":
                transitions.append(transition)

        # An episode can receive multiple observations for one window (one per
        # namespace). Its final object is the deterministic state after all of them.
        self.last_transitions = tuple(transitions)
        return tuple(sorted(episodes.values(), key=lambda item: item.episode_id))

    def _select_candidate(
        self,
        candidates: Sequence[PeakEpisode],
        observation: PeakObservation,
    ) -> Optional[PeakEpisode]:
        adjacent = [
            episode
            for episode in candidates
            if observation.window_start_utc - episode.last_window_start_utc
            <= timedelta(minutes=WINDOW_MINUTES)
            and observation.window_start_utc >= episode.last_window_start_utc
        ]
        return min(adjacent, key=lambda item: item.episode_id) if adjacent else None

    def _new_episode(
        self,
        observation: PeakObservation,
        cause_signature: str,
        *,
        recurrence: bool,
        previous_episode_id: Optional[str] = None,
    ) -> PeakEpisode:
        return PeakEpisode(
            episode_id=_stable_episode_id(
                observation.stream_key,
                cause_signature,
                observation.window_start_utc,
                recurrence,
            ),
            stream_key=observation.stream_key,
            cause_signature=cause_signature,
            cause_signature_version=observation.cause_signature_version,
            state="RECURRENCE" if recurrence else "START",
            first_window_start_utc=observation.window_start_utc,
            last_window_start_utc=observation.window_start_utc,
            current_raw_error_lines=observation.cause_family_raw_lines,
            cumulative_raw_error_lines=observation.cause_family_raw_lines,
            current_operation_occurrences=observation.unique_operation_occurrences,
            cumulative_operation_occurrences=observation.unique_operation_occurrences,
            diagnosis_confidence=observation.confidence,
            active_namespaces={observation.signal_namespace},
            previous_episode_id=previous_episode_id,
        )

    def _apply_peak(
        self,
        episode: Optional[PeakEpisode],
        observation: PeakObservation,
        cause_signature: str,
        episodes: dict[str, PeakEpisode],
        active_by_stream_cause: dict[tuple[str, str], list[str]],
    ) -> EpisodeTransition:
        if episode is not None and observation.window_decision_id in episode.seen_window_ids:
            allocated = min(observation.namespace_raw_lines, observation.cause_family_raw_lines)
            return EpisodeTransition(
                episode_id=episode.episode_id,
                window_decision_id=observation.window_decision_id,
                stream_key=observation.stream_key,
                window_start_utc=observation.window_start_utc,
                previous_state=episode.state,
                state=episode.state,
                cause_signature=cause_signature,
                correlation_method="idempotent_replay",
                correlation_version=CORRELATION_VERSION,
                confidence=observation.confidence,
                allocated_raw_error_lines=allocated,
                unexplained_raw_lines=max(0, observation.namespace_raw_lines - allocated),
                current_raw_error_lines=episode.current_raw_error_lines,
                cumulative_raw_error_lines=episode.cumulative_raw_error_lines,
                previous_raw_error_lines=episode.current_raw_error_lines,
                contributor_fingerprints=observation.contributor_fingerprints,
                material_change_reasons=episode.material_change_reasons,
                previous_episode_id=episode.previous_episode_id,
            )
        previous_lines = episode.current_raw_error_lines if episode is not None else None
        if episode is None:
            previous = self._previous_resolved(episodes, observation, cause_signature)
            episode = self._new_episode(
                observation,
                cause_signature,
                recurrence=previous is not None,
                previous_episode_id=previous.episode_id if previous else None,
            )
            episodes[episode.episode_id] = episode
            active_by_stream_cause.setdefault(
                (observation.stream_key, cause_signature), []
            ).append(episode.episode_id)
            previous_state = None
            state = episode.state
            method = "event_time_cause_match" if previous else "new_cause"
            reasons: Tuple[str, ...] = ()
        else:
            previous_state = episode.state
            reasons_list = []
            same_window = episode.last_window_start_utc == observation.window_start_utc
            if same_window:
                reasons_list.extend(episode.material_change_reasons)
            if observation.signal_namespace not in episode.active_namespaces:
                reasons_list.append("new_namespace")
            if (
                previous_lines > 0
                and observation.cause_family_raw_lines
                >= previous_lines * self.escalation_ratio
            ):
                reasons_list.append("material_impact_increase")
            if (
                episode.current_operation_occurrences is not None
                and observation.unique_operation_occurrences is not None
                and observation.unique_operation_occurrences
                > episode.current_operation_occurrences
                * self.escalation_ratio
            ):
                reasons_list.append("operation_impact_increase")
            if episode.state == "RECOVERY":
                reasons_list.append("recovered_signal_returned")
            reasons = tuple(sorted(set(reasons_list)))
            state = "EXPANSION" if "new_namespace" in reasons else (
                "ESCALATION" if reasons else "CONTINUATION"
            )
            method = "event_time_cause_match"
            episode.state = state
            episode.last_window_start_utc = observation.window_start_utc
            episode.current_raw_error_lines = observation.cause_family_raw_lines
            episode.cumulative_raw_error_lines += observation.cause_family_raw_lines
            episode.current_operation_occurrences = observation.unique_operation_occurrences
            if (
                episode.cumulative_operation_occurrences is not None
                and observation.unique_operation_occurrences is not None
            ):
                episode.cumulative_operation_occurrences += observation.unique_operation_occurrences
            elif observation.unique_operation_occurrences is not None:
                episode.cumulative_operation_occurrences = observation.unique_operation_occurrences
            episode.active_namespaces.add(observation.signal_namespace)
            episode.diagnosis_confidence = min(
                (episode.diagnosis_confidence, observation.confidence),
                key=("low", "medium", "high").index,
            )
            episode.material_change_reasons = reasons
            episode.non_peak_windows = 0
        episode.seen_window_ids.add(observation.window_decision_id)
        allocated = min(observation.namespace_raw_lines, observation.cause_family_raw_lines)
        return EpisodeTransition(
            episode_id=episode.episode_id,
            window_decision_id=observation.window_decision_id,
            stream_key=observation.stream_key,
            window_start_utc=observation.window_start_utc,
            previous_state=previous_state,
            state=state,
            cause_signature=cause_signature,
            correlation_method=method,
            correlation_version=CORRELATION_VERSION,
            confidence=observation.confidence,
            allocated_raw_error_lines=allocated,
            unexplained_raw_lines=max(0, observation.namespace_raw_lines - allocated),
            current_raw_error_lines=episode.current_raw_error_lines,
            cumulative_raw_error_lines=episode.cumulative_raw_error_lines,
            previous_raw_error_lines=previous_lines,
            material_change_reasons=reasons,
            contributor_fingerprints=observation.contributor_fingerprints,
            previous_episode_id=episode.previous_episode_id,
        )

    def _apply_recovery(
        self,
        episode: PeakEpisode,
        observation: PeakObservation,
    ) -> EpisodeTransition:
        if observation.window_decision_id in episode.seen_window_ids:
            return EpisodeTransition(
                episode_id=episode.episode_id,
                window_decision_id=observation.window_decision_id,
                stream_key=observation.stream_key,
                window_start_utc=observation.window_start_utc,
                previous_state=episode.state,
                state=episode.state,
                cause_signature=episode.cause_signature,
                correlation_method="idempotent_replay",
                correlation_version=CORRELATION_VERSION,
                confidence=episode.diagnosis_confidence,
                allocated_raw_error_lines=0,
                unexplained_raw_lines=0,
                current_raw_error_lines=episode.current_raw_error_lines,
                cumulative_raw_error_lines=episode.cumulative_raw_error_lines,
                previous_raw_error_lines=episode.current_raw_error_lines,
                contributor_fingerprints=observation.contributor_fingerprints,
            )
        previous_state = episode.state
        previous_lines = episode.current_raw_error_lines
        is_new_window = observation.window_start_utc > episode.last_window_start_utc
        if is_new_window:
            episode.non_peak_windows += 1
            episode.last_window_start_utc = observation.window_start_utc
            episode.current_raw_error_lines = 0
            episode.state = (
                "RESOLVED"
                if episode.non_peak_windows >= self.resolve_non_peak_windows
                else "RECOVERY"
            )
            if episode.state == "RESOLVED":
                episode.resolved_at_utc = observation.window_start_utc
        episode.seen_window_ids.add(observation.window_decision_id)
        return EpisodeTransition(
            episode_id=episode.episode_id,
            window_decision_id=observation.window_decision_id,
            stream_key=observation.stream_key,
            window_start_utc=observation.window_start_utc,
            previous_state=previous_state,
            state=episode.state,
            cause_signature=episode.cause_signature,
            correlation_method="event_time_recovery",
            correlation_version=CORRELATION_VERSION,
            confidence=episode.diagnosis_confidence,
            allocated_raw_error_lines=0,
            unexplained_raw_lines=0,
            current_raw_error_lines=episode.current_raw_error_lines,
            cumulative_raw_error_lines=episode.cumulative_raw_error_lines,
            previous_raw_error_lines=previous_lines,
        )

    @staticmethod
    def _previous_resolved(
        episodes: Mapping[str, PeakEpisode],
        observation: PeakObservation,
        cause_signature: str,
    ) -> Optional[PeakEpisode]:
        previous = [
            episode
            for episode in episodes.values()
            if episode.stream_key == observation.stream_key
            and episode.cause_signature == cause_signature
            and episode.state == "RESOLVED"
            and episode.last_window_start_utc < observation.window_start_utc
        ]
        return max(previous, key=lambda item: (item.last_window_start_utc, item.episode_id), default=None)


def observations_from_decisions(
    decisions: Iterable[Mapping[str, Any]],
    cause_families: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> Tuple[PeakObservation, ...]:
    """Build observations keyed by ``(window_decision_id, cause_signature)``."""
    cause_families = cause_families or {}
    observations = []
    for decision in decisions:
        families = decision.get("cause_families") or decision.get("families") or ()
        if not families:
            families = [None]
        for family in families:
            family = family or {}
            observations.append(
                PeakObservation.from_mapping(
                    decision,
                    cause=(
                        cause_families.get(
                            (decision.get("window_decision_id"), family.get("signature"))
                        )
                        or family
                    ),
                )
            )
    return tuple(observations)


def _episode_from_mapping(value: Mapping[str, Any]) -> PeakEpisode:
    """Restore the minimum episode state needed for event-time continuation."""
    def _optional_int(item: Any) -> Optional[int]:
        return int(item) if item is not None else None

    return PeakEpisode(
        episode_id=str(value.get("episode_id") or ""),
        stream_key=str(value.get("stream_key") or ""),
        cause_signature=str(value.get("cause_signature") or "unresolved"),
        cause_signature_version=str(
            value.get("cause_signature_version") or CAUSE_SIGNATURE_VERSION
        ),
        state=str(value.get("state") or "RESOLVED"),
        first_window_start_utc=_utc(
            value.get("first_window_start_utc"), "first_window_start_utc"
        ),
        last_window_start_utc=_utc(
            value.get("last_window_start_utc"), "last_window_start_utc"
        ),
        current_raw_error_lines=_positive_int(value.get("current_raw_error_lines")),
        cumulative_raw_error_lines=_positive_int(
            value.get("cumulative_raw_error_lines")
        ),
        current_operation_occurrences=_optional_int(
            value.get("current_operation_occurrences")
        ),
        cumulative_operation_occurrences=_optional_int(
            value.get("cumulative_operation_occurrences")
        ),
        diagnosis_confidence=str(value.get("diagnosis_confidence") or "low"),
        active_namespaces=set(str(item) for item in (value.get("active_namespaces") or ())),
        material_change_reasons=tuple(
            sorted(str(item) for item in (value.get("material_change_reasons") or ()))
        ),
        non_peak_windows=_positive_int(value.get("non_peak_windows")),
        previous_episode_id=value.get("previous_episode_id") or None,
        seen_window_ids={
            str(item).strip() for item in (value.get("seen_window_ids") or ())
        },
        resolved_at_utc=(
            _utc(value.get("resolved_at_utc"), "resolved_at_utc")
            if value.get("resolved_at_utc") else None
        ),
    )


def materialize_episode_state(
    decisions: Iterable[Mapping[str, Any]],
    cause_families: Iterable[Mapping[str, Any]],
    *,
    resolve_non_peak_windows: int = 2,
    escalation_ratio: float = 1.5,
    prior_episodes: Iterable[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Correlate decision payloads with current-run cause-family evidence."""
    families = tuple(cause_families or ())
    enriched_decisions = []
    for decision in decisions:
        namespace = str(
            decision.get("signal_namespace") or decision.get("namespace") or ""
        )
        matching_families = []
        for family in families:
            namespace_counts = family.get("namespace_counts") or {}
            namespace_lines = int(namespace_counts.get(namespace, 0) or 0)
            if namespace_lines <= 0:
                continue
            family_namespaces = sorted(
                str(key)
                for key, value in namespace_counts.items()
                if int(value or 0) > 0
            )
            namespace_family = dict(family)
            namespace_family["raw_error_lines"] = namespace_lines
            if family.get("unique_operations") is not None:
                namespace_family["unique_operations"] = (
                    int(family["unique_operations"])
                    if namespace == family_namespaces[0]
                    else 0
                )
            matching_families.append(namespace_family)
        enriched = dict(decision)
        enriched["cause_families"] = matching_families
        enriched_decisions.append(enriched)

    observations = observations_from_decisions(enriched_decisions)
    correlator = PeakEpisodeCorrelator(
        resolve_non_peak_windows=resolve_non_peak_windows,
        escalation_ratio=escalation_ratio,
    )
    episodes = correlator.correlate(observations, prior_episodes=prior_episodes)
    transitioned_episode_ids = {
        transition.episode_id for transition in correlator.last_transitions
    }
    return (
        [
            episode.to_dict()
            for episode in episodes
            if episode.episode_id in transitioned_episode_ids
        ],
        [transition.to_dict() for transition in correlator.last_transitions],
    )