import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.core.run_persistence import (
    PersistenceInvariantError,
    build_cause_family_rows,
    build_detection_rows,
    build_error_kind_rows,
    build_namespace_rows,
    build_peak_episode_transition_rows,
    persist_analysis_run,
    validate_reconciliation,
)
from scripts.analysis.operational_cause import (  # noqa: E402
    CauseFamilyAnalysis,
    OperationalCauseFamily,
)
from scripts.pipeline.incident import Incident


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 1
        self._result = None

    def execute(self, statement, params=None):
        normalized = ' '.join(statement.split())
        self.statements.append((normalized, params))
        if normalized.startswith('SELECT run_id'):
            self._result = None
        elif normalized.startswith('SELECT COUNT(*)'):
            raise AssertionError('row-count verification must not run after bulk failure')
        else:
            self._result = None

    def fetchone(self):
        return self._result

    def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def _fact(window_start, fingerprint, application, count):
    return {
        'window_start': window_start,
        'namespace': 'ns-a',
        'application': application,
        'fingerprint': fingerprint,
        'error_type': 'RuntimeError',
        'category': 'unknown',
        'subcategory': 'unclassified',
        'error_count': count,
        'first_event_at': window_start,
        'last_event_at': window_start,
        'sample_message': 'failure',
        'metadata_quality': 'structured',
    }


def test_fact_builders_keep_identity_dense_zeros_and_exact_totals():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 31, 8, 30, tzinfo=timezone.utc)
    collection = SimpleNamespace(error_kind_facts=[
        _fact(window_start, 'fp-a', 'app-a', 3),
        _fact(window_start, 'fp-b', 'app-b', 2),
    ])

    fact_rows = build_error_kind_rows(collection, 'run-1')
    namespace_rows = build_namespace_rows(
        fact_rows,
        'run-1',
        window_start,
        window_end,
        ['ns-a', 'ns-b'],
    )

    assert len(fact_rows) == 2
    assert [row[3] for row in namespace_rows] == [5, 0, 0, 0]
    assert validate_reconciliation(5, 5, 5, fact_rows, namespace_rows) == 5

    with pytest.raises(PersistenceInvariantError, match='do not reconcile'):
        validate_reconciliation(6, 5, 5, fact_rows, namespace_rows)


def test_bulk_failure_rolls_back_data_and_marks_run_failed():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    window_end = datetime(2026, 7, 31, 8, 15, tzinfo=timezone.utc)
    incident = SimpleNamespace(
        fingerprint='fp-a',
        stats=SimpleNamespace(baseline_rate=0),
        flags=SimpleNamespace(
            is_new=True,
            is_spike=False,
            is_burst=False,
            is_cross_namespace=False,
            is_regression=False,
            is_cascade=False,
        ),
        error_type='RuntimeError',
        normalized_message='failure',
        score=10,
        severity=SimpleNamespace(value='info'),
        versions=[],
        evidence=[],
    )
    collection = SimpleNamespace(
        run_id='run-failure',
        pipeline_version='test',
        input_records=1,
        error_kind_facts=[_fact(window_start, 'fp-a', 'app-a', 1)],
        incidents=[incident],
    )
    connection = FakeConnection()
    bulk_calls = 0

    def fail_on_namespace_rows(cursor, statement, rows, page_size):
        nonlocal bulk_calls
        bulk_calls += 1
        if bulk_calls == 2:
            raise RuntimeError('injected namespace insert failure')

    with pytest.raises(RuntimeError, match='injected namespace insert failure'):
        persist_analysis_run(
            connection_factory=lambda: connection,
            collection=collection,
            run_type='regular',
            window_start=window_start,
            window_end=window_end,
            monitored_namespaces=['ns-a'],
            expected_count=1,
            fetched_count=1,
            source_index='logs-*',
            execute_values_fn=fail_on_namespace_rows,
        )

    assert connection.commits == 2
    assert connection.rollbacks == 1
    assert connection.closed
    statements = [statement for statement, _ in connection.cursor_instance.statements]
    assert any("SET status = 'failed'" in statement for statement in statements)
    assert not any("SET status = 'complete'" in statement for statement in statements)


def test_incident_evidence_details_survive_json_round_trip():
    incident = Incident(id='inc-1', fingerprint='fp-a')
    incident.add_evidence(
        'spike_p93_cap',
        current=100,
        threshold=50,
        details={
            'threshold_snapshot_id': 'snapshot-1',
            'detector_version': 'namespace_p93_cap_v2',
        },
    )

    restored = Incident.from_dict(incident.to_dict())

    assert restored.evidence[0].current == 100
    assert restored.evidence[0].details == incident.evidence[0].details


