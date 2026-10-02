from datetime import datetime, timezone

from scripts.analysis.workflow_lifecycle import (
    LifecycleFetchStats,
    WorkflowIdentity,
    WorkflowIncident,
)
from scripts.core.workflow_persistence import persist_workflow_run


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 1

    def execute(self, statement, params=None):
        self.statements.append((' '.join(statement.split()), params))

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _incident(alert_eligible=True):
    timestamp = datetime(2026, 9, 24, 23, 18, tzinfo=timezone.utc)
    return WorkflowIncident(
        identity=WorkflowIdentity('topic-a', 'ns-a', '6467528'),
        source_cluster='es-a',
        source_indices=['cluster-app-a'],
        fetch_window_start=timestamp,
        fetch_window_end=timestamp.replace(minute=35),
        fetch_stats=LifecycleFetchStats('es-a', 'cluster-app-a', 'topic-a|ns-a'),
        first_seen=timestamp,
        last_seen=timestamp,
        confidence='high',
        alert_eligible=alert_eligible,
    )


def _stats(complete):
    return LifecycleFetchStats(
        source_cluster='es-a',
        source_index='cluster-app-a',
        scope='topic-a|ns-a',
        expected_count=3,
        fetched_count=3 if complete else 2,
        processed_count=3 if complete else 2,
        query_count=1,
        complete=complete,
        reason=None if complete else 'record cap 2',
    )


def test_partial_workflow_run_is_persisted_but_never_alert_eligible():
    connection = FakeConnection()
    result = persist_workflow_run(
        connection_factory=lambda: connection,
        run_id='workflow-partial',
        window_start=datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        fetch_stats=_stats(False),
        incidents=[_incident()],
        execute_values_fn=lambda *args, **kwargs: None,
    )

    assert result['status'] == 'partial'
    assert result['alert_eligible'] == []
    statements = [statement for statement, _ in connection.cursor_instance.statements]
    assert any('workflow_lifecycle_runs' in statement for statement in statements)
    assert any("SET status = %s" in statement for statement in statements)


def test_complete_workflow_run_exposes_alerts_only_after_commit():
    connection = FakeConnection()
    result = persist_workflow_run(
        connection_factory=lambda: connection,
        run_id='workflow-complete',
        window_start=datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        window_end=datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        fetch_stats=_stats(True),
        incidents=[_incident()],
        execute_values_fn=lambda *args, **kwargs: None,
    )

    assert result['status'] == 'complete'
    assert result['alert_eligible'] == ['topic-a|ns-a|6467528']
    assert connection.commits == 2