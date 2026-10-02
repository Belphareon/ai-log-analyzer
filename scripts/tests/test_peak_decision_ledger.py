from datetime import datetime, timezone

from scripts.core.peak_decision import (
    build_contributor_rows,
    build_decision_rows,
    decision_from_audit,
    densify_decision_windows,
    materialize_namespace_decisions,
    materialize_decision_windows,
)


WINDOW = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)


def _audit(namespace="pcb-sit-01-app", peak=True):
    return {
        "window_start": WINDOW.isoformat(),
        "namespace": namespace,
        "namespace_total": 4760 if peak else 12,
        "is_namespace_peak": peak,
        "p93_threshold": 100,
        "cap_threshold": 80,
        "triggered_by": "both" if peak else None,
        "threshold_snapshot_id": "snapshot-1",
        "peak_identifier": "SPIKE:NS:pcb-sit-01-app:2026-09-30T13:00:00+00:00" if peak else None,
        "owner_fingerprint": "fp-cause" if peak else None,
        "family_decisions": [
            {
                "fingerprint": "fp-cause",
                "contribution": 4500,
                "threshold": 20,
                "baseline": 2,
                "anomaly_score": 225,
                "method": "namespace_fingerprint_median_mad",
                "is_anomalous": True,
                "error_type": "BusinessException",
                "normalized_message": "Person not found",
                "apps": ["svc-a"],
            },
            {
                "fingerprint": "fp-wrapper",
                "contribution": 260,
                "threshold": 1000,
                "baseline": 200,
                "anomaly_score": 0.26,
                "method": "namespace_fingerprint_median_mad",
                "is_anomalous": False,
            },
        ],
    }


def test_decision_identity_is_idempotent_and_keeps_all_contributors():
    first = decision_from_audit(_audit(), stream_key="replay-2026-09-30")
    second = decision_from_audit(_audit(), stream_key="replay-2026-09-30")

    assert first.window_decision_id == second.window_decision_id
    assert first.is_peak
    assert first.diagnosis_status == "diagnosed"
    assert [item["fingerprint"] for item in first.contributors] == [
        "fp-cause",
        "fp-wrapper",
    ]


def test_materialization_creates_zero_decisions_for_missing_namespaces():
    decisions = materialize_namespace_decisions(
        [_audit()],
        ["pcb-sit-01-app", "pcb-uat-01-app"],
        window_start=WINDOW,
        contract_hash="contract-1",
        run_id="run-1",
    )

    assert len(decisions) == 2
    missing = next(item for item in decisions if item.signal_namespace == "pcb-uat-01-app")
    assert not missing.is_peak
    assert missing.verdict_reason == "below_min_volume"
    assert missing.namespace_raw_lines == 0
    assert missing.contract_hash == "contract-1"


def test_decision_and_contributor_rows_are_deterministic():
    decisions = materialize_namespace_decisions(
        [_audit()],
        ["pcb-sit-01-app"],
        window_start=WINDOW,
        run_id="run-1",
    )

    decision_rows = build_decision_rows(decisions, "run-1")
    contributor_rows = build_contributor_rows(decisions, "run-1")

    assert decision_rows[0][1] == decisions[0].window_decision_id
    assert decision_rows[0][13] is True
    assert len(contributor_rows) == 2
    assert contributor_rows[0][2] == "fp-cause"


def test_materialize_multiple_windows_keeps_each_namespace_timeline():
    second_window = WINDOW.replace(minute=15)
    audits = [_audit(), {**_audit(), "window_start": second_window.isoformat()}]

    decisions = materialize_decision_windows(
        audits,
        ["pcb-sit-01-app", "pcb-ch-dev-01-app"],
        window_starts=[WINDOW, second_window],
        stream_key="replay-1",
    )

    assert len(decisions) == 4
    assert {
        (item.window_start_utc, item.signal_namespace)
        for item in decisions
    } == {
        (WINDOW, "pcb-sit-01-app"),
        (WINDOW, "pcb-ch-dev-01-app"),
        (second_window, "pcb-sit-01-app"),
        (second_window, "pcb-ch-dev-01-app"),
    }


def test_densify_preserves_existing_peak_and_adds_missing_window_rows():
    existing = materialize_namespace_decisions(
        [_audit()],
        ["pcb-sit-01-app"],
        window_start=WINDOW,
        stream_key="replay-1",
    )
    decisions = densify_decision_windows(
        [item.to_dict() for item in existing],
        ["pcb-sit-01-app", "pcb-uat-01-app"],
        window_starts=[WINDOW, WINDOW.replace(minute=15)],
        stream_key="replay-1",
    )

    assert len(decisions) == 4
    preserved = next(
        item for item in decisions
        if item.window_start_utc == WINDOW and item.signal_namespace == "pcb-sit-01-app"
    )
    assert preserved.is_peak
    assert next(
        item for item in decisions
        if item.window_start_utc == WINDOW.replace(minute=15)
        and item.signal_namespace == "pcb-uat-01-app"
    ).verdict_reason == "below_min_volume"