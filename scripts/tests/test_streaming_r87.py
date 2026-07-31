#!/usr/bin/env python3
"""
r87 Streaming validation tests
==============================

Ověřuje, že streaming cesta (StreamingAggregator + Pipeline.run_streaming) dává
IDENTICKÉ výsledky jako batch Pipeline.run() a že paměť je ohraničená.

Spuštění:
    python3 scripts/tests/test_streaming_r87.py

Testy (dle zadání uživatele r87):
  1. Golden regression   - stejné logy batch vs streaming => identické výsledky
  2. Page-size invariance - stejné výsledky pro ES page 1/100/1000/5000
  3. Stress              - miliony syntetických logů => ohraničený růst RSS
    4. Fetch consumer      - stránky bez materializace, failure zavře session
    5. OOM guard           - batch cesta hlídá growth i absolutní RSS ceiling
    6. SQLite detail       - trace flow odpovídá batch analýze
    7. Trace limits        - per-trace i globální cap detailních timelines
    8. SQLite cleanup      - osiřelé spill soubory po tvrdém ukončení se uklidí
"""

import os
import sys
import random
import tempfile
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(SCRIPTS, 'pipeline'))
sys.path.insert(0, os.path.join(SCRIPTS, 'core'))
sys.path.insert(0, SCRIPTS)

from pipeline import Pipeline  # noqa: E402
from phase_a_parse import PhaseA_Parser  # noqa: E402
from streaming_aggregator import StreamingAggregator  # noqa: E402
import fetch_unlimited as fetch_module  # noqa: E402


# ---------------------------------------------------------------- synthetic data
def _ts(base: datetime, seconds: float) -> str:
    return (base + timedelta(seconds=seconds)).astimezone(timezone.utc).isoformat()


def make_errors(n_fingerprints=25, seed=42, base=None):
    """Vygeneruj syntetické error dicty ve stejném schématu jako fetch_unlimited."""
    if base is None:
        base = datetime(2026, 1, 20, 8, 0, 0, tzinfo=timezone.utc)
    rnd = random.Random(seed)
    namespaces = ['ns-alpha', 'ns-beta', 'ns-gamma', 'ns-delta']
    apps = ['svc-a', 'svc-b', 'svc-c', 'svc-d', 'svc-e']
    errors = []
    for fp_i in range(n_fingerprints):
        msg_tmpl = f"Error kind {fp_i}: operation failed code={{code}} id={{id}}"
        etype = f"Domain{fp_i % 5}Exception"
        # rozprostři eventy přes ~40 minut (víc 15min oken pro backfill-like)
        count = rnd.randint(2, 60)
        # část fingerprintů udělá burst (nakupení v krátkém okně)
        burst = (fp_i % 4 == 0)
        for e in range(count):
            if burst and e < count * 0.8:
                sec = rnd.uniform(600, 630)  # nakupení do ~30s okna
            else:
                sec = rnd.uniform(0, 2400)
            ns = namespaces[(fp_i + e) % len(namespaces)]
            app = apps[(fp_i * 2 + e) % len(apps)]
            tid = f"trace-{fp_i}-{e % 7}"
            errors.append({
                'message': msg_tmpl.format(code=rnd.randint(400, 599), id=rnd.randint(1, 9999)),
                'application': app,
                'cluster': 'prod-cluster',
                'namespace': ns,
                'timestamp': _ts(base, sec),
                'trace_id': tid,
                'originator_application': f"orig-{fp_i % 3}",
                'pcbs_master': f"eam-{fp_i % 6}",
                '_error_type_hint': etype,
            })
    rnd.shuffle(errors)
    # ES vrací globálně vzestupně dle času → seřaď (streaming to předpokládá)
    errors.sort(key=lambda x: x['timestamp'])
    return errors


