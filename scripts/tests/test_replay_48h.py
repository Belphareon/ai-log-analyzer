"""Tests for the isolated multi-window historical replay runner."""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


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
            ('ns-a', 6, 11, 0): [0.0, 10.0, 20.0, 30.0],
        },
        {
            'min': datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc),
            'max': datetime(2026, 9, 20, 10, 45, tzinfo=timezone.utc),
        },
        cutoff,
        weeks=12,
        percentile_level=0.93,
    )

    assert bundle['bundle_id'] == 'replay-memory-v5.0-asof-20260920T110000Z'
    assert bundle['metadata']['training_cutoff'] == cutoff.isoformat()
    assert bundle['metadata']['persistence'] == 'none'
    assert bundle['thresholds'] == [{
        'namespace': 'ns-a',
        'day_of_week': 6,
        'hour_of_day': 11,
        'quarter_hour': 0,
        'value': 30.0,
        'samples': 4,
        'profile_status': 'init',
    }]
    assert bundle['caps'] == {}


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


def test_es_count_query_requires_exact_dense_reconciled_windows():
    start = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 26, 0, 15, tzinfo=timezone.utc)
    payload = {
        'hits': {'total': {'value': 5, 'relation': 'eq'}},
        '_shards': {'failed': 0}, 'timed_out': False,
        'aggregations': {'namespaces': {'buckets': {'ns-a': {'windows': {'buckets': [
            {'key': int(start.timestamp() * 1000), 'doc_count': 5},
        ]}}}}},
    }
    session = SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payload,
    ))
    assert replay.fetch_es_namespace_counts(session, 'https://es', 'logs-*', ['ns-a'], start, end) == [(start, 'ns-a', 5)]
    payload['hits']['total']['value'] = 6
    with pytest.raises(RuntimeError, match='reconcile'):
        replay.fetch_es_namespace_counts(session, 'https://es', 'logs-*', ['ns-a'], start, end)
    payload['timed_out'] = True
    with pytest.raises(RuntimeError, match='incomplete'):
        replay.fetch_es_namespace_counts(session, 'https://es', 'logs-*', ['ns-a'], start, end)


@pytest.mark.parametrize('percentile_level', [0.94, 0.95])
@pytest.mark.parametrize('retained_weeks', [1, 2])
def test_es_replay_trains_only_before_holdout_and_uses_real_detector(monkeypatch, percentile_level, retained_weeks):
    from datetime import timedelta
    import dotenv
    import requests
    import core.namespace_contract as contract
    end = datetime(2026, 10, 27, 7, tzinfo=timezone.utc)
    cutoff = end - timedelta(hours=24)
    retained_start = cutoff - timedelta(weeks=retained_weeks)
    captured_hosts = []

    class Session:
        def mount(self, _host, adapter):
            assert adapter.max_retries.total == 2
            assert adapter.max_retries.allowed_methods == ['POST']

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    def counts(_session, host, _indices, _namespaces, start, stop):
        captured_hosts.append(host)
        return [
            (timestamp, 'ns-a', 0 if timestamp < retained_start else 100 if timestamp == cutoff else 10)
            for timestamp in [start + timedelta(minutes=15 * index)
                              for index in range(int((stop - start).total_seconds() // 900))]
        ]

    monkeypatch.setattr(dotenv, 'dotenv_values', lambda *_args: {'ES_USER': 'test', 'ES_PASSWORD': 'test', 'ES_INDEX': 'logs-*'})
    monkeypatch.setattr(requests, 'Session', Session)
    monkeypatch.setattr(contract, 'load_canonical_namespaces', lambda: ('ns-a',))
    monkeypatch.setattr(replay, 'fetch_es_namespace_counts', counts)
    monkeypatch.setenv('ES_HOST', 'https://wrong-global-profile')
    monkeypatch.delenv('NPROD_ES_HOST', raising=False)
    monkeypatch.delenv('NPROD_MONITORED_NAMESPACES', raising=False)
    report = replay.run_es_replay(end, 24, 12, 'nprod', percentile_level)
    assert set(captured_hosts) == {'https://elasticsearch-test.kb.cz:9500'}
    assert report['threshold_bundle']['metadata']['training_cutoff'] == cutoff.isoformat()
    assert report['threshold_bundle']['metadata']['training_weeks'] == 12
    assert report['threshold_bundle']['metadata']['training_start'] == retained_start.isoformat()
    assert {item['samples'] for item in report['threshold_bundle']['thresholds']} == {retained_weeks}
    assert report['threshold_bundle']['metadata']['history_completeness'] == 'unverified_es_retention_and_ingestion'
    assert report['period_start'] == '2026-10-26T07:00:00+00:00'
    assert report['windows'][0]['window_start'] == report['period_start']
    assert report['windows'][0]['error_count'] == 100
    assert report['windows'][0]['is_peak']
    assert len(report['windows']) == 96
    assert report['summary']['errors'] == 1050
    assert report['summary']['namespace_volume_peaks'] == 1
    assert report['summary']['profile_status_counts'] == {'init': 96, 'mature': 0, 'missing': 0}
    assert all(item['percentile_level'] == percentile_level for item in report['windows'])
    assert report['verification_scope'] == 'namespace_volume_detector_only'


@pytest.mark.parametrize('fault', ['shard', 'missing_namespace', 'missing_window', 'misaligned_window'])
def test_es_count_query_rejects_partial_namespace_grids(fault):
    start = datetime(2026, 10, 26, tzinfo=timezone.utc)
    end = datetime(2026, 10, 26, 0, 15, tzinfo=timezone.utc)
    payload = {
        'hits': {'total': {'value': 0, 'relation': 'eq'}}, '_shards': {'failed': 0},
        'aggregations': {'namespaces': {'buckets': {'ns-a': {'windows': {'buckets': [
            {'key': int(start.timestamp() * 1000), 'doc_count': 0},
        ]}}}}},
    }
    session = SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: payload,
    ))
    assert replay.fetch_es_namespace_counts(session, 'https://es', 'logs-*', ['ns-a'], start, end) == [(start, 'ns-a', 0)]
    if fault == 'shard':
        payload['_shards']['failed'] = 1
    elif fault == 'missing_namespace':
        payload['aggregations']['namespaces']['buckets'] = {}
    elif fault == 'missing_window':
        payload['aggregations']['namespaces']['buckets']['ns-a']['windows']['buckets'] = []
    else:
        payload['aggregations']['namespaces']['buckets']['ns-a']['windows']['buckets'][0]['key'] += 1
    with pytest.raises(RuntimeError):
        replay.fetch_es_namespace_counts(session, 'https://es', 'logs-*', ['ns-a'], start, end)