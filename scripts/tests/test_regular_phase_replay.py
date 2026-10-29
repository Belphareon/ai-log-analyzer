"""Regression tests for read-only historical regular-phase replays."""

import os
import sys
import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, SCRIPTS)

import regular_phase as rp  # noqa: E402
import backfill as bf  # noqa: E402
from core.regular_schedule import plan_collection_windows  # noqa: E402


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


def test_collection_plan_prioritizes_live_window_and_keeps_oldest_gaps():
    start = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
    complete = {start, start + timedelta(minutes=30)}
    now = datetime(2026, 10, 29, 12, 17, tzinfo=timezone.utc)

    plan = plan_collection_windows(now, start, complete, max_windows=3)

    assert plan == [
        (datetime(2026, 10, 29, 12, tzinfo=timezone.utc), True),
        (start + timedelta(minutes=15), False),
        (start + timedelta(minutes=45), False),
    ]
    assert start + timedelta(minutes=60) not in {window for window, _notify in plan}


def test_collection_plan_retries_only_missing_windows_after_completed_zero_runs():
    start = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
    now = start + timedelta(minutes=47)
    assert plan_collection_windows(now, start, {start, start + timedelta(minutes=30)}) == [
        (start + timedelta(minutes=15), False),
    ]


def test_collection_plan_waits_for_indexing_and_rejects_bad_boundaries():
    start = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
    assert plan_collection_windows(start + timedelta(minutes=16), start, set()) == []
    assert plan_collection_windows(start + timedelta(minutes=17), start, set()) == [(start, True)]
    with pytest.raises(ValueError, match='timezone-aware'):
        plan_collection_windows(start.replace(tzinfo=None), start, set())
    with pytest.raises(ValueError, match='15-minute'):
        plan_collection_windows(start, start + timedelta(minutes=1), set())


def test_facts_only_zero_window_persists_without_episode_or_registry_mutation(monkeypatch):
    monkeypatch.setattr(rp, 'StreamingAggregator', lambda: SimpleNamespace(
        total_records=0, ingest_page=lambda *_args: None, close=lambda: None,
    ))
    monkeypatch.setattr(rp, 'fetch_unlimited', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rp, 'LAST_FETCH_STATS', {'complete': True, 'expected': 0, 'fetched': 0})
    monkeypatch.setattr(rp, 'init_registry', lambda: SimpleNamespace(fingerprint_index={}, problems={}, peaks={}))
    monkeypatch.setattr(rp, '_load_monitored_namespaces', lambda: ['ns-a'])
    monkeypatch.setattr(rp, 'stream_advisory_lock', lambda *_args: nullcontext(object()))
    persisted = []
    monkeypatch.setattr(rp, 'persist_analysis_run', lambda **kwargs: persisted.append(kwargs) or {})
    monkeypatch.setattr(rp, 'load_peak_episodes_before', lambda *_args, **_kwargs: pytest.fail('must not change live episodes'))

    result = rp.run_regular_phase(
        scheduled_window_end=datetime(2026, 10, 29, 10, 15, tzinfo=timezone.utc), facts_only=True,
    )

    assert result['status'] == 'no_data'
    assert result['facts_only'] is True
    assert persisted[0]['collection'].namespace_peak_decisions == []
    assert persisted[0]['collection'].peak_episodes == []


