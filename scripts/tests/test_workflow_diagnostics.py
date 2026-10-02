from datetime import datetime, timezone

from scripts.analysis.workflow_lifecycle import (
    LifecycleFetchStats,
    WorkflowIdentity,
    WorkflowIncident,
)
from scripts.core import workflow_diagnostics


def test_disabled_diagnostics_do_not_probe(monkeypatch):
    monkeypatch.delenv('LIFECYCLE_ANALYSIS_ENABLED', raising=False)
    monkeypatch.setattr(workflow_diagnostics, 'probe_lifecycle', lambda *args: (_ for _ in ()).throw(AssertionError()))

    result = workflow_diagnostics.run_workflow_lifecycle_diagnostics(
        datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        connection_factory=lambda: None,
    )

    assert result['status'] == 'disabled'


def test_incomplete_fetch_is_persisted_without_alert(monkeypatch):
    class Probe:
        scopes = [object()]
        expected_count = 1
        fetched_count = 1
        truncated = False
        reason = None

    class Stats:
        source_cluster = 'es'
        processed_count = 0
        complete = False

        def to_dict(self):
            return {'complete': False}

    monkeypatch.setenv('LIFECYCLE_ANALYSIS_ENABLED', 'true')
    monkeypatch.setenv('LIFECYCLE_ALERT_ENABLED', 'true')
    monkeypatch.setattr(workflow_diagnostics, 'probe_lifecycle', lambda *args: Probe())
    monkeypatch.setattr(workflow_diagnostics, 'fetch_lifecycle_context', lambda *args: ([], Stats()))
    monkeypatch.setattr(workflow_diagnostics, 'persist_workflow_run', lambda *args: {
        'status': 'partial', 'alert_eligible': []
    })

    result = workflow_diagnostics.run_workflow_lifecycle_diagnostics(
        datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        connection_factory=lambda: None,
    )

    assert result['status'] == 'partial'
    assert result['alerted'] == []


def test_capped_probe_forces_partial_run_even_when_scope_fetch_completes(monkeypatch):
    class Probe:
        scopes = [object()]
        expected_count = 2
        fetched_count = 1
        truncated = True
        reason = 'probe capped at 1'

    class Stats:
        source_cluster = 'es'
        processed_count = 0
        complete = True
        truncated = False
        reason = None

        def to_dict(self):
            return {
                'complete': self.complete,
                'truncated': self.truncated,
                'reason': self.reason,
            }

    persisted = {}
    monkeypatch.setenv('LIFECYCLE_ANALYSIS_ENABLED', 'true')
    monkeypatch.setattr(workflow_diagnostics, 'probe_lifecycle', lambda *args: Probe())
    monkeypatch.setattr(workflow_diagnostics, 'fetch_lifecycle_context', lambda *args: ([], Stats()))
    monkeypatch.setattr(
        workflow_diagnostics,
        'persist_workflow_run',
        lambda *args: persisted.update(complete=args[4].complete) or {
            'status': 'partial', 'alert_eligible': []
        },
    )

    result = workflow_diagnostics.run_workflow_lifecycle_diagnostics(
        datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        connection_factory=lambda: None,
    )

    assert result['status'] == 'partial'
    assert persisted['complete'] is False


def test_configured_retry_threshold_is_passed_to_detector(monkeypatch):
    class Probe:
        scopes = [object()]
        expected_count = 0
        fetched_count = 0
        truncated = False
        reason = None

    class Stats:
        source_cluster = 'es'
        processed_count = 0
        complete = True
        truncated = False
        reason = None

        def to_dict(self):
            return {'complete': self.complete}

    captured = {}
    monkeypatch.setenv('LIFECYCLE_ANALYSIS_ENABLED', 'true')
    monkeypatch.setenv('LIFECYCLE_MIN_RETRIES', '4')
    monkeypatch.setattr(workflow_diagnostics, 'probe_lifecycle', lambda *args: Probe())
    monkeypatch.setattr(workflow_diagnostics, 'fetch_lifecycle_context', lambda *args: ([], Stats()))
    monkeypatch.setattr(
        workflow_diagnostics,
        'analyze_workflow_events',
        lambda *args, **kwargs: captured.update(kwargs) or [],
    )
    monkeypatch.setattr(workflow_diagnostics, 'persist_workflow_run', lambda *args: {
        'status': 'complete', 'alert_eligible': []
    })

    result = workflow_diagnostics.run_workflow_lifecycle_diagnostics(
        datetime(2026, 9, 24, 23, 15, tzinfo=timezone.utc),
        datetime(2026, 9, 24, 23, 30, tzinfo=timezone.utc),
        connection_factory=lambda: None,
    )

    assert result['status'] == 'complete'
    assert captured['min_retries'] == 4


def test_complete_persistence_precedes_lifecycle_alert_dispatch(monkeypatch):
    timestamp = datetime(2026, 9, 24, 23, 18, tzinfo=timezone.utc)
    stats = LifecycleFetchStats(
        source_cluster='es',
        source_index='cluster-app-*',
        scope='topic-a|ns-a',
        expected_count=1,
        fetched_count=1,
        complete=True,
    )
    incident = WorkflowIncident(
        identity=WorkflowIdentity('topic-a', 'ns-a', '10'),
        source_cluster='es',
        source_indices=['cluster-app-a'],
        fetch_window_start=timestamp,
        fetch_window_end=timestamp.replace(minute=30),
        fetch_stats=stats,
        first_seen=timestamp,
        last_seen=timestamp,
        attempt_count=3,
        processing_to_registered_count=3,
        without_delaying_count=3,
        stale_delay_count=3,
        confidence='high',
        alert_eligible=True,
        loop_detected=True,
    )

    class Probe:
        scopes = [object()]
        expected_count = 1
        fetched_count = 1
        truncated = False
        reason = None

    actions = []

    class Notifier:
        def is_enabled(self):
            return True

        def send_workflow_lifecycle_alert(self, message):
            assert 'persisted' in actions
            assert 'Queue event: 10' in message
            actions.append('alerted')
            return True

    monkeypatch.setenv('LIFECYCLE_ANALYSIS_ENABLED', 'true')
    monkeypatch.setenv('LIFECYCLE_ALERT_ENABLED', 'true')
    monkeypatch.setattr(workflow_diagnostics, 'probe_lifecycle', lambda *args: Probe())
    monkeypatch.setattr(workflow_diagnostics, 'fetch_lifecycle_context', lambda *args: ([], stats))
    monkeypatch.setattr(workflow_diagnostics, 'analyze_workflow_events', lambda *args, **kwargs: [incident])
    monkeypatch.setattr(
        workflow_diagnostics,
        'persist_workflow_run',
        lambda *args: actions.append('persisted') or {
            'status': 'complete', 'alert_eligible': [incident.identity.key]
        },
    )
    monkeypatch.setattr(workflow_diagnostics, '_get_email_notifier', lambda: Notifier())

    result = workflow_diagnostics.run_workflow_lifecycle_diagnostics(
        timestamp.replace(minute=15),
        timestamp.replace(minute=30),
        connection_factory=lambda: None,
    )

    assert actions == ['persisted', 'alerted']
    assert result['alerted'] == ['topic-a|ns-a|10']