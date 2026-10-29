from copy import deepcopy
from importlib import import_module
from types import SimpleNamespace

import pytest

from scripts.analysis.trace_timeline import (
    TracePattern, TraceTimeline, enrich_patterns_with_trace_context,
)

fetch_module = import_module('scripts.core.fetch_unlimited')


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.closed = False

    def post(self, _url, json, timeout):
        self.calls.append(deepcopy(json))
        payload = next(self.responses)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def search_result(trace_id, total=1, **extra):
    return {
        'hits': {'total': {'value': total, 'relation': 'eq'}, 'hits': [{
            '_source': {'traceId': trace_id, 'message': 'evidence', 'level': 'WARN'},
        }]},
        **extra,
    }


def fetch(monkeypatch, responses):
    session = FakeSession(responses)
    monkeypatch.setattr(fetch_module, 'ES_PASSWORD', 'fake-test-password')
    monkeypatch.setattr(fetch_module, '_load_monitored_namespaces', lambda: ['prod'])
    monkeypatch.setattr(fetch_module.requests, 'Session', lambda: session)
    result = fetch_module.fetch_trace_context(['busy', 'quiet'], 'from', 'to', max_events=1)
    assert session.closed
    return result, session


def test_busy_trace_cannot_starve_other_traces(monkeypatch):
    result, session = fetch(monkeypatch, [search_result('busy', total=100), search_result('quiet')])
    assert result.coverage['busy']['status'] == 'truncated'
    assert result.coverage['quiet']['status'] == 'complete_within_range'
    assert len(result['quiet']) == 1
    assert len(session.calls) == 2
    assert session.calls[1]['query']['bool']['must'][1]['bool']['should'][0] == {'term': {'traceId': 'quiet'}}


@pytest.mark.parametrize('partial', [{'timed_out': True}, {'_shards': {'failed': 1}}])
def test_partial_search_is_never_marked_complete(monkeypatch, partial):
    result, _session = fetch(monkeypatch, [search_result('busy', **partial), search_result('quiet')])
    assert result.coverage['busy']['status'] == 'truncated'


@pytest.mark.parametrize('payload', [
    {'count': 0, 'timed_out': True}, {'count': 0, '_shards': {'failed': 1}},
    {'count': -1}, {'count': True}, {'count': '0'}, {},
])
def test_count_recheck_rejects_incomplete_or_invalid_results(monkeypatch, payload):
    session = FakeSession([payload])
    monkeypatch.setattr(fetch_module, '_load_monitored_namespaces', lambda: ['prod'])
    monkeypatch.setattr(fetch_module.requests, 'Session', lambda: session)
    with pytest.raises(RuntimeError):
        fetch_module.count_errors('from', 'to')
    assert session.closed


def test_count_recheck_preserves_observed_zero_and_scoped_query(monkeypatch):
    session = FakeSession([{'count': 0, '_shards': {'failed': 0}}])
    monkeypatch.setattr(fetch_module, '_load_monitored_namespaces', lambda: ['prod'])
    monkeypatch.setattr(fetch_module.requests, 'Session', lambda: session)
    assert fetch_module.count_errors('from', 'to') == 0
    assert session.calls == [{'query': fetch_module._build_error_query('from', 'to', 0, ['prod'])['query']}]
    assert session.closed


def test_slow_trace_exhausts_shared_budget_without_unbounded_retry(monkeypatch):
    clock = iter([0, 0, 61])
    monkeypatch.setattr(fetch_module.time, 'monotonic', lambda: next(clock))
    result, session = fetch(monkeypatch, [search_result('busy')])
    assert len(session.calls) == 1
    assert result.coverage['busy']['status'] == 'complete_within_range'
    assert result.coverage['quiet']['status'] == 'failed'
    assert result.coverage['quiet']['reason'] == 'context_budget_exhausted'


def test_incomplete_context_preserves_original_error_evidence():
    original = TraceTimeline(trace_id='busy')
    pattern = TracePattern(signature=(), representative=original)
    result = fetch_module.TraceContextResult(['busy'], 'from', 'to')
    result['busy'] = [{'message': 'partial context', 'level': 'WARN'}]
    result.coverage['busy']['status'] = 'truncated'
    enrich_patterns_with_trace_context([pattern], lambda *_args: result, 'from', 'to')
    assert pattern.representative is original
    assert pattern.to_dict()['context_coverage']['status'] == 'truncated'


def test_empty_failed_context_is_exposed_instead_of_losing_metadata():
    pattern = TracePattern(signature=(), representative=TraceTimeline(trace_id='busy'))
    result = fetch_module.TraceContextResult(['busy'], 'from', 'to')
    enrich_patterns_with_trace_context([pattern], lambda *_args: result, 'from', 'to')
    assert pattern.representative.context_coverage['status'] == 'failed'