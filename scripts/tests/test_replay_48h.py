"""Tests for the isolated multi-window historical replay runner."""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, SCRIPTS)

import replay_48h as replay  # noqa: E402


def test_48h_replay_produces_192_aligned_window_ends():
    period_end = datetime(2026, 9, 22, 10, 45, tzinfo=timezone.utc)

    windows = replay.replay_window_ends(period_end, 48)

    assert len(windows) == 192
    assert windows[0] == datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc)
    assert windows[-1] == period_end


def test_summary_counts_attributed_and_suppressed_namespace_peaks():
    results = [
        {
            'status': 'success',
            'fetch_complete': True,
            'expected_count': 40,
            'fetched_count': 40,
            'family_baseline_available': True,
            'namespace_peak_audit': [
                {
                    'is_namespace_peak': True,
                    'owner_fingerprint': 'fp-a',
                    'threshold_snapshot_id': 'snapshot-1',
                    'namespace_total': 80,
                    'family_decisions': [{
                        'fingerprint': 'fp-a',
                        'contribution': 60,
                        'threshold': 20.0,
                        'is_anomalous': True,
                    }],
                },
                {
                    'is_namespace_peak': True,
                    'owner_fingerprint': None,
                    'suppressed_reason': 'no_anomalous_family',
                    'threshold_snapshot_id': 'snapshot-1',
                    'namespace_total': 70,
                    'family_decisions': [{
                        'fingerprint': 'fp-routine',
                        'contribution': 8,
                        'threshold': 20.0,
                        'is_anomalous': False,
                    }],
                },
                {'is_namespace_peak': False, 'threshold_snapshot_id': 'snapshot-1'},
            ],
        },
    ]

    summary = replay.summarize(results, hours=1)

    assert summary['expected_windows'] == 4
    assert summary['completed_windows'] == 1
    assert summary['expected_errors'] == summary['fetched_errors'] == 40
    assert summary['namespace_window_evaluations'] == 3
    assert summary['namespace_volume_peaks'] == 2
    assert summary['attributed_peaks'] == 1
    assert summary['suppressed_volume_peaks'] == 1
    assert summary['suppression_reasons'] == {'no_anomalous_family': 1}
    assert summary['threshold_snapshot_ids'] == ['snapshot-1']
    assert summary['top_attributed_peaks'][0]['owner']['fingerprint'] == 'fp-a'
    assert (
        summary['top_suppressed_volume_peaks'][0]['top_families'][0]['fingerprint']
        == 'fp-routine'
    )


def test_replay_threshold_bundle_is_versioned_and_uses_training_cutoff():
    cutoff = datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc)
    bundle = replay._serialize_threshold_bundle(
        {
            ('ns-a', 6): [0.0, 10.0, 20.0, 30.0],
        },
        {
            'min': datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc),
            'max': datetime(2026, 9, 20, 10, 45, tzinfo=timezone.utc),
        },
        cutoff,
        weeks=4,
        percentile_level=0.93,
    )

    assert bundle['bundle_id'] == 'replay-memory-v4.0-asof-20260920T110000Z'
    assert bundle['metadata']['training_cutoff'] == cutoff.isoformat()
    assert bundle['metadata']['persistence'] == 'none'
    assert bundle['thresholds'] == [{
        'namespace': 'ns-a',
        'day_of_week': 6,
        'value': 30.0,
        'samples': 3,
    }]
    assert bundle['caps']['ns-a'] == {'value': 30.0, 'samples': 3}


def test_replay_stops_after_first_window_crash_without_result(monkeypatch):
    period_end = datetime(2026, 9, 22, 10, 45, tzinfo=timezone.utc)
    window_ends = [
        datetime(2026, 9, 22, 10, 30, tzinfo=timezone.utc),
        period_end,
    ]
    subprocess_calls = []
    threshold_bundle = {
        'bundle_id': 'replay-memory-v4.0-asof-20260922T100000Z',
        'metadata': {
            'percentile_level': 0.93,
            'population_grain': 'namespace/15m/day_of_week/active_windows',
            'percentile_method': 'configured_percentile_capped_by_median_plus_6_scaled_mad',
            'calculation_version': '4.0',
            'training_weeks': 4,
            'training_cutoff': '2026-09-22T10:00:00+00:00',
        },
        'thresholds': [{'namespace': 'ns-a', 'day_of_week': 1, 'value': 10, 'samples': 20}],
        'caps': {'ns-a': {'value': 10, 'samples': 100}},
    }

    monkeypatch.setattr(replay, 'replay_window_ends', lambda *_args: window_ends)
    monkeypatch.setattr(
        replay,
        'build_replay_threshold_bundle',
        lambda *_args, **_kwargs: threshold_bundle,
    )

    def crash_without_result(command, **_kwargs):
        subprocess_calls.append(command)
        return SimpleNamespace(returncode=1, stdout='detector traceback')

    monkeypatch.setattr(replay.subprocess, 'run', crash_without_result)

    report = replay.run_replay(period_end, hours=1)

    assert len(subprocess_calls) == 1
    assert report['status'] == 'incomplete'
    assert report['summary']['completed_windows'] == 0
    assert report['failures'][0]['output'] == 'detector traceback'