# ------------------------------------------------------------------ fingerprint
def collection_signature(collection):
    """Deterministický otisk kolekce podle fingerprintu (ne podle incident ID/času)."""
    sig = {}
    for inc in collection.incidents:
        sig[inc.fingerprint] = {
            'current_count': inc.stats.current_count,
            'current_rate': round(float(inc.stats.current_rate), 6),
            'baseline_ewma': round(float(inc.stats.baseline_rate), 6),
            'baseline_mad': round(float(inc.stats.baseline_mad), 6),
            'trend_ratio': round(float(inc.stats.trend_ratio), 6),
            'trend_direction': inc.stats.trend_direction,
            'namespaces_count': inc.stats.namespaces,
            'is_new': inc.flags.is_new,
            'is_spike': inc.flags.is_spike,
            'is_burst': inc.flags.is_burst,
            'is_cross_namespace': inc.flags.is_cross_namespace,
            'score': round(float(inc.score), 6),
            'severity': str(inc.severity.value if hasattr(inc.severity, 'value') else inc.severity),
            'category': str(inc.category.value if hasattr(inc.category, 'value') else inc.category),
            'error_type': inc.error_type,
            'normalized_message': inc.normalized_message,
            'apps': sorted(inc.apps),
            'namespaces': sorted(inc.namespaces),
            'versions': sorted(inc.versions),
            'trace_ids': sorted(inc.trace_ids),
            'app_event_counts': dict(sorted(inc.app_event_counts.items())),
            'namespace_event_counts': dict(sorted(inc.namespace_event_counts.items())),
            'trace_event_counts': dict(sorted(inc.trace_event_counts.items())),
            'evidence_rules': sorted(ev.rule for ev in inc.evidence),
        }
    return sig


def _new_pipeline(peak_detector=None, build_trace_patterns=False):
    return Pipeline(peak_detector=peak_detector, build_trace_patterns=build_trace_patterns)


def run_batch(errors, peak_detector=None, build_trace_patterns=False):
    return _new_pipeline(peak_detector, build_trace_patterns).run(errors, run_id="batch")


def run_streaming(errors, page_size=1000, peak_detector=None, build_trace_patterns=False,
                  sqlite_path=None):
    agg = StreamingAggregator(sqlite_path=sqlite_path)
    for i in range(0, len(errors), page_size):
        agg.ingest_page(errors[i:i + page_size])
    agg.finalize()
    pipe = _new_pipeline(peak_detector, build_trace_patterns)
    col = pipe.run_streaming(agg, run_id="streaming")
    return col, agg


# ---------------------------------------------------------------- fake peak det
class FakePeakDetector:
    """Deterministický peak detector: peak, když value >= threshold pro daný ns."""
    def __init__(self, threshold=3.0):
        self.threshold = threshold

    def is_peak(self, value, namespace, day_of_week):
        p93 = self.threshold
        return {
            'is_peak': value >= p93,
            'p93_threshold': p93,
            'cap_threshold': p93 * 5,
            'value': value,
        }


# ============================================================================ 1
def test_golden_regression():
    errors = make_errors(n_fingerprints=30, seed=7)
    batch = run_batch(errors)
    stream, agg = run_streaming(errors, page_size=1000)
    agg.close()
    b, s = collection_signature(batch), collection_signature(stream)
    assert set(b) == set(s), (
        f"Fingerprint set liší: only_batch={set(b)-set(s)}, only_stream={set(s)-set(b)}"
    )
    diffs = {fp: (b[fp], s[fp]) for fp in b if b[fp] != s[fp]}
    assert not diffs, f"Rozdíly ({len(diffs)}): {list(diffs.items())[:2]}"
    print(f"✅ 1. Golden regression: {len(b)} fingerprintů identických (batch == streaming)")


# ============================================================================ 1b
def test_golden_regression_with_peak_and_traces():
    errors = make_errors(n_fingerprints=30, seed=11)
    pd = FakePeakDetector(threshold=2.0)
    batch = run_batch(errors, peak_detector=pd, build_trace_patterns=True)
    stream, agg = run_streaming(errors, page_size=500, peak_detector=FakePeakDetector(2.0),
                                build_trace_patterns=True)
    b, s = collection_signature(batch), collection_signature(stream)
    assert set(b) == set(s)
    diffs = {fp: (b[fp], s[fp]) for fp in b if b[fp] != s[fp]}
    assert not diffs, f"Rozdíly s peak/trace ({len(diffs)}): {list(diffs.items())[:2]}"
    # spike se musí objevit (P93 aktivní)
    assert any(v['is_spike'] for v in s.values()), "Očekáván aspoň jeden spike s peak_detectorem"
    agg.close()
    print(f"✅ 1b. Golden regression s P93/CAP + trace patterns: identické, "
          f"spikes={sum(v['is_spike'] for v in s.values())}")


