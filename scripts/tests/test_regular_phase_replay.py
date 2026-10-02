"""Regression tests for read-only historical regular-phase replays."""

import os
import sys
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, SCRIPTS)

import regular_phase as rp  # noqa: E402
import backfill as bf  # noqa: E402


class _FakeAggregator:
    def __init__(self):
        self.total_records = 1
        self.acc = {}
        self.closed = False

    def ingest_page(self, _errors):
        pass

    def close(self):
        self.closed = True


def _complete_fetch(*_args, stats_out=None, **_kwargs):
    if stats_out is not None:
        stats_out.update({'expected': 1, 'fetched': 1, 'complete': True})
    return []


def _raise_db_unavailable(*_args, **_kwargs):
    raise RuntimeError('authoritative DB unavailable')


def test_replay_window_uses_the_requested_utc_boundary():
    requested_end = datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc)

    _now, window_start, window_end = rp._resolve_regular_window(
        15,
        requested_end,
    )

    assert window_start == datetime(2026, 9, 22, 3, 30, tzinfo=timezone.utc)
    assert window_end == requested_end


def test_replay_window_rejects_unaligned_or_naive_end_time():
    with pytest.raises(ValueError, match='timezone-aware'):
        rp._resolve_regular_window(15, datetime(2026, 9, 22, 3, 45))
    with pytest.raises(ValueError, match='15-minute UTC boundary'):
        rp._resolve_regular_window(
            15,
            datetime(2026, 9, 22, 3, 46, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match='window_minutes=15'):
        rp._resolve_regular_window(
            30,
            datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
        )


def test_historical_replay_requires_dry_run_before_any_runtime_work():
    with pytest.raises(ValueError, match='historical replay requires dry_run=True'):
        rp.run_regular_phase(
            dry_run=False,
            replay_window_end=datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
        )


def test_historical_replay_requires_the_15_minute_grain_before_dry_run():
    with pytest.raises(ValueError, match='window_minutes=15'):
        rp.run_regular_phase(
            window_minutes=30,
            dry_run=False,
            replay_window_end=datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
        )


def test_replay_threshold_bundle_loads_directly_without_db_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('PERCENTILE_LEVEL', '0.93')
    bundle_path = tmp_path / 'thresholds.json'
    bundle_path.write_text(json.dumps({
        'bundle_id': 'replay-memory-v4.0-asof-20260920T110000Z',
        'metadata': {
            'percentile_level': 0.93,
            'population_grain': 'namespace/15m/day_of_week/active_windows',
            'percentile_method': 'configured_percentile_capped_by_median_plus_6_scaled_mad',
            'calculation_version': '4.0',
            'training_cutoff': '2026-09-20T11:00:00+00:00',
            'monitored_namespaces': ['ns-a'],
            'namespace_contract_hash': rp.namespace_contract_hash(['ns-a']),
        },
        'thresholds': [{
            'namespace': 'ns-a',
            'day_of_week': 6,
            'value': 30,
            'samples': 20,
        }],
        'caps': {'ns-a': {'value': 40, 'samples': 140}},
    }), encoding='utf-8')

    class Detector:
        loaded = None

        def load_thresholds_direct(self, thresholds, caps, snapshot_id=None):
            self.loaded = (thresholds, caps, snapshot_id)

    detector = Detector()
    metadata = rp._load_replay_threshold_bundle(
        detector,
        bundle_path,
        datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc),
        ['ns-a'],
    )

    assert metadata['calculation_version'] == '4.0'
    assert detector.loaded == (
        {('ns-a', 6): {'value': 30.0, 'samples': 20}},
        {'ns-a': {'value': 40.0, 'samples': 140}},
        'replay-memory-v4.0-asof-20260920T110000Z',
    )


def test_regular_phase_fails_closed_when_peak_detector_cannot_initialize(monkeypatch):
    aggregators = []

    def new_aggregator():
        aggregator = _FakeAggregator()
        aggregators.append(aggregator)
        return aggregator

    monkeypatch.setattr(rp, 'StreamingAggregator', new_aggregator)
    monkeypatch.setattr(rp, 'fetch_unlimited', _complete_fetch)
    monkeypatch.setattr(
        rp,
        'LAST_FETCH_STATS',
        {'complete': True, 'expected': 1, 'fetched': 1},
    )
    monkeypatch.setattr(
        rp,
        'init_registry',
        lambda: SimpleNamespace(fingerprint_index={}, problems={}, peaks={}),
    )
    monkeypatch.setattr(rp, 'get_db_connection', _raise_db_unavailable)

    result = rp.run_regular_phase(
        dry_run=True,
        replay_window_end=datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
    )

    assert result['status'] == 'error'
    assert 'Pxx/CAP peak detector initialization failed' in result['error']
    assert aggregators[0].closed is True


