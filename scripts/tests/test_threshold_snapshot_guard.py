from scripts.core.calculate_peak_thresholds import (
    CALCULATION_VERSION,
    PERCENTILE_METHOD,
    POPULATION_GRAIN,
)
from scripts.core.threshold_snapshot_guard import (
    SnapshotMetadata,
    decide_refresh,
    load_latest_complete_snapshot,
)
from scripts.core import threshold_snapshot_guard as guard


class Cursor:
    def __init__(self, row):
        self.row = row
        self.query = ""
        self.closed = False

    def execute(self, query):
        self.query = query

    def fetchone(self):
        return self.row

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, row):
        self.cursor_instance = Cursor(row)

    def cursor(self):
        return self.cursor_instance


def _snapshot(**overrides):
    values = {
        'snapshot_id': 'snapshot-1',
        'percentile_level': 0.93,
        'population_grain': POPULATION_GRAIN,
        'percentile_method': PERCENTILE_METHOD,
        'calculation_version': CALCULATION_VERSION,
        'namespaces': ('ns-a', 'ns-b'),
    }
    values.update(overrides)
    return SnapshotMetadata(**values)


def test_compatible_snapshot_is_reused():
    decision = decide_refresh(
        _snapshot(),
        percentile_level=0.93,
        monitored_namespaces=['ns-b', 'ns-a'],
    )

    assert decision.refresh is False
    assert decision.reason == 'compatible_snapshot'
    assert decision.snapshot_id == 'snapshot-1'


def test_missing_snapshot_bootstraps_and_force_always_refreshes():
    bootstrap = decide_refresh(
        None,
        percentile_level=0.93,
        monitored_namespaces=['ns-a'],
    )
    forced = decide_refresh(
        _snapshot(),
        percentile_level=0.93,
        monitored_namespaces=['ns-a', 'ns-b'],
        force=True,
    )

    assert bootstrap.refresh is True
    assert bootstrap.reason == 'bootstrap'
    assert forced.refresh is True
    assert forced.reason == 'manual_refresh'


def test_model_or_namespace_change_requires_refresh():
    decision = decide_refresh(
        _snapshot(population_grain='namespace/15m/day_of_week'),
        percentile_level=0.92,
        monitored_namespaces=['ns-a', 'ns-c'],
    )

    assert decision.refresh is True
    assert decision.reason.startswith('model_change:')
    assert 'percentile_level' in decision.reason
    assert 'population_grain' in decision.reason
    assert 'namespaces' in decision.reason


def test_latest_snapshot_loader_reads_complete_view_and_namespace_coverage():
    connection = Connection((
        'snapshot-1',
        0.93,
        POPULATION_GRAIN,
        PERCENTILE_METHOD,
        CALCULATION_VERSION,
        ['ns-b', 'ns-a'],
    ))

    snapshot = load_latest_complete_snapshot(connection)

    assert snapshot == _snapshot()
    assert 'v_latest_threshold_snapshot' in connection.cursor_instance.query
    assert 'snapshot.monitored_namespaces' in connection.cursor_instance.query
    assert 'threshold_snapshot_values' not in connection.cursor_instance.query
    assert connection.cursor_instance.closed is True


def test_preflight_uses_direct_read_only_application_credentials(monkeypatch):
    captured = {}

    class PreflightConnection:
        def set_session(self, **kwargs):
            captured['session'] = kwargs

        def close(self):
            captured['closed'] = True

    monkeypatch.setenv('MONITORED_NAMESPACES', 'ns-a,ns-b')
    monkeypatch.setenv('PERCENTILE_LEVEL', '0.93')
    monkeypatch.setenv('DB_HOST', 'db.example.test')
    monkeypatch.setenv('DB_PORT', '5433')
    monkeypatch.setenv('DB_NAME', 'ailog')
    monkeypatch.setenv('DB_USER', 'application-reader')
    monkeypatch.setenv('DB_PASSWORD', 'reader-secret')
    monkeypatch.setenv('DB_DDL_USER', 'ddl-writer')
    monkeypatch.setenv('DB_DDL_PASSWORD', 'ddl-secret')
    monkeypatch.setattr(
        guard.psycopg2,
        'connect',
        lambda **kwargs: captured.setdefault('config', kwargs) and PreflightConnection(),
    )
    monkeypatch.setattr(guard, 'load_latest_complete_snapshot', lambda _conn: _snapshot())

    assert guard.main() == 0
    assert captured['config'] == {
        'host': 'db.example.test',
        'port': 5433,
        'database': 'ailog',
        'user': 'application-reader',
        'password': 'reader-secret',
        'connect_timeout': 30,
        'options': '-c statement_timeout=60000',
    }
    assert captured['session'] == {'readonly': True, 'autocommit': True}
    assert captured['closed'] is True