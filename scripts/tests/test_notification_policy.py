from dataclasses import replace

import pytest

from scripts.core.notification_policy import (
    decide_notification_candidates,
    decision_summary,
)


def candidate(episode_id, state, **kwargs):
    return {
        "episode_id": episode_id,
        "window_decision_id": f"decision-{episode_id}",
        "stream_key": "live",
        "episode_state": state,
        "namespace_ratio": kwargs.pop("namespace_ratio", 1),
        **kwargs,
    }


def test_test_origin_is_visible_and_detail_limit_does_not_omit_candidates():
    decisions = decide_notification_candidates(
        [
            candidate("episode-1", "START", test_originator_application="MochaXTestApp"),
            candidate("episode-2", "START"),
            candidate("episode-3", "EXPANSION"),
            candidate("episode-4", "START"),
        ],
        detail_limit=3,
    )

    assert len(decisions) == 4
    assert all(decision.policy_outcome != "route_suppressed" for decision in decisions)
    assert sum(decision.policy_outcome == "primary_send" for decision in decisions) == 3
    assert sum(decision.policy_outcome == "digest_only" for decision in decisions) == 1
    assert next(
        decision for decision in decisions if decision.episode_id == "episode-1"
    ).test_origin_label == "MochaXTestApp"


def test_continuation_is_not_sent_unless_materially_changed():
    decisions = decide_notification_candidates([
        candidate("episode-1", "CONTINUATION"),
        candidate("episode-2", "CONTINUATION", material_change_reasons=["new_namespace"]),
        candidate("episode-3", "ESCALATION"),
    ])

    by_episode = {decision.episode_id: decision for decision in decisions}
    assert by_episode["episode-1"].policy_outcome == "no_material_change"
    assert by_episode["episode-2"].policy_outcome == "primary_send"
    assert by_episode["episode-3"].policy_outcome == "primary_send"
    assert decision_summary(decisions) == {
        "candidates": 3,
        "primary_send": 2,
        "digest_only": 0,
        "route_suppressed": 0,
        "no_material_change": 1,
    }


def test_only_high_confidence_expected_outcomes_are_demoted():
    decisions = decide_notification_candidates([
        candidate("expected", "START", assessment="expected_outcome_logged_as_error", confidence="high"),
        candidate("uncertain", "START", assessment="expected_outcome_logged_as_error", confidence="low"),
        candidate("unknown", "START", assessment="unknown"),
    ], detail_limit=0)
    outcomes = {item.episode_id: item.policy_outcome for item in decisions}
    assert outcomes == {"expected": "digest_only", "uncertain": "primary_send", "unknown": "primary_send"}


def test_stable_expected_outcome_is_not_resent_but_escalation_is_visible():
    decisions = decide_notification_candidates([
        candidate("stable", "CONTINUATION", assessment="expected_outcome_logged_as_error", confidence="high"),
        candidate("worse", "ESCALATION", assessment="expected_outcome_logged_as_error", confidence="high"),
        candidate("heartbeat", "CONTINUATION", heartbeat_due=True),
    ])
    outcomes = {item.episode_id: item.policy_outcome for item in decisions}
    assert outcomes == {"stable": "no_material_change", "worse": "primary_send", "heartbeat": "primary_send"}


def test_no_material_change_is_explicit_when_requested_by_caller():
    decision = decide_notification_candidates([
        candidate(
            "episode-1",
            "CONTINUATION",
            no_material_change=True,
            no_material_change_reason="cooldown_active",
        ),
    ])[0]

    assert decision.policy_outcome == "no_material_change"
    assert decision.candidate_reason == "cooldown_active"


def test_zero_detail_limit_means_unlimited():
    decisions = decide_notification_candidates(
        [candidate("episode-1", "START"), candidate("episode-2", "START")],
        detail_limit=0,
    )

    assert [decision.policy_outcome for decision in decisions] == [
        "primary_send",
        "primary_send",
    ]


def test_same_window_delivery_guard_overrides_even_a_new_episode():
    decision = decide_notification_candidates([
        candidate("episode-1", "START", no_material_change=True,
                  no_material_change_reason="same_window_duplicate"),
    ])[0]
    assert decision.policy_outcome == "no_material_change"
    assert decision.candidate_reason == "same_window_duplicate"


def test_digest_and_suppressed_candidates_do_not_consume_primary_detail_limit():
    decisions = decide_notification_candidates([
        candidate("expected", "START", assessment="expected_outcome_logged_as_error", confidence="high"),
        candidate("suppressed", "START", route_suppressed=True),
        candidate("technical", "ESCALATION", assessment="technical_failure"),
    ], detail_limit=1)
    assert next(item for item in decisions if item.episode_id == "technical").policy_outcome == "primary_send"


def test_policy_rejects_incomplete_routing_identity():
    decision = decide_notification_candidates([candidate("episode-1", "START")])[0]

    with_invalid_destination = replace(decision, destination="")
    with pytest.raises(ValueError, match="notification decision routing is incomplete"):
        with_invalid_destination.validate()