def test_namespace_total_peak_is_not_split_by_fingerprint():
    base = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    errors = []
    for fingerprint_index in range(10):
        for event_index in range(10):
            errors.append({
                'message': f'Error family {fingerprint_index} failed',
                'application': 'svc-a',
                'namespace': 'ns-a',
                'timestamp': _ts(base, event_index),
                'trace_id': f'trace-{fingerprint_index}-{event_index}',
            })

    batch = run_batch(errors, peak_detector=FakePeakDetector(threshold=50))
    streaming, aggregator = run_streaming(
        errors,
        page_size=7,
        peak_detector=FakePeakDetector(threshold=50),
    )
    aggregator.close()
    for collection in (batch, streaming):
        spikes = [incident for incident in collection.incidents if incident.flags.is_spike]
        assert len(spikes) == 1
        evidence = next(item for item in spikes[0].evidence if item.rule == 'spike_p93_cap')
        assert evidence.current == 100
    assert collection_signature(batch) == collection_signature(streaming)
    print("✅ 1c. Namespace total peak: 10 fingerprintů × 10 eventů => total=100")


def test_error_kind_fact_grain_matches_batch_and_streaming():
    errors = make_errors(n_fingerprints=12, seed=31)
    batch = run_batch(errors)
    streaming, aggregator = run_streaming(errors, page_size=7)
    aggregator.close()

    def signature(collection):
        return sorted(
            (
                fact['window_start'].isoformat(),
                fact['namespace'],
                fact['application'],
                fact['fingerprint'],
                fact['error_count'],
            )
            for fact in collection.error_kind_facts
        )

    batch_facts = signature(batch)
    streaming_facts = signature(streaming)
    assert batch_facts == streaming_facts
    assert sum(fact[-1] for fact in streaming_facts) == len(errors)
    print(f"✅ 1d. Error-kind facts: {len(streaming_facts)} exact rows batch == streaming")


def test_regression_uses_latest_observed_application_version():
    base = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    errors = [
        {
            'message': 'Previously fixed checkout failure',
            'application': 'checkout',
            'application.version': version,
            'namespace': 'payments',
            'timestamp': _ts(base, index),
            'trace_id': f'trace-{index}',
        }
        for index, version in enumerate(('2.8.0', '2.10.0'))
    ]
    fingerprint = PhaseA_Parser().parse(errors[0]).fingerprint

    batch_pipeline = _new_pipeline()
    batch_pipeline.phase_c.known_fixes[fingerprint] = '2.9.0'
    batch = batch_pipeline.run(errors, run_id='batch-version')

    aggregator = StreamingAggregator()
    aggregator.ingest_page(errors)
    aggregator.finalize()
    streaming_pipeline = _new_pipeline()
    streaming_pipeline.phase_c.known_fixes[fingerprint] = '2.9.0'
    streaming = streaming_pipeline.run_streaming(aggregator, run_id='stream-version')
    aggregator.close()

    for collection in (batch, streaming):
        incident = next(item for item in collection.incidents if item.fingerprint == fingerprint)
        assert incident.flags.is_regression
        evidence = next(item for item in incident.evidence if item.rule == 'regression')
        assert '2.10.0' in evidence.message
    print("✅ 1e. Regression: batch/streaming používají nejvyšší explicitní verzi 2.10.0")


# ============================================================================ 2
def test_page_size_invariance():
    errors = make_errors(n_fingerprints=30, seed=13)
    ref = None
    for ps in (1, 100, 1000, 5000, len(errors) + 10):
        col, agg = run_streaming(errors, page_size=ps, peak_detector=FakePeakDetector(2.0))
        sig = collection_signature(col)
        agg.close()
        if ref is None:
            ref = sig
        else:
            assert sig == ref, f"Page-size {ps} dává jiný výsledek než reference"
    print("✅ 2. Page-size invariance: page 1/100/1000/5000/all → identické výsledky")


