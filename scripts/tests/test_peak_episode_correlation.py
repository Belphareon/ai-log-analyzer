from datetime import datetime, timedelta, timezone

from scripts.core.peak_episode import (
    PeakEpisodeCorrelator,
    PeakObservation,
)


START = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)


def observation(
    offset=0,
    *,
    decision_id=None,
    namespace="pcb-sit-01-app",
    cause="cause-a",
    peak=True,
    lines=100,
    fingerprints=("fp-a",),
):
    return PeakObservation(
        window_decision_id=decision_id or f"decision-{offset}-{namespace}-{cause}",
        stream_key="replay-1",
        signal_namespace=namespace,
        window_start_utc=START + timedelta(minutes=15 * offset),
        is_peak=peak,
        namespace_raw_lines=lines if peak else 0,
        cause_signature=cause,
        cause_family_raw_lines=lines if peak else 0,
        unique_operation_occurrences=lines // 10 if peak else None,
        confidence="high" if peak else "low",
        contributor_fingerprints=fingerprints,
        material_impact=lines,
    )


def test_same_cause_continues_and_new_namespace_expands():
    correlator = PeakEpisodeCorrelator()
    episodes = correlator.correlate([
        observation(0, lines=100),
        observation(1, lines=120),
        observation(1, namespace="pcb-ch-sit-01-app", lines=80),
    ])

    assert len(episodes) == 1
    episode = episodes[0]
    assert episode.state == "EXPANSION"
    assert episode.active_namespaces == {"pcb-sit-01-app", "pcb-ch-sit-01-app"}
    assert set(episode.material_change_reasons) == {
        "new_namespace",
        "material_impact_increase",
    }
    states = [transition.state for transition in correlator.last_transitions]
    assert states == ["START", "EXPANSION", "EXPANSION"]


def test_different_cause_does_not_merge_even_in_same_window():
    correlator = PeakEpisodeCorrelator()
    episodes = correlator.correlate([
        observation(0, cause="cause-a"),
        observation(1, cause="cause-b"),
    ])

    assert len(episodes) == 2
    assert [transition.state for transition in correlator.last_transitions] == ["START", "START"]


def test_recovery_resolves_and_later_cause_is_recurrence():
    correlator = PeakEpisodeCorrelator(resolve_non_peak_windows=2)
    episodes = correlator.correlate([
        observation(0),
        observation(1, peak=False),
        observation(2, peak=False),
        observation(3),
    ])

    assert len(episodes) == 2
    states = [transition.state for transition in correlator.last_transitions]
    assert states == ["START", "RECOVERY", "RESOLVED", "RECURRENCE"]
    resolved = next(episode for episode in episodes if episode.state == "RESOLVED")
    recurrence = next(episode for episode in episodes if episode.state == "RECURRENCE")
    assert resolved.episode_id != recurrence.episode_id
    assert recurrence.previous_episode_id == resolved.episode_id


def test_transitions_retain_current_and_cumulative_raw_lines():
    correlator = PeakEpisodeCorrelator(resolve_non_peak_windows=2)
    correlator.correlate([
        observation(0, lines=100),
        observation(1, lines=120),
        observation(2, peak=False),
    ])

    assert [
        (transition.current_raw_error_lines, transition.cumulative_raw_error_lines)
        for transition in correlator.last_transitions
    ] == [(100, 100), (120, 220), (0, 220)]
    assert [transition.previous_raw_error_lines for transition in correlator.last_transitions] == [
        None,
        100,
        120,
    ]


def test_replay_order_does_not_change_episode_identity_or_states():
    values = [observation(0), observation(1, lines=200), observation(2, cause="cause-b")]
    first = PeakEpisodeCorrelator().correlate(values)
    second_correlator = PeakEpisodeCorrelator()
    second = second_correlator.correlate(list(reversed(values)))

    assert [episode.episode_id for episode in first] == [episode.episode_id for episode in second]
    assert [episode.state for episode in first] == [episode.state for episode in second]
    assert [transition.state for transition in second_correlator.last_transitions] == [
        "START", "ESCALATION", "START"
    ]


def test_prior_episode_state_continues_across_run_boundary():
    first_correlator = PeakEpisodeCorrelator()
    first_episode = first_correlator.correlate([observation(0)])[0]

    second_correlator = PeakEpisodeCorrelator()
    second_episodes = second_correlator.correlate(
        [observation(1, lines=120)],
        prior_episodes=[first_episode.to_dict()],
    )

    assert len(second_episodes) == 1
    assert second_episodes[0].episode_id == first_episode.episode_id
    assert second_episodes[0].state == "CONTINUATION"
    assert second_correlator.last_transitions[0].previous_state == "START"


def test_prior_diagnosed_episode_recovers_from_no_cause_decisions():
    first_correlator = PeakEpisodeCorrelator(resolve_non_peak_windows=2)
    first_episode = first_correlator.correlate([observation(0)])[0]

    second_correlator = PeakEpisodeCorrelator(resolve_non_peak_windows=2)
    second_episodes = second_correlator.correlate(
        [
            observation(1, peak=False, decision_id="recovery-a"),
            observation(
                1,
                peak=False,
                namespace="pcb-ch-sit-01-app",
                decision_id="recovery-b",
            ),
        ],
        prior_episodes=[first_episode.to_dict()],
    )

    assert len(second_episodes) == 1
    assert second_episodes[0].episode_id == first_episode.episode_id
    assert second_episodes[0].state == "RECOVERY"
    assert second_episodes[0].non_peak_windows == 1
    assert [transition.state for transition in second_correlator.last_transitions] == [
        "RECOVERY",
        "RECOVERY",
    ]


def test_undiagnosed_fallback_requires_contributor_overlap():
    def decision(window_start, fingerprints):
        return {
            "window_decision_id": f"decision-{window_start.isoformat()}",
            "stream_key": "replay-1",
            "signal_namespace": "pcb-sit-01-app",
            "window_start_utc": window_start.isoformat(),
            "is_peak": True,
            "namespace_raw_lines": 100,
            "diagnosis_status": "undiagnosed",
            "contributors": [
                {
                    "fingerprint": fingerprint,
                    "is_anomalous": False,
                    "contribution": 50,
                }
                for fingerprint in fingerprints
            ],
        }

    first = PeakObservation.from_mapping(
        decision(START, ("fp-a",)),
    )
    second = PeakObservation.from_mapping(
        decision(START + timedelta(minutes=15), ("fp-a",)),
    )
    assert first.contributor_fingerprints == ("fp-a",)
    assert PeakEpisodeCorrelator().correlate([first, second])[0].state == "CONTINUATION"

    no_evidence = PeakObservation.from_mapping(decision(START, ()))
    later_no_evidence = PeakObservation.from_mapping(
        decision(START + timedelta(minutes=15), ()),
    )
    assert no_evidence.normalized_cause_signature() != later_no_evidence.normalized_cause_signature()
    assert len(PeakEpisodeCorrelator().correlate([no_evidence, later_no_evidence])) == 2