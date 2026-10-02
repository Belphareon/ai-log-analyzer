from datetime import datetime, timezone

import pytest

from scripts.core.baseline_loader import BaselineLoader


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)

    def cursor(self):
        return self.cursor_instance


def test_fingerprint_baseline_is_dense_and_as_of_bounded():
    analysis_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    rows = [
        ('fp-a', datetime(2026, 7, 31, 7, 15, tzinfo=timezone.utc), 0),
        ('fp-a', datetime(2026, 7, 31, 7, 30, tzinfo=timezone.utc), 3),
        ('fp-a', datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc), 0),
        ('fp-b', datetime(2026, 7, 31, 7, 15, tzinfo=timezone.utc), 0),
        ('fp-b', datetime(2026, 7, 31, 7, 30, tzinfo=timezone.utc), 0),
        ('fp-b', datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc), 1),
    ]
    connection = FakeConnection(rows)

    rates = BaselineLoader(connection).load_fingerprint_rates(
        ['fp-b', 'fp-a'],
        analysis_window_start=analysis_start,
        lookback_days=7,
        min_samples=3,
    )

    assert rates == {'fp-a': [0.0, 3.0, 0.0], 'fp-b': [0.0, 0.0, 1.0]}
    assert connection.cursor_instance.query.count('window_start < %s') == 2
    assert connection.cursor_instance.params[1] == analysis_start
    assert connection.cursor_instance.params[-1] == analysis_start


def test_fingerprint_baseline_requires_as_of_time():
    with pytest.raises(ValueError, match='analysis_window_start is required'):
        BaselineLoader(FakeConnection([])).load_fingerprint_rates(
            ['fp-a'], analysis_window_start=None
        )


def test_namespace_fingerprint_baseline_is_dense_and_as_of_bounded():
    analysis_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    rows = [
        ('ns-a', 'fp-a', datetime(2026, 7, 31, 7, 15, tzinfo=timezone.utc), 0),
        ('ns-a', 'fp-a', datetime(2026, 7, 31, 7, 30, tzinfo=timezone.utc), 3),
        ('ns-a', 'fp-a', datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc), 0),
        ('ns-b', 'fp-a', datetime(2026, 7, 31, 7, 15, tzinfo=timezone.utc), 1),
        ('ns-b', 'fp-a', datetime(2026, 7, 31, 7, 30, tzinfo=timezone.utc), 0),
        ('ns-b', 'fp-a', datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc), 2),
    ]
    connection = FakeConnection(rows)

    rates = BaselineLoader(connection).load_namespace_fingerprint_rates(
        [('ns-b', 'fp-a'), ('ns-a', 'fp-a')],
        analysis_window_start=analysis_start,
        lookback_days=7,
        min_samples=3,
    )

    assert rates == {
        ('ns-a', 'fp-a'): [0.0, 3.0, 0.0],
        ('ns-b', 'fp-a'): [1.0, 0.0, 2.0],
    }
    assert 'requested_pairs' in connection.cursor_instance.query
    assert connection.cursor_instance.params[1] == analysis_start
    assert connection.cursor_instance.params[-1] == analysis_start