# ============================================================================ 3
def test_stress_bounded_memory():
    import resource
    import gc

    def rss_mb():
        try:
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        return int(line.split()[1]) / 1024.0
        except OSError:
            pass
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    base = datetime(2026, 1, 20, 8, 0, 0, tzinfo=timezone.utc)
    n_fp = 200                      # ohraničená kardinalita (paměť roste s tímto)
    total = 2_000_000              # miliony logů
    apps = ['a', 'b', 'c', 'd']
    namespaces = ['ns1', 'ns2', 'ns3']

    agg = StreamingAggregator()
    gc.collect()
    rss_start = rss_mb()
    rss_after_warmup = None
    page = []
    PAGE = 20000
    for i in range(total):
        fp_i = i % n_fp
        page.append({
            'message': f"Stress error {fp_i}: code={fp_i % 50}",
            'application': apps[i % len(apps)],
            'cluster': 'c',
            'namespace': namespaces[i % len(namespaces)],
            'timestamp': (base + timedelta(seconds=i * 0.01)).isoformat(),
            'trace_id': f"t-{fp_i}-{i % 50}",
            'originator_application': 'o',
            'pcbs_master': 'e',
        })
        if len(page) >= PAGE:
            agg.ingest_page(page)
            page.clear()
            if i >= 400000 and rss_after_warmup is None:
                gc.collect()
                rss_after_warmup = rss_mb()
    if page:
        agg.ingest_page(page)
    agg.finalize()
    gc.collect()
    rss_end = rss_mb()
    agg.close()

    assert agg.total_records == total, f"Očekáváno {total}, zpracováno {agg.total_records}"
    assert agg.fingerprint_count == n_fp
    # Růst po warmupu (kdy jsou fingerprinty i trace už ustálené) musí být malý.
    if rss_after_warmup:
        growth_after_warmup = rss_end - rss_after_warmup
        assert growth_after_warmup < 150, (
            f"RSS růst po warmupu {growth_after_warmup:.0f}MB není ohraničený "
            f"(start={rss_start:.0f}, warmup={rss_after_warmup:.0f}, end={rss_end:.0f})"
        )
    print(f"✅ 3. Stress: {total:,} logů / {n_fp} fp zpracováno, "
          f"RSS start={rss_start:.0f}MB end={rss_end:.0f}MB (ohraničené)")


# ============================================================================ 5
def test_sqlite_detail_matches_batch():
    from analysis.trace_timeline import build_trace_timelines, group_traces_by_signature
    from phase_a_parse import PhaseA_Parser

    errors = make_errors(n_fingerprints=20, seed=23)
    # batch trace timelines z parsovaných recordů
    parser = PhaseA_Parser()
    records = parser.parse_batch(errors)
    batch_timelines = build_trace_timelines(records)
    batch_patterns = group_traces_by_signature(batch_timelines)

    agg = StreamingAggregator()
    agg.ingest_page(errors)
    agg.finalize()
    stream_records = list(agg.iter_top_trace_records())
    stream_timelines = build_trace_timelines(stream_records)
    stream_patterns = group_traces_by_signature(stream_timelines)
    agg.close()

    # stejná sada trace_id a stejné per-trace error county
    b_counts = {tid: tl.error_count for tid, tl in batch_timelines.items()}
    s_counts = {tid: tl.error_count for tid, tl in stream_timelines.items()}
    assert b_counts == s_counts, (
        f"Trace event counts se liší: "
        f"only_b={set(b_counts)-set(s_counts)}, only_s={set(s_counts)-set(b_counts)}"
    )
    assert len(batch_patterns) == len(stream_patterns), (
        f"Počet trace patternů se liší: batch={len(batch_patterns)} stream={len(stream_patterns)}"
    )
    print(f"✅ 5. SQLite detail: {len(s_counts)} trace, {len(stream_patterns)} patternů "
          f"odpovídá batch analýze")


