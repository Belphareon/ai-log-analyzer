from scripts.analysis.workflow_lifecycle import WorkflowIdentity
from scripts.core.fetch_lifecycle import (
    LifecycleScope,
    fetch_lifecycle_context,
    probe_lifecycle,
)


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        return FakeResponse(200, {
            "hits": {
                "total": {"value": 3, "relation": "eq"},
                "hits": [
                    {"_source": {"topic": "topic-a", "kubernetes": {"namespace": "ns-a"}}},
                    {"_source": {"topic": "topic-a", "kubernetes": {"namespace": "ns-a"}}},
                ],
            }
        })


class FakeLifecycleSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.delete_calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        return self.responses.pop(0)

    def delete(self, url, json=None, timeout=None):
        self.delete_calls.append((url, json, timeout))
        return FakeResponse(200, {})


def _document(event_id, message):
    return {
        '_index': 'cluster-app-2026.09.24',
        '_id': event_id,
        'sort': [event_id],
        '_source': {
            '@timestamp': '2026-09-24T23:18:01.000Z',
            'topic': 'topic-a',
            'kubernetes': {'namespace': 'ns-a'},
            'message': message,
        },
    }


def _search_response(total, hits, pit_id='pit-next'):
    return FakeResponse(200, {
        'pit_id': pit_id,
        'hits': {'total': {'value': total, 'relation': 'eq'}, 'hits': hits},
    })


def test_probe_is_independent_of_error_trace_ids_and_reports_cap():
    session = FakeSession()

    probe = probe_lifecycle(
        "2026-09-24T23:10:00Z",
        "2026-09-24T23:35:00Z",
        max_hits=2,
        session=session,
    )

    assert probe.scopes == [LifecycleScope("topic-a", "ns-a")]
    assert probe.expected_count == 3
    assert probe.fetched_count == 2
    assert probe.truncated
    body = session.calls[0][1]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert "traceId" not in str(body)


def test_context_fetch_uses_pit_and_collects_predecessor_evidence():
    start = _document(
        'start-1',
        'Start processing of queued event EventProcessingQueue(queueEventId=10, type=TYPE).',
    )
    blocked = _document(
        'blocked-1',
        'There are prior unprocessed events, this event 10 TYPE/a will be delayed. '
        'Prior events are [20 TYPE/a].',
    )
    predecessor_completed = _document(
        'completed-1',
        'Changing status of event TYPE(20) from PROCESSING to COMPLETED.',
    )
    session = FakeLifecycleSession([
        FakeResponse(200, {'id': 'root-pit'}),
        _search_response(2, [start, blocked]),
        FakeResponse(200, {'id': 'predecessor-pit'}),
        _search_response(1, [predecessor_completed]),
    ])

    documents, stats = fetch_lifecycle_context(
        [LifecycleScope('topic-a', 'ns-a')],
        '2026-09-24T23:10:00Z',
        '2026-09-24T23:35:00Z',
        batch_size=10,
        max_records_per_query=10,
        session=session,
    )

    assert [document['_id'] for document in documents] == ['start-1', 'blocked-1', 'completed-1']
    assert stats.expected_count == 3
    assert stats.fetched_count == 3
    assert stats.processed_count == 3
    assert stats.query_count == 2
    assert stats.complete
    assert len(session.delete_calls) == 2
    predecessor_body = session.calls[3][1]
    assert '20' in str(predecessor_body['query']['bool']['should'])


def test_context_fetch_deduplicates_es_documents_but_preserves_query_completeness():
    blocked = _document(
        'blocked-1',
        'There are prior unprocessed events, this event 10 TYPE/a will be delayed. '
        'Prior events are [20 TYPE/a].',
    )
    session = FakeLifecycleSession([
        FakeResponse(200, {'id': 'root-pit'}),
        _search_response(1, [blocked]),
        FakeResponse(200, {'id': 'predecessor-pit'}),
        _search_response(1, [blocked]),
    ])

    documents, stats = fetch_lifecycle_context(
        [LifecycleScope('topic-a', 'ns-a')],
        '2026-09-24T23:10:00Z',
        '2026-09-24T23:35:00Z',
        batch_size=10,
        max_records_per_query=10,
        session=session,
    )

    assert [document['_id'] for document in documents] == ['blocked-1']
    assert stats.expected_count == 2
    assert stats.fetched_count == 2
    assert stats.processed_count == 1
    assert stats.complete


def test_predecessor_id_cap_forces_an_incomplete_context_fetch():
    blocked = _document(
        'blocked-1',
        'There are prior unprocessed events, this event 10 TYPE/a will be delayed. '
        'Prior events are [20 TYPE/a, 30 TYPE/a].',
    )
    session = FakeLifecycleSession([
        FakeResponse(200, {'id': 'root-pit'}),
        _search_response(1, [blocked]),
        FakeResponse(200, {'id': 'predecessor-pit'}),
        _search_response(1, [_document('predecessor-1', 'event TYPE(20)')]),
    ])

    _documents, stats = fetch_lifecycle_context(
        [LifecycleScope('topic-a', 'ns-a')],
        '2026-09-24T23:10:00Z',
        '2026-09-24T23:35:00Z',
        batch_size=10,
        max_records_per_query=10,
        max_predecessor_ids=1,
        session=session,
    )

    assert not stats.complete
    assert stats.truncated
    assert stats.reason == 'predecessor id cap 1 for topic-a|ns-a'