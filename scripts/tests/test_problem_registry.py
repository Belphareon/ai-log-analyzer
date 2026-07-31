import multiprocessing
from datetime import datetime
from types import SimpleNamespace

from scripts.core.problem_registry import ProblemRegistry


def _incident(fingerprint, category, app):
    timestamp = datetime(2026, 7, 31, 8, 0)
    return SimpleNamespace(
        fingerprint=fingerprint,
        category=SimpleNamespace(value=category),
        apps=[app],
        namespaces=['ns-a'],
        error_type='RuntimeError',
        normalized_message=f'{fingerprint} failure',
        stats=SimpleNamespace(current_count=1),
        time=SimpleNamespace(first_seen=timestamp, last_seen=timestamp),
        flags=SimpleNamespace(is_spike=False, is_burst=False),
    )


def _concurrent_writer(registry_dir, fingerprint, category, app, start, results):
    registry = ProblemRegistry(registry_dir)
    start.wait()
    results.put(registry.update_and_save([_incident(fingerprint, category, app)]))


def test_concurrent_updates_do_not_lose_registry_entries(tmp_path):
    context = multiprocessing.get_context('fork')
    start = context.Event()
    results = context.Queue()
    writers = [
        context.Process(
            target=_concurrent_writer,
            args=(str(tmp_path), 'fp-a', 'BUSINESS', 'card-servicing', start, results),
        ),
        context.Process(
            target=_concurrent_writer,
            args=(str(tmp_path), 'fp-b', 'DATABASE', 'billing', start, results),
        ),
    ]

    for writer in writers:
        writer.start()
    start.set()
    for writer in writers:
        writer.join(timeout=10)

    assert [writer.exitcode for writer in writers] == [0, 0]
    assert sorted(results.get(timeout=1) for _ in writers) == [True, True]

    registry = ProblemRegistry(str(tmp_path))
    assert registry.load() is True
    assert set(registry.fingerprint_index) == {'fp-a', 'fp-b'}
    assert len(registry.problems) == 2


def test_repeated_load_replaces_in_memory_state(tmp_path):
    registry = ProblemRegistry(str(tmp_path))
    assert registry.update_and_save([_incident('fp-a', 'BUSINESS', 'card-servicing')])

    registry.problems['stale'] = object()
    registry.fingerprint_index['stale'] = 'stale'

    assert registry.load() is True
    assert set(registry.fingerprint_index) == {'fp-a'}
    assert set(registry.problems) == {'BUSINESS:card_servicing:runtime_error'}


def test_enrichment_merge_preserves_concurrent_registry_update(tmp_path):
    stale_registry = ProblemRegistry(str(tmp_path))
    assert stale_registry.update_and_save(
        [_incident('fp-a', 'BUSINESS', 'card-servicing')]
    )

    concurrent_registry = ProblemRegistry(str(tmp_path))
    assert concurrent_registry.update_and_save(
        [_incident('fp-b', 'DATABASE', 'billing')]
    )

    assert stale_registry.merge_enrichment_and_save(
        {
            'BUSINESS:card_servicing:runtime_error': {
                'root_cause': 'service failure',
                'behavior': 'request rejected',
                'enriched_severity': 'high',
                'enriched_score': 87.5,
            }
        },
        {},
    )

    registry = ProblemRegistry(str(tmp_path))
    assert registry.load()
    assert set(registry.fingerprint_index) == {'fp-a', 'fp-b'}
    problem = registry.problems['BUSINESS:card_servicing:runtime_error']
    assert problem.root_cause == 'service failure'
    assert problem.behavior == 'request rejected'
    assert problem.enriched_severity == 'high'
    assert problem.enriched_score == 87.5