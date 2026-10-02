#!/usr/bin/env python3
"""Regression tests for the operator-centered daily problem report."""

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
    assert 'Behavior (top patterns)' not in report


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