#!/usr/bin/env python3
"""Regression tests for the operator-centered daily problem report."""

import csv
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, SCRIPTS)

from analysis.operational_cause import (  # noqa: E402
    CauseFamilyAnalysis,
    OperationalCauseFamily,
    build_collection_cause_analysis,
)
from analysis.problem_report import ProblemReportGenerator  # noqa: E402
from backfill import (  # noqa: E402
    _merge_collection_trace_data,
    _resolve_operator_trace_analysis,
    _validate_trace_evidence,
)
from core.streaming_aggregator import StreamingAggregator  # noqa: E402
from core.problem_registry import PeakEntry, ProblemEntry  # noqa: E402
from exports.table_exporter import TableExporter  # noqa: E402
from pipeline import Pipeline  # noqa: E402


def _family(**overrides):
    values = {
        'signature': 'family-1',
        'canonical_cause': 'HibernateOptimisticLockingFailureException while updating Card',
        'root_app': 'bl-pcb-v1',
        'operation': 'repairCard',
        'outward_status': 500,
        'assessment': 'technical_failure',
        'confidence': 'high',
        'next_action': 'Inspect concurrent updates and verify retry behavior.',
        'raw_error_lines': 11,
        'traced_error_lines': 11,
        'unsegmented_error_lines': 0,
        'unique_operations': 1,
        'amplification': 11.0,
        'app_counts': {'bl-pcb-v1': 7, 'feapi-pca-v1': 4},
        'namespace_counts': {'pcb-prod-01-app': 11},
        'representative_trace_id': 'trace-lock',
        'trace_ids': ('trace-lock',),
    }
    values.update(overrides)
    return OperationalCauseFamily(**values)


def _generator(analysis):
    generator = ProblemReportGenerator.__new__(ProblemReportGenerator)
    generator.analysis_start = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
    generator.analysis_end = datetime(2026, 8, 25, 8, 15, tzinfo=timezone.utc)
    generator.run_id = 'run-test'
    generator.problems = {}
    generator.cause_analysis = analysis
    return generator


def test_known_peak_pattern_shares_include_hidden_contributors():
    contributions = {'first': 40, 'second': 30, 'third': 20, 'fourth': 10}
    registry = SimpleNamespace(problems={
        key: SimpleNamespace(
            behavior=f'Observed failure in {key}',
            app_counts={f'app-{key}': count},
        )
        for key, count in contributions.items()
    })
    peak = SimpleNamespace(contributing_problems=contributions, raw_error_count=100)

    behavior = TableExporter(registry)._format_peak_behavior(peak)

    assert '100' in behavior
    assert '40 ERROR lines, 40%' in behavior
    assert '30 ERROR lines, 30%' in behavior
    assert '20 ERROR lines, 20%' in behavior
    assert '90 ERROR lines' not in behavior


def test_known_peak_share_does_not_invent_diagnostic_confidence():
    problem = ProblemEntry('KP-1', 'database:repair:lock', 'database', 'repair', 'LockException')
    problem.behavior = 'Concurrent update rejected'
    peak = SimpleNamespace(contributing_problems={problem.problem_key: 100}, raw_error_count=100)
    exporter = TableExporter(SimpleNamespace(problems={problem.problem_key: problem}))

    assert exporter._format_peak_root_cause(peak) == ''

    problem.trace_root_cause = {
        'message': 'Concurrent update rejected', 'service': 'cards', 'confidence': 'low',
    }
    root_cause = exporter._format_peak_root_cause(peak)
    assert '[low]' in root_cause
    assert '100% of ERROR lines' in root_cause
    assert '[high' not in root_cause


def test_known_errors_csv_is_a_catalog_with_separate_historical_evidence(tmp_path):
    problem = ProblemEntry('KP-1', 'business:repair:missing', 'business', 'repair', 'NotFound')
    problem.sample_messages = ['Client does not exist', 'Card does not exist | repair failed']
    problem.occurrences = 500
    problem.jira = 'KB-123'
    problem.notes = 'Owner: cards; verify "repair" contract'
    exporter = TableExporter(SimpleNamespace(problems={problem.problem_key: problem}, peaks={}))
    output = tmp_path / 'errors.csv'

    exporter.export_errors_csv(str(output))
    with output.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames[:3] == ['problem_id', 'cause', 'diagnosis']
        row = next(reader)

    assert row['cause'] == 'Client does not exist'
    assert row['diagnosis'] == 'Not diagnosed; observed pattern only'
    assert row['root_cause'] == ''
    assert row['jira'] == problem.jira
    assert row['notes'] == problem.notes
    assert 'Client does not exist' not in row['behavior']
    assert 'Card does not exist | repair failed' in row['behavior']
    assert 'retained samples' in row['metric_scope']
    assert row['occurrence_total'] == '500'