def test_fetch_page_consumer_without_materialization():
    class FakeResponse:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    class FakeSession:
        close_count = 0

        def __init__(self):
            self.search_calls = 0
            self.auth = None
            self.verify = True
            self.trust_env = False

        def post(self, url, **_kwargs):
            if url.endswith('/_pit?keep_alive=5m'):
                return FakeResponse({'id': 'pit-1'})
            self.search_calls += 1
            if self.search_calls == 1:
                hits = [
                    {'_source': {'message': 'one', '@timestamp': '2026-01-20T08:00:00+00:00'}, 'sort': [1]},
                    {'_source': {'message': 'two', '@timestamp': '2026-01-20T08:00:01+00:00'}, 'sort': [2]},
                ]
            else:
                hits = [
                    {'_source': {'message': 'three', '@timestamp': '2026-01-20T08:00:02+00:00'}, 'sort': [3]},
                ]
            return FakeResponse({'hits': {'total': {'value': 3}, 'hits': hits}})

        def delete(self, *_args, **_kwargs):
            return FakeResponse({})

        def close(self):
            type(self).close_count += 1

    pages = []
    with patch.object(fetch_module.requests, 'Session', FakeSession):
        result = fetch_module.fetch_unlimited(
            '2026-01-20T08:00:00Z',
            '2026-01-20T08:15:00Z',
            batch_size=2,
            page_consumer=lambda page: pages.append(page),
            collect_results=False,
        )

    assert result == []
    assert [len(page) for page in pages] == [2, 1]
    assert fetch_module.LAST_FETCH_STATS['fetched'] == 3
    assert not fetch_module.LAST_FETCH_STATS['truncated']

    def fail_consumer(_page):
        raise RuntimeError('consumer failed')

    try:
        with patch.object(fetch_module.requests, 'Session', FakeSession):
            fetch_module.fetch_unlimited(
                '2026-01-20T08:00:00Z',
                '2026-01-20T08:15:00Z',
                batch_size=2,
                page_consumer=fail_consumer,
                collect_results=False,
            )
    except RuntimeError as error:
        assert str(error) == 'consumer failed'
    else:
        raise AssertionError('Consumer failure must propagate')

    assert FakeSession.close_count == 2
    print("✅ 6. Fetch consumer: stránky bez materializace, failure zavře session")


def test_fetch_contract_preserves_metadata_and_scope():
    nested = {
        'message': 'Request failed',
        'application': {'name': 'orders-v1', 'version': '2.4.1'},
        'exception': {'type': 'java.net.SocketTimeoutException'},
        'error': {'type': 'upstream_timeout'},
        'stack_trace': 'java.net.SocketTimeoutException: timeout',
        'kubernetes': {
            'namespace': 'orders-prod',
            'labels': {'eamApplication': 'orders'},
        },
        '@timestamp': '2026-07-31T08:00:00Z',
        'traceId': 'trace-1',
        'span': {'id': 'span-1'},
        'parent': {'id': 'parent-1'},
    }
    dotted = {
        'message': 'Request failed',
        'application.name': 'orders-v1',
        'application.version': '2.4.1',
        'exception.type': 'java.net.SocketTimeoutException',
        'error.type': 'upstream_timeout',
        'stack_trace': 'java.net.SocketTimeoutException: timeout',
        'kubernetes.namespace': 'orders-prod',
        'kubernetes.labels.eamApplication': 'orders',
        '@timestamp': '2026-07-31T08:00:00Z',
        'traceId': 'trace-1',
        'span.id': 'span-1',
        'parent.id': 'parent-1',
    }

    nested_error = fetch_module._source_to_error(nested)
    dotted_error = fetch_module._source_to_error(dotted)
    for field in (
        'application', 'application.version', 'exception.type', 'error.type',
        'namespace', 'trace_id', 'spanId', 'parentId', 'pcbs_master',
    ):
        assert nested_error[field] == dotted_error[field], field

    record = PhaseA_Parser().parse(nested_error)
    assert record.app_name == 'orders-v1'
    assert record.app_version == '2.4.1'
    assert record.error_type == 'SocketTimeoutException'
    assert record.span_id == 'span-1'
    assert record.parent_span_id == 'parent-1'

    query = fetch_module._build_error_query(
        '2026-07-31T08:00:00Z',
        '2026-07-31T08:15:00Z',
        100,
        ['orders-prod'],
    )
    time_range = query['query']['bool']['must'][0]['range']['@timestamp']
    assert time_range == {
        'gte': '2026-07-31T08:00:00Z',
        'lt': '2026-07-31T08:15:00Z',
    }
    assert query['query']['bool']['filter'] == [
        {'terms': {'kubernetes.namespace': ['orders-prod']}},
    ]
    print("✅ 6c. Fetch contract: metadata, half-open range a namespace scope zachovány")