@pytest.mark.parametrize('live_succeeds', [True, False])
def test_scheduled_collection_does_not_repeat_unchanged_data_and_repairs_changed_counts(monkeypatch, live_succeeds):
    connection = SimpleNamespace(close=lambda: None)
    latest = rp._resolve_regular_window(15, rp._floor_to_window(
        datetime.now(timezone.utc) - timedelta(minutes=2), 15,
    ))[1]
    gap = latest - timedelta(minutes=30)
    old = latest - timedelta(minutes=15)
    counts = {old: 5, latest: 0}
    calls = []
    marked = []
    monkeypatch.setattr(rp, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(rp, '_load_monitored_namespaces', lambda: ['ns-a'])
    monkeypatch.setattr(rp, 'load_collection_state', lambda *_args: (gap, counts.copy()))
    monkeypatch.setattr(rp, 'load_live_completion', lambda *_args: None)
    monkeypatch.setattr(rp, 'mark_live_completion', lambda *_args: marked.append(_args[-1]))
    monkeypatch.setattr(rp, 'sync_report_knowledge', lambda *_args: None)
    monkeypatch.setattr(rp, 'init_registry', lambda: object())
    monkeypatch.setattr(sys.modules['core.fetch_unlimited'], 'count_errors', lambda start, _end: 7 if start == old.strftime('%Y-%m-%dT%H:%M:%SZ') else 0)
    monkeypatch.setattr(rp, 'run_regular_phase', lambda **kwargs: calls.append(kwargs) or {
        'status': 'success' if live_succeeds or kwargs['facts_only'] else 'error', 'error_count': 0,
    })
    monkeypatch.setenv('REGULAR_COLLECTION_START', '')
    monkeypatch.setenv('REGULAR_LATE_RECHECK_HOURS', '2')

    result = rp.run_scheduled_collection()

    assert result['status'] == ('success' if live_succeeds else 'error')
    assert result['pending_window_count'] == 0
    assert calls == [
        {'output_dir': None, 'scheduled_window_end': latest + timedelta(minutes=15), 'facts_only': False},
        {'output_dir': None, 'scheduled_window_end': old + timedelta(minutes=15), 'facts_only': True},
        {'output_dir': None, 'scheduled_window_end': gap + timedelta(minutes=15), 'facts_only': True},
    ]
    assert marked == ([latest] if live_succeeds else [])


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
        'bundle_id': 'replay-memory-v5.0-asof-20260920T110000Z',
        'metadata': {
            'percentile_level': 0.93,
            'population_grain': 'namespace/utc_weekday/hour/quarter/observed',
            'percentile_method': 'configured_percentile_capped_by_median_plus_6_scaled_mad',
            'calculation_version': '5.0',
            'training_cutoff': '2026-09-20T11:00:00+00:00',
        },
        'thresholds': [{
            'namespace': 'ns-a',
            'day_of_week': 6,
            'hour_of_day': 11,
            'quarter_hour': 0,
            'value': 30,
            'samples': 20,
            'profile_status': 'mature',
        }],
        'caps': {},
    }), encoding='utf-8')

    class Detector:
        loaded = None

        def load_thresholds_direct(self, thresholds, snapshot_id=None):
            self.loaded = (thresholds, snapshot_id)

    detector = Detector()
    metadata = rp._load_replay_threshold_bundle(
        detector,
        bundle_path,
        datetime(2026, 9, 20, 11, 0, tzinfo=timezone.utc),
    )

    assert metadata['calculation_version'] == '5.0'
    assert detector.loaded == (
        {('ns-a', 6, 11, 0): {'value': 30.0, 'samples': 20, 'profile_status': 'mature'}},
        'replay-memory-v5.0-asof-20260920T110000Z',
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


def test_backfill_closes_aggregator_when_page_consumer_raises(monkeypatch):
    aggregators = []

    class FailingAggregator(_FakeAggregator):
        def __init__(self):
            super().__init__()
            self.total_records = 17

        def ingest_page(self, _errors):
            raise OSError(28, 'No space left on device')

    def new_aggregator():
        aggregator = FailingAggregator()
        aggregators.append(aggregator)
        return aggregator

    def fail_during_fetch(*_args, page_consumer=None, **_kwargs):
        page_consumer([{}])

    monkeypatch.setattr(bf, 'StreamingAggregator', new_aggregator)
    monkeypatch.setattr(bf, 'fetch_unlimited', fail_during_fetch)

    result = bf.process_day_worker(
        datetime(2026, 9, 22, tzinfo=timezone.utc),
        dry_run=True,
        skip_processed=False,
    )

    assert result['status'] == 'error'
    assert result['error_count'] == 17
    assert 'No space left on device' in result['error']
    assert aggregators[0].closed is True


def test_backfill_main_fails_closed_on_incomplete_result(monkeypatch):
    monkeypatch.setattr(bf, 'run_backfill', lambda **_kwargs: {'status': 'error'})
    monkeypatch.setattr(sys, 'argv', ['backfill.py', '--days', '1'])

    assert bf.main() == 1


@pytest.mark.parametrize('facts_only', [False, True])
def test_registry_failure_after_backfill_commit_preserves_summary(monkeypatch, facts_only):
    def fake_day(date, *_args, **_kwargs):
        return {
            'date': date.strftime('%Y-%m-%d'), 'status': 'success',
            'collection': SimpleNamespace(incidents=[], namespace_peak_decisions=[]),
            'event_timestamps': {}, 'window_start': date, 'window_end': date,
            'expected_count': 0, 'fetched_count': 0,
        }

    monkeypatch.setattr(bf, 'init_registry', lambda *_args: None)
    monkeypatch.setattr(bf, 'process_day_worker', fake_day)
    monkeypatch.setattr(bf, 'stream_advisory_lock', lambda *_args: nullcontext(object()))
    monkeypatch.setattr(bf, 'load_peak_episodes_before', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(bf, 'persist_analysis_run', lambda **_kwargs: {
        'incident_rows': 0, 'persisted_events': 0, 'fact_rows': 0, 'namespace_rows': 0,
    })
    registry_calls = []
    monkeypatch.setattr(bf, 'update_registry_from_incidents', lambda *_args: registry_calls.append(True) or False)
    result = bf.run_backfill(days=1, workers=1, skip_analysis=True, facts_only=facts_only)
    assert result['status'] == ('success' if facts_only else 'error')
    if facts_only:
        assert registry_calls == []
        assert result['delivery_status'] == 'skipped'
    else:
        assert result['delivery_error'] == 'Registry update failed after database commit'
    assert result['success_count'] == 1
    assert result['total_saved'] == 0


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
    assert captured['detector'].is_peak(100.0, 'ns-a', 1, 0, 0) == {'is_peak': False}


@pytest.mark.parametrize('failure', [None, 'send', 'audit'])
def test_undiagnosed_window_reaches_delivery_and_records_cooldown_before_audit(monkeypatch, failure):
    events = []
    registry = SimpleNamespace(
        fingerprint_index={}, problems={}, peaks={},
        get_all_known_fingerprints=lambda: set(), update_and_save=lambda *_args: True,
        get_stats=lambda: {'new_problems_added': 0, 'new_peaks_added': 0},
    )

    class FakePipeline:
        def __init__(self, **_kwargs):
            self.phase_b = SimpleNamespace()
            self.phase_c = SimpleNamespace(namespace_peak_audit=[])

        def run_streaming(self, _aggregator, run_id):
            window_start = rp._resolve_regular_window(15)[1]
            decisions = [item.to_dict() for item in rp.materialize_decision_windows([{
                'namespace': 'ns-a', 'window_start': window_start.isoformat(),
                'namespace_total': 1, 'is_namespace_peak': True,
                'p93_threshold': 0, 'cap_threshold': 0,
                'triggered_by': 'both', 'peak_identifier': 'undiagnosed-test',
            }], ['ns-a'], window_starts=[window_start], run_id=run_id)]
            return SimpleNamespace(
                incidents=[], total_incidents=0, by_severity={},
                namespace_peak_decisions=decisions,
            )

    def send_digest(_start, _end, payloads, _summary):
        events.append('send')
        assert len(payloads) == 1
        assert payloads[0]['diagnosis_status'] == 'undiagnosed'
        if failure == 'send':
            raise RuntimeError('sender unavailable')
        return True, [{'destination': 'test-smtp', 'status': 'delivered'}]

    def audit(*_args, **_kwargs):
        events.append('audit')
        if failure == 'audit':
            raise RuntimeError('audit unavailable')

    monkeypatch.setattr(rp, 'StreamingAggregator', _FakeAggregator)
    monkeypatch.setattr(rp, 'fetch_unlimited', _complete_fetch)
    monkeypatch.setattr(rp, 'LAST_FETCH_STATS', {'complete': True, 'expected': 1, 'fetched': 1})
    monkeypatch.setattr(rp, 'init_registry', lambda: registry)
    monkeypatch.setattr(rp, '_load_monitored_namespaces', lambda: ['ns-a'])
    monkeypatch.setattr(rp, 'get_db_connection', lambda **_kwargs: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr('core.peak_detection.PeakDetector', lambda **_kwargs: object())
    monkeypatch.setattr(rp, 'Pipeline', FakePipeline)
    monkeypatch.setattr(rp, 'build_collection_cause_analysis', lambda _collection: SimpleNamespace(families=[], source_raw_error_lines=1))
    monkeypatch.setattr(rp, 'stream_advisory_lock', lambda *_args: nullcontext(object()))
    monkeypatch.setattr(rp, 'load_peak_episodes_before', lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rp, 'persist_analysis_run', lambda **_kwargs: dict(incident_rows=0, persisted_events=1, fact_rows=1, namespace_rows=1, cause_family_rows=0))
    monkeypatch.setattr(rp, 'persist_notification_decisions', lambda *_args: 1)
    monkeypatch.setattr(rp, '_load_alert_state', lambda _registry: {'peaks': {}})
    monkeypatch.setattr(rp, '_record_delivered_peak_alerts', lambda *_args: events.append('cooldown'))
    monkeypatch.setattr(rp, 'persist_notification_deliveries', audit)
    monkeypatch.setattr(rp, '_send_peak_alert_digest', send_digest)
    monkeypatch.setattr(rp, 'HAS_EXPORTS', False)
    monkeypatch.setenv('ALERT_DIGEST_ENABLED', 'true')
    result = rp.run_regular_phase()
    assert result['status'] == ('error' if failure else 'success')
    assert events == (['send'] if failure == 'send' else ['send', 'cooldown', 'audit'])
    if failure:
        assert 'unavailable' in result['error']


def test_regular_phase_returns_cleanly_for_complete_zero_error_window(monkeypatch):
    class EmptyAggregator:
        total_records = 0

        def ingest_page(self, _errors):
            pass

        def close(self):
            pass

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
    result = rp.run_regular_phase(
        dry_run=True,
        replay_window_end=datetime(2026, 9, 22, 3, 45, tzinfo=timezone.utc),
    )

    assert result['status'] == 'no_data'
    assert result['error_count'] == 0