def test_legacy_known_peak_does_not_turn_maximum_into_a_total(tmp_path):
    peak = PeakEntry('PK-1', 'PEAK:business:repair:SPIKE', 'SPIKE', occurrences=3, max_value=200)
    unrelated = ProblemEntry('KP-1', 'business:repair:unrelated', 'business', 'repair', 'Other')
    unrelated.root_cause = 'Unrelated historical failure'
    exporter = TableExporter(SimpleNamespace(
        problems={unrelated.problem_key: unrelated}, peaks={peak.problem_key: peak},
    ))
    output = tmp_path / 'peaks.csv'

    exporter.export_peaks_csv(str(output))
    with output.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames[:3] == ['peak_id', 'peak_type', 'diagnosis']
        row = next(reader)

    assert row['total_errors'] == ''
    assert row['avg_errors_per_peak'] == ''
    assert row['max_observed_errors'] == '200'
    assert row['occurrence_count'] == '3'
    assert row['root_cause'] == ''
    assert 'not the UTC slot baseline' in row['metric_scope']
    exporter.export_peaks_markdown(str(tmp_path / 'peaks.md'))
    assert 'N/A' in (tmp_path / 'peaks.md').read_text(encoding='utf-8')


def test_known_tables_markdown_preserves_structure_with_untrusted_log_text(tmp_path):
    problem = ProblemEntry('KP-1', 'business:repair:missing', 'business', 'repair', 'NotFound')
    problem.description = '<script>alert(1)</script> | rejected'
    problem.affected_apps = {'cards|repair'}
    problem.last_seen = datetime.now(timezone.utc)
    problem.notes = '<img src=x> | operator note'
    peak = PeakEntry('PK-1', 'PEAK:business:repair:SPIKE', 'SPIKE', occurrences=2)
    peak.behavior = problem.description
    peak.notes = problem.notes
    exporter = TableExporter(SimpleNamespace(
        problems={problem.problem_key: problem}, peaks={peak.problem_key: peak},
    ))

    for kind, width in [('errors', 12), ('peaks', 13)]:
        output = tmp_path / f'{kind}.md'
        getattr(exporter, f'export_{kind}_markdown')(str(output))
        text = output.read_text(encoding='utf-8')
        assert '<script>' not in text
        assert '<img' not in text
        assert '&#124;' in text
        main_table = text.split('## All Problems', 1)[-1] if kind == 'errors' else text
        table_lines = [line for line in main_table.splitlines() if line.startswith('|')]
        assert all(len(line.split('|')) == width + 2 for line in table_lines)


def test_operator_daily_report_uses_cause_families_and_operation_impact(monkeypatch):
    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'true')
    analysis = CauseFamilyAnalysis(
        families=(_family(),),
        source_raw_error_lines=11,
        segmented_error_lines=11,
        unsegmented_error_lines=0,
        unique_operations=1,
    )

    report = _generator(analysis).generate_text_report()

    assert 'EXECUTIVE SUMMARY' in report
    assert 'PROBLEM DETAILS' in report
    assert 'Actionable technical: 1' in report
    assert 'Operation occurrences: 1' in report
    assert '[TECHNICAL FAILURE] HibernateOptimisticLockingFailureException' in report
    assert 'Unique operations: 1' in report
    assert 'Operation count evidence: trace_id (medium confidence)' in report
    assert 'Raw ERROR lines: 11' in report
    assert 'Logging amplification: 11.0x' in report
    assert 'Representative trace: trace-lock' in report
    assert 'Next action:' in report
    assert 'Context coverage: not_fetched' in report
    assert 'Behavior (top patterns)' not in report


def test_operator_report_exposes_incomplete_context(monkeypatch):
    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'true')
    analysis = CauseFamilyAnalysis(
        families=(_family(context_coverage={'status': 'truncated'}),),
        source_raw_error_lines=11, segmented_error_lines=11,
        unsegmented_error_lines=0, unique_operations=1,
    )
    assert 'Context coverage: truncated' in _generator(analysis).generate_text_report()