def test_backfill_fails_closed_when_peak_detector_cannot_initialize(monkeypatch):
    aggregators = []

    def new_aggregator():
        aggregator = _FakeAggregator()
        aggregators.append(aggregator)
        return aggregator

    monkeypatch.setattr(bf, 'StreamingAggregator', new_aggregator)
    monkeypatch.setattr(bf, 'fetch_unlimited', _complete_fetch)
    monkeypatch.setattr(bf, 'get_db_connection', _raise_db_unavailable)

    result = bf.process_day_worker(
        datetime(2026, 9, 22, tzinfo=timezone.utc),
        dry_run=True,
        skip_processed=False,
    )

    assert result['status'] == 'error'
    assert 'Pxx/CAP peak detector initialization failed' in result['error']
    assert aggregators[0].closed is True


def test_backfill_bootstrap_collects_facts_without_loading_threshold_snapshot(monkeypatch):
    captured = {}

    class FakePipeline:
        def __init__(self, *, peak_detector, **_kwargs):
            captured['detector'] = peak_detector
            self.phase_b = SimpleNamespace(historical_baseline={})
            self.phase_c = SimpleNamespace(
                namespace_fingerprint_baselines={},
                namespace_fingerprint_baseline_available=False,
            )

        def run_streaming(self, _aggregator, run_id):
            captured['run_id'] = run_id
            return SimpleNamespace(trace_patterns=[], incidents=[], total_incidents=0)

    monkeypatch.setattr(bf, 'StreamingAggregator', _FakeAggregator)
    monkeypatch.setattr(bf, 'fetch_unlimited', _complete_fetch)
    monkeypatch.setattr(bf, 'get_db_connection', _raise_db_unavailable)
    monkeypatch.setattr(bf, 'Pipeline', FakePipeline)
    monkeypatch.setattr(
        bf,
        'build_collection_cause_analysis',
        lambda _collection: SimpleNamespace(families=[]),
    )

    result = bf.process_day_worker(
        datetime(2026, 9, 22, tzinfo=timezone.utc),
        dry_run=True,
        skip_processed=False,
        bootstrap=True,
    )

    assert result['status'] == 'success'
    assert captured['run_id'].startswith('backfill-20260922-')
    assert captured['detector'].is_peak(100.0, 'ns-a', 1) == {'is_peak': False}


def test_regular_phase_runs_lifecycle_diagnostics_before_zero_error_return(monkeypatch):
    class EmptyAggregator:
        total_records = 0

        def ingest_page(self, _errors):
            pass

        def close(self):
            pass

    lifecycle_calls = []
    monkeypatch.setattr(rp, 'StreamingAggregator', EmptyAggregator)
    monkeypatch.setattr(rp, 'fetch_unlimited', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        rp,
        'LAST_FETCH_STATS',
        {'complete': True, 'expected': 0, 'fetched': 0},
    )
    monkeypatch.setattr(
        rp,
        'init_registry',
        lambda: SimpleNamespace(fingerprint_index={}, problems={}, peaks={}),
    )
    monkeypatch.setattr(rp, '_load_monitored_namespaces', lambda: [])
    monkeypatch.setattr(
        rp,
        'run_workflow_lifecycle_diagnostics',
        lambda *args, **kwargs: lifecycle_calls.append((args, kwargs)) or {
            'status': 'complete', 'alerted': []
        },
    )

    result = rp.run_regular_phase(
        dry_run=True,
        replay_window_end=datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
    )

    assert result['status'] == 'no_data'
    assert result['workflow_lifecycle']['status'] == 'complete'
    assert len(lifecycle_calls) == 1


def test_clustered_payload_keeps_all_same_window_episode_contexts():
    window_start = datetime(2026, 9, 22, 3, 30, tzinfo=timezone.utc)
    transitions = [
        {
            'episode_id': 'episode-a',
            'window_decision_id': 'decision-a',
            'window_start_utc': window_start.isoformat(),
            'cause_signature': 'cause-a',
        },
        {
            'episode_id': 'episode-b',
            'window_decision_id': 'decision-b',
            'window_start_utc': window_start.isoformat(),
            'cause_signature': 'cause-b',
        },
    ]

    contexts = rp._episode_policy_contexts(
        {'window_start': window_start.isoformat()},
        transitions,
    )

    assert [context['episode_id'] for context in contexts] == [
        'episode-a',
        'episode-b',
    ]


def test_explicit_cause_signature_mismatch_does_not_fallback_to_same_window():
    window_start = datetime(2026, 9, 22, 3, 30, tzinfo=timezone.utc)
    transitions = [{
        'episode_id': 'episode-a',
        'window_decision_id': 'decision-a',
        'window_start_utc': window_start.isoformat(),
        'cause_signature': 'cause-a',
    }]

    contexts = rp._episode_policy_contexts(
        {
            'window_start': window_start.isoformat(),
            'cause_families': [{'signature': 'cause-b'}],
        },
        transitions,
    )

    assert contexts == []