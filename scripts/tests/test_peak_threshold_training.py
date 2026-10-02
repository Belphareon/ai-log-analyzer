from datetime import datetime, timezone

import pytest

from scripts.core import calculate_peak_thresholds as thresholds_module
from scripts.core.peak_detection import PeakDetector


class FetchCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FetchConnection:
    def __init__(self, rows):
        self.cursor_instance = FetchCursor(rows)

    def cursor(self):
        return self.cursor_instance


class SnapshotCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 1

    def execute(self, statement, params=None):
        self.statements.append((' '.join(statement.split()), params))

    def close(self):
        pass


class SnapshotConnection:
    def __init__(self):
        self.cursor_instance = SnapshotCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_threshold_training_reads_dense_complete_facts_with_as_of_bound():
    as_of = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    rows = [
        ('ns-a', 4, 0, datetime(2026, 7, 31, 7, 30, tzinfo=timezone.utc)),
        ('ns-a', 4, 12, datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc)),
    ]
    connection = FetchConnection(rows)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv('MONITORED_NAMESPACES', 'ns-a')
    data, date_range = thresholds_module.fetch_raw_data(
        connection,
        weeks=4,
        as_of=as_of,
    )
    monkeypatch.undo()

    assert data == {('ns-a', 4): [0.0, 12.0]}
    assert date_range == {'min': rows[0][3], 'max': rows[1][3]}
    assert 'FROM ailog_peak.v_complete_namespace_error_counts' in connection.cursor_instance.query
    assert 'window_start < %s' in connection.cursor_instance.query
    assert 'namespace = ANY(%s)' in connection.cursor_instance.query
    assert connection.cursor_instance.params[0] == as_of
    assert connection.cursor_instance.params[1] == ['ns-a']


def test_threshold_training_excludes_zero_windows_from_percentile_population():
    thresholds = thresholds_module.calculate_p93_thresholds({
        ('ns-a', 0): [0.0] * 20 + [4.0, 8.0, 12.0],
        ('ns-zero', 0): [0.0] * 24,
    })

    assert thresholds[('ns-a', 0)]['p93'] == 12.0
    assert thresholds[('ns-a', 0)]['count'] == 3
    assert ('ns-zero', 0) not in thresholds

    caps = thresholds_module.calculate_cap_values(thresholds)
    assert caps['ns-a']['cap'] == 12.0
    assert 'ns-zero' not in caps


def test_threshold_training_caps_a_contaminated_p98_tail():
    routine_values = [float(value) for value in range(20, 220)]
    contaminated_values = routine_values + [4760.0] * 5

    assert thresholds_module.percentile(contaminated_values, 0.98) == 4760.0

    thresholds = thresholds_module.calculate_p93_thresholds(
        {('pcb-ch-sit-01-app', 0): contaminated_values},
        percentile_level=0.98,
    )

    effective_threshold = thresholds[('pcb-ch-sit-01-app', 0)]['p93']
    assert 200 < effective_threshold < 1000
    assert 4760 > effective_threshold


def test_percentile_level_remains_the_primary_sensitivity_control():
    routine_values = [float(value) for value in range(1, 101)]

    p90 = thresholds_module.calculate_p93_thresholds(
        {('ns-a', 0): routine_values},
        percentile_level=0.90,
    )[('ns-a', 0)]
    p98 = thresholds_module.calculate_p93_thresholds(
        {('ns-a', 0): routine_values},
        percentile_level=0.98,
    )[('ns-a', 0)]

    assert p90['p93'] == p90['raw_percentile']
    assert p98['p93'] == p98['raw_percentile']
    assert p98['p93'] > p90['p93']


def test_threshold_snapshot_failure_rolls_back_cache_and_marks_snapshot_failed(monkeypatch):
    connection = SnapshotConnection()
    as_of = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    date_range = {
        'min': datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        'max': datetime(2026, 7, 31, 7, 45, tzinfo=timezone.utc),
    }
    threshold_values = {
        ('ns-a', 4): {
            'p93': 12,
            'count': 20,
            'median': 2,
            'mean': 3,
            'max': 12,
        }
    }
    caps = {
        'ns-a': {
            'cap': 12,
            'median_p93': 12,
            'avg_p93': 12,
            'min_p93': 12,
            'max_p93': 12,
            'total_samples': 20,
        }
    }
    batch_calls = 0

    monkeypatch.setenv('MONITORED_NAMESPACES', 'ns-a,ns-zero')

    def fail_after_snapshot_values(cursor, statement, rows):
        nonlocal batch_calls
        batch_calls += 1
        if batch_calls == 2:
            raise RuntimeError('injected cache insert failure')

    monkeypatch.setattr(thresholds_module, 'execute_batch', fail_after_snapshot_values)

    with pytest.raises(RuntimeError, match='injected cache insert failure'):
        thresholds_module.save_thresholds_to_db(
            connection,
            threshold_values,
            caps,
            date_range,
            as_of=as_of,
        )

    assert connection.commits == 2
    assert connection.rollbacks == 1
    statements = [statement for statement, _ in connection.cursor_instance.statements]
    assert any("SET status = 'failed'" in statement for statement in statements)
    assert not any("SET status = 'complete'" in statement for statement in statements)
    snapshot_insert = next(
        params
        for statement, params in connection.cursor_instance.statements
        if 'INSERT INTO ailog_peak.threshold_snapshot_runs' in statement
    )
    assert snapshot_insert[-1] == ['ns-a', 'ns-zero']


def test_peak_detector_returns_latest_complete_snapshot_id(monkeypatch):
    monkeypatch.setenv('PERCENTILE_LEVEL', '0.98')
    connection = FetchConnection([
        (
            'snapshot-1', 'ns-a', 4, 50, 80, 20, 0.98,
            thresholds_module.POPULATION_GRAIN, thresholds_module.PERCENTILE_METHOD,
            thresholds_module.CALCULATION_VERSION,
        ),
    ])
    detector = PeakDetector(conn=connection)

    result = detector.is_peak(value=100, namespace='ns-a', day_of_week=4)

    assert result['is_peak']
    assert result['p93_threshold'] == 50
    assert result['cap_threshold'] == 80
    assert result['percentile_level'] == 0.98
    assert result['percentile_threshold'] == 50
    assert result['threshold_snapshot_id'] == 'snapshot-1'
    assert 'FROM ailog_peak.v_latest_threshold_values' in connection.cursor_instance.query


def test_peak_detector_rejects_incompatible_snapshot(monkeypatch):
    monkeypatch.setenv('PERCENTILE_LEVEL', '0.98')
    connection = FetchConnection([
        (
            'snapshot-old', 'ns-a', 4, 50, 80, 20, 0.98,
            thresholds_module.POPULATION_GRAIN, 'legacy_percentile', '3.0',
        ),
    ])
    detector = PeakDetector(conn=connection)

    with pytest.raises(RuntimeError, match='incompatible threshold snapshot'):
        detector.is_peak(value=100, namespace='ns-a', day_of_week=4)