def test_operator_daily_report_marks_missing_trace_coverage(monkeypatch):
    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'true')
    family = _family(
        signature='family-untraced',
        canonical_cause='Client does not exist',
        assessment='business_rejection',
        confidence='medium',
        raw_error_lines=4,
        traced_error_lines=0,
        unsegmented_error_lines=4,
        unique_operations=None,
        amplification=None,
        representative_trace_id='',
        trace_ids=(),
        operation_count_method='unavailable',
        operation_count_confidence='low',
        operation_count_reason='trace coverage unavailable',
    )
    analysis = CauseFamilyAnalysis(
        families=(family,),
        source_raw_error_lines=4,
        segmented_error_lines=0,
        unsegmented_error_lines=4,
        unique_operations=0,
    )

    report = _generator(analysis).generate_text_report()

    assert 'Operation occurrences: N/A (trace coverage unavailable)' in report
    assert 'Unique operations: N/A (trace coverage unavailable)' in report
    assert 'Operation count evidence: unavailable (low confidence)' in report
    assert 'Unsegmented ERROR lines: 4' in report
    assert 'Representative trace: N/A' in report


def test_operator_daily_report_refuses_unreconciled_counts(monkeypatch):
    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'true')
    analysis = CauseFamilyAnalysis(
        families=(_family(raw_error_lines=10),),
        source_raw_error_lines=11,
        segmented_error_lines=11,
        unsegmented_error_lines=0,
        unique_operations=1,
    )

    try:
        _generator(analysis).generate_text_report()
    except ValueError as error:
        assert 'cause-family' in str(error)
        assert 'failed' in str(error)
    else:
        raise AssertionError('unreconciled report must fail closed')


def test_backfill_merges_trace_data_from_each_daily_collection():
    first_timeline = object()
    second_timeline = object()
    first_pattern = object()
    second_pattern = object()
    collections = [
        ('2026-08-24', SimpleNamespace(
            trace_timelines={'trace-a': first_timeline},
            trace_pattern_index={'trace-a': first_pattern},
        )),
        ('2026-08-25', SimpleNamespace(
            trace_timelines={'trace-b': second_timeline},
            trace_pattern_index={'trace-b': second_pattern},
        )),
    ]

    timelines, patterns = _merge_collection_trace_data(collections)

    assert timelines == {
        'trace-a': first_timeline,
        'trace-b': second_timeline,
    }
    assert patterns == {
        'trace-a': first_pattern,
        'trace-b': second_pattern,
    }


def test_trace_analysis_defaults_to_operator_report_state(monkeypatch):
    monkeypatch.delenv('OPERATOR_DAILY_REPORT_ENABLED', raising=False)
    monkeypatch.delenv('OPERATOR_DAILY_TRACE_ANALYSIS_ENABLED', raising=False)

    assert _resolve_operator_trace_analysis() is True

    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'false')
    assert _resolve_operator_trace_analysis() is False


def test_operator_report_rejects_explicitly_disabled_trace_analysis(monkeypatch):
    monkeypatch.setenv('OPERATOR_DAILY_REPORT_ENABLED', 'true')
    monkeypatch.setenv('OPERATOR_DAILY_TRACE_ANALYSIS_ENABLED', 'false')

    try:
        _resolve_operator_trace_analysis()
    except ValueError as error:
        assert 'requires OPERATOR_DAILY_TRACE_ANALYSIS_ENABLED' in str(error)
    else:
        raise AssertionError('operator report without trace analysis must fail')


def test_trace_evidence_guard_rejects_lost_timelines():
    collection = SimpleNamespace(
        incidents=[SimpleNamespace(trace_event_counts={'trace-a': 2})],
        trace_timelines={},
    )

    try:
        _validate_trace_evidence(collection, enabled=True)
    except RuntimeError as error:
        assert 'no trace timelines were built' in str(error)
    else:
        raise AssertionError('lost trace timelines must fail the backfill')


def test_default_operator_contract_builds_segmented_trace_evidence(monkeypatch):
    monkeypatch.delenv('OPERATOR_DAILY_REPORT_ENABLED', raising=False)
    monkeypatch.delenv('OPERATOR_DAILY_TRACE_ANALYSIS_ENABLED', raising=False)
    aggregator = StreamingAggregator()
    aggregator.ingest_page([{
        'message': 'upstream call failed -> 500',
        'application': 'svc-a',
        'namespace': 'ns-a',
        'timestamp': '2026-09-29T12:00:00Z',
        'traceId': 'trace-a',
    }])
    aggregator.finalize()

    try:
        trace_enabled = _resolve_operator_trace_analysis()
        collection = Pipeline(
            build_trace_patterns=trace_enabled
        ).run_streaming(aggregator, run_id='operator-trace-contract')
    finally:
        aggregator.close()

    _validate_trace_evidence(collection, trace_enabled)
    analysis = build_collection_cause_analysis(collection)

    assert set(collection.trace_timelines) == {'trace-a'}
    assert analysis.segmented_error_lines == 1
    assert analysis.unsegmented_error_lines == 0
    assert analysis.unique_operations == 1