def test_episode_transition_rows_keep_reason_and_previous_raw_lines():
    rows = build_peak_episode_transition_rows(SimpleNamespace(
        peak_episode_transitions=[{
            'episode_id': 'episode-1',
            'window_decision_id': 'decision-1',
            'previous_state': 'CONTINUATION',
            'state': 'ESCALATION',
            'correlation_method': 'event_time_cause_match',
            'material_change_reasons': ['material_impact_increase'],
            'previous_raw_error_lines': 100,
            'current_raw_error_lines': 180,
            'cumulative_raw_error_lines': 280,
        }],
    ))

    assert rows == [(
        'episode-1',
        'decision-1',
        'CONTINUATION',
        'ESCALATION',
        'material_impact_increase',
        100,
        180,
        280,
    )]


def test_detection_rows_keep_threshold_snapshot_and_flags():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    incident = Incident(id='inc-1', fingerprint='fp-a')
    incident.flags.is_spike = True
    incident.add_evidence(
        'spike_p93_cap',
        current=100,
        threshold=50,
        message='namespace total exceeds P93',
        details={
            'threshold_snapshot_id': '00000000-0000-0000-0000-000000000001',
            'detector_version': 'namespace_p93_cap_v2',
        },
    )
    collection = SimpleNamespace(incidents=[incident])
    fact_rows = [
        (
            'run-1', window_start, 'ns-a', 'app-a', 'fp-a', 'RuntimeError',
            'unknown', 'unclassified', 100, window_start, window_start,
            'failure', 'structured',
        )
    ]

    rows = build_detection_rows(collection, fact_rows, 'run-1')

    assert len(rows) == 1
    assert rows[0][4] == 'spike_p93_cap'
    assert rows[0][5] == 'namespace_p93_cap_v2'
    assert rows[0][8] == '00000000-0000-0000-0000-000000000001'
    assert json.loads(rows[0][9])['is_spike'] is True


def test_cause_family_rows_preserve_reconciled_operation_evidence():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    family = OperationalCauseFamily(
        signature='cause-1',
        canonical_cause='HibernateOptimisticLockingFailureException',
        root_app='bl-pcb-v1',
        operation='repairCard',
        outward_status=500,
        assessment='technical_failure',
        confidence='high',
        next_action='Inspect concurrent updates.',
        raw_error_lines=11,
        traced_error_lines=11,
        unsegmented_error_lines=0,
        unique_operations=1,
        amplification=11.0,
        app_counts={'bl-pcb-v1': 7, 'feapi-pca-v1': 4},
        namespace_counts={'pcb-prod-01-app': 11},
        representative_trace_id='trace-lock',
        trace_ids=('trace-lock',),
    )
    collection = SimpleNamespace(
        input_records=11,
        cause_analysis=CauseFamilyAnalysis(
            families=(family,),
            source_raw_error_lines=11,
            segmented_error_lines=11,
            unsegmented_error_lines=0,
            unique_operations=1,
        ),
    )

    rows = build_cause_family_rows(collection, 'run-1', window_start)

    assert len(rows) == 1
    assert rows[0][2] == 'cause-1'
    assert rows[0][3] == 'operational_cause_v1'
    assert rows[0][10:15] == (11, 11, 0, 1, 11.0)
    assert json.loads(rows[0][15]) == {'bl-pcb-v1': 7, 'feapi-pca-v1': 4}
    assert json.loads(rows[0][18]) == ['trace-lock']
    assert rows[0][19:22] == ('trace_id', 'medium', '')


def test_cause_family_rows_allow_multiple_operations_per_trace():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    family = OperationalCauseFamily(
        signature='cause-session',
        canonical_cause='Request failed',
        root_app='app-a',
        operation='submit',
        outward_status=500,
        assessment='technical_failure',
        confidence='high',
        next_action='Inspect the two failed requests.',
        raw_error_lines=2,
        traced_error_lines=2,
        unsegmented_error_lines=0,
        unique_operations=2,
        amplification=1.0,
        app_counts={'app-a': 2},
        namespace_counts={'ns-a': 2},
        representative_trace_id='session-trace',
        trace_ids=('session-trace',),
        operation_count_method='root_span',
        operation_count_confidence='high',
    )
    collection = SimpleNamespace(
        input_records=2,
        cause_analysis=CauseFamilyAnalysis(
            families=(family,),
            source_raw_error_lines=2,
            segmented_error_lines=2,
            unsegmented_error_lines=0,
            unique_operations=2,
        ),
    )

    rows = build_cause_family_rows(collection, 'run-session', window_start)

    assert rows[0][13] == 2
    assert json.loads(rows[0][18]) == ['session-trace']
    assert rows[0][19:22] == ('root_span', 'high', '')


def test_cause_family_rows_reject_processed_count_mismatch():
    collection = SimpleNamespace(
        input_records=2,
        cause_analysis=CauseFamilyAnalysis(
            families=(),
            source_raw_error_lines=0,
            segmented_error_lines=0,
            unsegmented_error_lines=0,
            unique_operations=0,
        ),
    )

    with pytest.raises(PersistenceInvariantError, match='processed count'):
        build_cause_family_rows(
            collection,
            'run-mismatch',
            datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc),
        )