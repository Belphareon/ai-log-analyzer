import json
import os
from pathlib import Path
import sys
import uuid

import psycopg2
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.runtime_state import RuntimeStateStore


@pytest.fixture
def state_store():
    dsn = os.getenv('AILOG_TEST_POSTGRES_DSN')
    if not dsn:
        pytest.skip('AILOG_TEST_POSTGRES_DSN is required')
    query_hash = uuid.uuid4().hex * 2
    connection = psycopg2.connect(dsn)
    assert 'test' in connection.info.dbname.lower()
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA IF NOT EXISTS ailog_peak')
        cursor.execute((Path(__file__).parents[1] / 'migrations/013_runtime_state.sql').read_text())
    connection.commit()
    yield RuntimeStateStore(lambda: psycopg2.connect(dsn), query_hash)
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM ailog_peak.runtime_state WHERE query_hash = %s', (query_hash,))
    connection.commit()
    connection.close()


def seed_files():
    return {
        'known_problems.yaml': '- id: KP-000042\n  problem_key: database:payments:timeout\n  fingerprints: [abc123]\n',
        'known_peaks.yaml': '- id: PK-000007\n  problem_key: database:payments:SPIKE\n',
        'alert_state_regular_phase.json': json.dumps({'peaks': {'payments': {'cooldown_until': '2026-10-30T12:00:00+00:00'}}}),
    }


def test_state_survives_pod_replacement_without_pvc(state_store, tmp_path):
    with state_store.writer():
        assert state_store.seed(seed_files())
        state_store.restore(tmp_path / 'first-pod')
        alerts = tmp_path / 'first-pod/alert_state_regular_phase.json'
        alerts.write_text(json.dumps({'peaks': {'payments': {'cooldown_until': '2026-10-30T13:00:00+00:00'}}}))
        state_store.checkpoint(tmp_path / 'first-pod')
    with state_store.writer():
        assert not state_store.seed({**seed_files(), 'known_peaks.yaml': '[]'})
        state_store.restore(tmp_path / 'second-pod')
    assert (tmp_path / 'second-pod/known_problems.yaml').read_text() == seed_files()['known_problems.yaml']
    assert (tmp_path / 'second-pod/alert_state_regular_phase.json').read_text() == alerts.read_text()


def test_missing_state_fails_closed(state_store, tmp_path):
    with state_store.writer(), pytest.raises(RuntimeError, match='not seeded'):
        state_store.restore(tmp_path)
    assert not list(tmp_path.iterdir())


def test_overlapping_writer_is_rejected_and_lease_released(state_store):
    other = RuntimeStateStore(state_store.connection_factory, state_store.query_hash)
    with state_store.writer():
        with pytest.raises(RuntimeError, match='another runtime state writer'):
            with other.writer():
                pytest.fail('overlapping writer was allowed')
    with other.writer():
        assert other.seed(seed_files())


def test_invalid_or_incomplete_state_cannot_replace_seed(state_store, tmp_path):
    with state_store.writer():
        assert state_store.seed(seed_files())
        with pytest.raises(ValueError, match='both registries'):
            state_store.seed({'known_problems.yaml': '[]'})
        with pytest.raises(FileNotFoundError):
            state_store.checkpoint(tmp_path)
        state_store.restore(tmp_path)
        assert (tmp_path / 'known_peaks.yaml').read_text() == seed_files()['known_peaks.yaml']


def test_registry_and_delivered_cooldown_checkpoint_immediately(state_store, tmp_path):
    from datetime import datetime, timezone
    from core.problem_registry import ProblemRegistry
    import regular_phase

    with state_store.writer():
        state_store.seed(seed_files())
        state_store.restore(tmp_path / 'writer')
        registry = ProblemRegistry(str(tmp_path / 'writer'), state_store=state_store)
        assert registry.load()
        registry.problems['database:payments:timeout'].occurrences = 123
        assert registry.save()
        regular_phase._save_alert_state_unlocked(registry, {'peaks': {'payments': {'last_sent_at': datetime.now(timezone.utc).isoformat()}}})
        state_store.restore(tmp_path / 'replacement')
    replacement = ProblemRegistry(str(tmp_path / 'replacement'))
    assert replacement.load()
    assert replacement.problems['database:payments:timeout'].occurrences == 123
    assert replacement._problem_counter == 42
    assert replacement._peak_counter == 7
    assert replacement.is_fingerprint_known('abc123')
    assert 'last_sent_at' in json.loads((tmp_path / 'replacement/alert_state_regular_phase.json').read_text())['peaks']['payments']


def test_postgres_mode_refuses_unleased_direct_regular(monkeypatch, tmp_path):
    import regular_phase

    monkeypatch.setenv('RUNTIME_STATE_BACKEND', 'postgres')
    monkeypatch.setenv('REGISTRY_DIR', str(tmp_path))
    monkeypatch.setattr(regular_phase, '_runtime_state_store', None)
    with pytest.raises(RuntimeError, match='writer lease'):
        regular_phase.init_registry()
    assert not list(tmp_path.iterdir())