def test_fetch_requires_pit():
    class FakeResponse:
        status_code = 503

        def json(self):
            return {}

    class FakeSession:
        close_count = 0
        search_count = 0

        def __init__(self):
            self.auth = None
            self.verify = True
            self.trust_env = False

        def post(self, url, **_kwargs):
            if not url.endswith('/_pit?keep_alive=5m'):
                type(self).search_count += 1
            return FakeResponse()

        def close(self):
            type(self).close_count += 1

    with patch.object(fetch_module.requests, 'Session', FakeSession):
        result = fetch_module.fetch_unlimited(
            '2026-07-31T08:00:00Z',
            '2026-07-31T08:15:00Z',
            collect_results=False,
        )

    assert result is None
    assert FakeSession.search_count == 0
    assert FakeSession.close_count == 1
    assert fetch_module.LAST_FETCH_STATS['failed']
    assert not fetch_module.LAST_FETCH_STATS['complete']
    print("✅ 6d. Fetch contract: PIT failure ukončí nekompletní run")


def test_fetch_memory_guard_uses_absolute_ceiling():
    reason = fetch_module._should_stop_fetch(
        record_count=100,
        rss_mb=910,
        budget_mb=500,
        baseline_mb=800,
        memory_ceiling_mb=900,
    )
    assert reason == 'memory ceiling 900MB (RSS 910MB)'

    reason = fetch_module._should_stop_fetch(
        record_count=100,
        rss_mb=850,
        budget_mb=40,
        baseline_mb=800,
        memory_ceiling_mb=900,
    )
    assert reason == 'memory budget 40MB (fetch growth 50MB, RSS 850MB)'
    print("✅ 6b. Fetch OOM guard: absolutní ceiling i growth budget aktivní")


def test_sqlite_trace_event_limit():
    base = datetime(2026, 1, 20, 8, 0, 0, tzinfo=timezone.utc)
    errors = [
        {
            'message': f'event-{trace_index}-{event_index}',
            'application': 'svc-a',
            'cluster': 'prod-cluster',
            'namespace': 'ns-a',
            'timestamp': _ts(base, trace_index * 100 + event_index),
            'trace_id': f'large-trace-{trace_index}',
        }
        for trace_index in range(3)
        for event_index in range(25)
    ]
    agg = StreamingAggregator()
    agg.ingest_page(errors)
    agg.finalize()
    records = list(agg.iter_top_trace_records(
        max_traces=3,
        max_events_per_trace=7,
        max_total_events=12,
    ))
    agg.close()

    assert len(records) == 12
    assert max(
        sum(record.trace_id == trace_id for record in records)
        for trace_id in {record.trace_id for record in records}
    ) <= 7
    print("✅ 7. SQLite trace limit: per-trace i globální detail cap aktivní")


def test_stale_sqlite_cleanup():
    with tempfile.TemporaryDirectory() as directory:
        stale_path = os.path.join(directory, 'streaming_events_stale.sqlite')
        active_path = os.path.join(directory, 'streaming_events_active.sqlite')
        unrelated_path = os.path.join(directory, 'keep.sqlite')
        for path in (stale_path, active_path, unrelated_path):
            with open(path, 'w'):
                pass
        stale_time = time.time() - 90000
        os.utime(stale_path, (stale_time, stale_time))

        with patch.dict(os.environ, {'REGISTRY_DIR': directory}):
            agg = StreamingAggregator()
            agg.close()

        assert not os.path.exists(stale_path)
        assert os.path.exists(active_path)
        assert os.path.exists(unrelated_path)
    print("✅ 8. SQLite cleanup: pouze stale streaming soubory odstraněny")


def main():
    tests = [
        test_golden_regression,
        test_golden_regression_with_peak_and_traces,
        test_namespace_total_peak_is_not_split_by_fingerprint,
        test_error_kind_fact_grain_matches_batch_and_streaming,
        test_regression_uses_latest_observed_application_version,
        test_page_size_invariance,
        test_sqlite_detail_matches_batch,
        test_fetch_page_consumer_without_materialization,
        test_fetch_memory_guard_uses_absolute_ceiling,
        test_fetch_contract_preserves_metadata_and_scope,
        test_fetch_requires_pit,
        test_sqlite_trace_event_limit,
        test_stale_sqlite_cleanup,
        test_stress_bounded_memory,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"💥 {t.__name__}: {e}")
            traceback.print_exc()
    print()
    if failed:
        print(f"❌ {failed}/{len(tests)} testů selhalo")
        return 1
    print(f"✅ Všech {len(tests)} testů prošlo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
