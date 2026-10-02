#!/usr/bin/env python3
"""Tests for operator-facing cause-family analysis."""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch


HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, SCRIPTS)

from analysis.operational_cause import (  # noqa: E402
    CauseFamilyAnalysis,
    build_cause_family,
    build_collection_cause_analysis,
    build_daily_cause_analysis,
    merge_cause_families,
)
from analysis.trace_timeline import (  # noqa: E402
    TraceEvent,
    TraceTimeline,
    estimate_operation_occurrences,
    segment_operation_timelines,
)
from pipeline.incident import Incident  # noqa: E402


class OperationalCauseFamilyTests(unittest.TestCase):
    def test_operation_count_uses_complete_root_span_ancestry(self):
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "first", span_id="error-a", parent_span_id="root-a"),
            TraceEvent(None, "app", "Failure", "second", span_id="error-b", parent_span_id="root-b"),
        ])
        context = TraceTimeline("session-trace", [
            TraceEvent(None, "edge", "info", "request a", level="INFO", span_id="root-a"),
            TraceEvent(None, "edge", "info", "request b", level="INFO", span_id="root-b"),
        ])

        estimate = estimate_operation_occurrences(timeline, context, 2)

        self.assertEqual(estimate.count, 2)
        self.assertEqual(estimate.method, "root_span")
        self.assertEqual(estimate.confidence, "high")

    def test_operation_count_uses_trace_fallback_for_one_unresolved_root(self):
        timeline = TraceTimeline("trace-a", [
            TraceEvent(None, "app", "Failure", "first", span_id="error-a", parent_span_id="missing-root"),
            TraceEvent(None, "app", "Failure", "second", span_id="error-b", parent_span_id="missing-root"),
        ])

        estimate = estimate_operation_occurrences(timeline, expected_error_lines=2)

        self.assertEqual(estimate.count, 1)
        self.assertEqual(estimate.method, "trace_id")
        self.assertEqual(estimate.confidence, "medium")

    def test_operation_count_refuses_long_trace_id_fallback(self):
        started_at = datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc)
        timeline = TraceTimeline("session-trace", [
            TraceEvent(started_at, "app", "Failure", "first"),
            TraceEvent(started_at + timedelta(minutes=16), "app", "Failure", "second"),
        ])

        with patch.dict(os.environ, {
            "OPERATION_TRACE_FALLBACK_MAX_DURATION_MIN": "15",
            "OPERATION_TRACE_FALLBACK_MAX_ERRORS": "100",
        }):
            estimate = estimate_operation_occurrences(timeline, expected_error_lines=2)

        self.assertIsNone(estimate.count)
        self.assertEqual(estimate.method, "unavailable")
        self.assertIn("duration exceeds 15 minutes", estimate.reason)

    def test_operation_count_refuses_noisy_trace_id_fallback(self):
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", f"error-{index}")
            for index in range(3)
        ])

        with patch.dict(os.environ, {
            "OPERATION_TRACE_FALLBACK_MAX_DURATION_MIN": "15",
            "OPERATION_TRACE_FALLBACK_MAX_ERRORS": "2",
        }):
            estimate = estimate_operation_occurrences(timeline, expected_error_lines=3)

        self.assertIsNone(estimate.count)
        self.assertEqual(estimate.method, "unavailable")
        self.assertIn("3 ERROR events exceed limit 2", estimate.reason)

    def test_operation_count_refuses_ambiguous_incomplete_mega_trace(self):
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "first", span_id="error-a", parent_span_id="missing-a"),
            TraceEvent(None, "app", "Failure", "second", span_id="error-b", parent_span_id="missing-b"),
        ])

        estimate = estimate_operation_occurrences(timeline, expected_error_lines=2)

        self.assertIsNone(estimate.count)
        self.assertEqual(estimate.method, "unavailable")
        self.assertEqual(estimate.confidence, "low")
        self.assertIn("multiple root/request candidates", estimate.reason)

    def test_operation_segments_keep_root_context_separate(self):
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "first", span_id="error-a", parent_span_id="root-a"),
            TraceEvent(None, "app", "Failure", "second", span_id="error-b", parent_span_id="root-b"),
        ])
        context = TraceTimeline("session-trace", [
            TraceEvent(None, "edge", "info", "context a", level="INFO", span_id="root-a"),
            TraceEvent(None, "edge", "info", "context b", level="INFO", span_id="root-b"),
        ])

        segments, estimate = segment_operation_timelines(timeline, context, 2)

        self.assertEqual(estimate.count, 2)
        self.assertEqual([segment.root_span_id for segment in segments], ["root-a", "root-b"])
        self.assertEqual(
            [[event.message for event in segment.context_timeline.events] for segment in segments],
            [["context a"], ["context b"]],
        )

    def test_reports_unique_operations_separately_from_raw_lines(self):
        family = build_cause_family({
            "error_count": 200,
            "root_cause": {
                "service": "bl-pcb-v1",
                "message": "Card with product instance null not found",
            },
            "trace_counts": {f"trace-{index}": 5 for index in range(40)},
            "app_counts": {"bl-pcb-v1": 200},
            "namespace_counts": {"pcb-prod-01-app": 200},
        })

        self.assertEqual(family.raw_error_lines, 200)
        self.assertEqual(family.traced_error_lines, 200)
        self.assertEqual(family.unsegmented_error_lines, 0)
        self.assertEqual(family.unique_operations, 40)
        self.assertEqual(family.amplification, 5.0)
        self.assertEqual(family.assessment, "business_rejection")

    def test_analysis_refuses_operation_count_mismatch(self):
        family = build_cause_family({
            "error_count": 2,
            "root_cause": {"service": "app", "message": "Request failed"},
            "trace_counts": {"trace-a": 2},
        })
        analysis = CauseFamilyAnalysis(
            families=(family,),
            source_raw_error_lines=2,
            segmented_error_lines=2,
            unsegmented_error_lines=0,
            unique_operations=2,
        )

        with self.assertRaisesRegex(ValueError, "operation-count reconciliation"):
            analysis.validate()

    def test_same_exception_class_keeps_distinct_concrete_causes(self):
        client_missing = build_cause_family({
            "error_class": "ServiceBusinessException",
            "root_cause": {"service": "bl-pcb-v1", "message": "Client does not exist"},
        })
        card_missing = build_cause_family({
            "error_class": "ServiceBusinessException",
            "root_cause": {"service": "bl-pcb-v1", "message": "Card not found"},
        })

        self.assertNotEqual(client_missing.signature, card_missing.signature)
        self.assertEqual(client_missing.canonical_cause, "Client does not exist")
        self.assertEqual(card_missing.canonical_cause, "Card not found")

    def test_concrete_trace_message_outranks_generic_wrapper(self):
        family = build_cause_family({
            "error_class": "ServiceBusinessException",
            "root_cause": {
                "service": "feapi-pca-v1",
                "message": "ServiceBusinessException error handled",
            },
            "trace_steps": [{
                "app": "bl-pcb-v1",
                "message": "HibernateOptimisticLockingFailureException while updating Card",
            }],
            "behavior_text": "repairCard -> 500",
        })

        self.assertIn("HibernateOptimisticLockingFailureException", family.canonical_cause)
        self.assertEqual(family.root_app, "bl-pcb-v1")
        self.assertEqual(family.assessment, "technical_failure")
        self.assertEqual(family.outward_status, 500)
        self.assertIn("optimistic-lock", family.next_action)

    def test_cancelled_requires_explicit_evidence_for_expected_assessment(self):
        without_context = build_cause_family({
            "root_cause_text": "CardsServiceImpl#cardTokenizationCompletedAction -> 400",
        })
        with_context = build_cause_family({
            "root_cause_text": "CardsServiceImpl#cardTokenizationCompletedAction -> 400",
            "trace_steps": [{"message": "result=CANCELLED; case cancelled by user"}],
        })

        self.assertEqual(without_context.assessment, "unknown")
        self.assertEqual(with_context.assessment, "expected_outcome_logged_as_error")
        self.assertEqual(with_context.operation, "cardTokenizationCompletedAction")

    def test_technical_failure_outranks_cancelled_context(self):
        family = build_cause_family({
            "root_cause": {
                "service": "bl-pcb-v1",
                "message": "HibernateOptimisticLockingFailureException while updating Card",
            },
            "trace_steps": [{
                "app": "bff-card-v1",
                "message": "result=CANCELLED; case cancelled by user",
            }],
        })

        self.assertEqual(family.assessment, "technical_failure")
        self.assertEqual(family.confidence, "high")

    def test_merge_uses_max_for_aliases_and_sum_for_repeated_occurrences(self):
        first = build_cause_family({
            "error_count": 9,
            "root_cause": {"service": "bl-pcb-v1", "message": "Client does not exist"},
            "trace_counts": {"trace-a": 9},
            "app_counts": {"bl-pcb-v1": 9},
        })
        alias = build_cause_family({
            "error_count": 9,
            "root_cause": {"service": "feapi-pca-v1", "message": "General error handled"},
            "trace_steps": [{"app": "bl-pcb-v1", "message": "Client does not exist"}],
            "trace_counts": {"trace-a": 9},
            "app_counts": {"bl-pcb-v1": 9},
        })
        repeated = build_cause_family({
            "error_count": 6,
            "root_cause": {"service": "bl-pcb-v1", "message": "Client does not exist"},
            "trace_counts": {"trace-b": 6},
            "app_counts": {"bl-pcb-v1": 6},
        })

        merged_alias = merge_cause_families(first, alias, same_events=True)
        merged_repeated = merge_cause_families(merged_alias, repeated, same_events=False)

        self.assertEqual(merged_alias.raw_error_lines, 9)
        self.assertEqual(merged_repeated.raw_error_lines, 15)
        self.assertEqual(merged_repeated.unique_operations, 2)
        self.assertEqual(merged_repeated.app_counts, {"bl-pcb-v1": 15})

    def test_daily_analysis_groups_operations_and_reconciles_unsegmented_lines(self):
        first = SimpleNamespace(
            fingerprint="fp-card",
            stats=SimpleNamespace(current_count=11),
            trace_event_counts={"trace-card": 9},
            app_event_counts={"bl-pcb-v1": 11},
            normalized_message="Client does not exist",
            error_type="ServiceBusinessException",
        )
        second = SimpleNamespace(
            fingerprint="fp-lock",
            stats=SimpleNamespace(current_count=6),
            trace_event_counts={"trace-lock": 6},
            app_event_counts={"bl-pcb-v1": 6},
            normalized_message="HibernateOptimisticLockingFailureException",
            error_type="ServiceBusinessException",
        )
        problems = {
            "business": SimpleNamespace(incidents=[first]),
            "technical": SimpleNamespace(incidents=[second]),
        }
        timelines = {
            "trace-card": TraceTimeline("trace-card", [
                TraceEvent(None, "bl-pcb-v1", "ServiceBusinessException", "Client does not exist")
                for _ in range(9)
            ]),
            "trace-lock": TraceTimeline("trace-lock", [
                TraceEvent(
                    None,
                    "bl-pcb-v1",
                    "HibernateOptimisticLockingFailureException",
                    "HibernateOptimisticLockingFailureException while updating Card",
                )
                for _ in range(6)
            ]),
        }
        ownership = {
            "business": SimpleNamespace(owned_trace_ids=["trace-card"]),
            "technical": SimpleNamespace(owned_trace_ids=["trace-lock"]),
        }

        analysis = build_daily_cause_analysis(problems, timelines, ownership)

        self.assertEqual(analysis.source_raw_error_lines, 17)
        self.assertEqual(analysis.segmented_error_lines, 15)
        self.assertEqual(analysis.unsegmented_error_lines, 2)
        self.assertEqual(analysis.unique_operations, 2)
        self.assertEqual(sum(f.raw_error_lines for f in analysis.families), 17)
        self.assertEqual(
            {family.assessment for family in analysis.families},
            {"business_rejection", "technical_failure"},
        )

    def test_daily_analysis_counts_multiple_root_spans_in_one_trace(self):
        incident = SimpleNamespace(
            fingerprint="fp-session",
            stats=SimpleNamespace(current_count=2),
            trace_event_counts={"session-trace": 2},
            app_event_counts={"app": 2},
            normalized_message="Operation failed",
            error_type="Failure",
        )
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "Operation failed", span_id="error-a", parent_span_id="root-a"),
            TraceEvent(None, "app", "Failure", "Operation failed", span_id="error-b", parent_span_id="root-b"),
        ])
        context = TraceTimeline("session-trace", [
            TraceEvent(None, "edge", "info", "request", level="INFO", span_id="root-a"),
            TraceEvent(None, "edge", "info", "request", level="INFO", span_id="root-b"),
        ])

        analysis = build_daily_cause_analysis(
            {"session": SimpleNamespace(incidents=[incident])},
            {"session-trace": timeline},
            {"session": SimpleNamespace(owned_trace_ids=["session-trace"])},
            {"session-trace": SimpleNamespace(representative=context)},
        )

        self.assertEqual(analysis.unique_operations, 2)
        self.assertEqual(analysis.families[0].unique_operations, 2)
        self.assertEqual(analysis.families[0].operation_count_method, "root_span")
        self.assertEqual(analysis.families[0].operation_count_confidence, "high")
        self.assertEqual(analysis.families[0].trace_ids, ("session-trace",))

    def test_daily_analysis_marks_ambiguous_mega_trace_impact_unavailable(self):
        incident = SimpleNamespace(
            fingerprint="fp-session",
            stats=SimpleNamespace(current_count=2),
            trace_event_counts={"session-trace": 2},
            app_event_counts={"app": 2},
            normalized_message="Operation failed",
            error_type="Failure",
        )
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "first", span_id="error-a", parent_span_id="missing-a"),
            TraceEvent(None, "app", "Failure", "second", span_id="error-b", parent_span_id="missing-b"),
        ])

        analysis = build_daily_cause_analysis(
            {"session": SimpleNamespace(incidents=[incident])},
            {"session-trace": timeline},
            {"session": SimpleNamespace(owned_trace_ids=["session-trace"])},
        )

        family = analysis.families[0]
        self.assertIsNone(analysis.unique_operations)
        self.assertIsNone(family.unique_operations)
        self.assertEqual(family.operation_count_method, "unavailable")
        self.assertIn("multiple root/request candidates", family.operation_count_reason)
        self.assertEqual(family.raw_error_lines, 2)
        self.assertEqual(family.traced_error_lines, 2)

    def test_daily_analysis_separates_causes_under_different_root_spans(self):
        incident = SimpleNamespace(
            fingerprint="fp-session",
            stats=SimpleNamespace(current_count=2),
            trace_event_counts={"session-trace": 2},
            app_event_counts={"app": 2},
            normalized_message="Operation failed",
            error_type="Failure",
        )
        timeline = TraceTimeline("session-trace", [
            TraceEvent(None, "app", "Failure", "Client does not exist", span_id="error-a", parent_span_id="root-a"),
            TraceEvent(None, "app", "Failure", "HibernateOptimisticLockingFailureException", span_id="error-b", parent_span_id="root-b"),
        ])
        context = TraceTimeline("session-trace", [
            TraceEvent(None, "edge", "info", "request a", level="INFO", span_id="root-a"),
            TraceEvent(None, "edge", "info", "request b", level="INFO", span_id="root-b"),
        ])

        analysis = build_daily_cause_analysis(
            {"session": SimpleNamespace(incidents=[incident])},
            {"session-trace": timeline},
            {"session": SimpleNamespace(owned_trace_ids=["session-trace"])},
            {"session-trace": SimpleNamespace(representative=context)},
        )

        self.assertEqual(len(analysis.families), 2)
        self.assertEqual(analysis.unique_operations, 2)
        self.assertEqual(
            {family.assessment for family in analysis.families},
            {"business_rejection", "technical_failure"},
        )
        self.assertEqual(
            {family.raw_error_lines for family in analysis.families},
            {1},
        )

    def test_daily_analysis_uses_pattern_context_without_counting_info_lines(self):
        incident = SimpleNamespace(
            fingerprint="fp-cancel",
            stats=SimpleNamespace(current_count=1),
            trace_event_counts={"trace-cancel": 1},
            app_event_counts={"bff-card-v1": 1},
            normalized_message="cardTokenizationCompletedAction -> 400",
            error_type="CardsServiceCallError",
        )
        error_timeline = TraceTimeline("trace-cancel", [
            TraceEvent(
                None,
                "bff-card-v1",
                "CardsServiceCallError",
                "CardsServiceImpl#cardTokenizationCompletedAction -> 400",
            ),
        ])
        enriched_representative = TraceTimeline("trace-cancel", [
            TraceEvent(
                None,
                "bff-card-v1",
                "info",
                "result=CANCELLED; case cancelled by user",
                level="INFO",
            ),
            *error_timeline.events,
        ])

        analysis = build_daily_cause_analysis(
            {"cancel": SimpleNamespace(incidents=[incident])},
            {"trace-cancel": error_timeline},
            {"cancel": SimpleNamespace(owned_trace_ids=["trace-cancel"])},
            {"trace-cancel": SimpleNamespace(representative=enriched_representative)},
        )

        self.assertEqual(len(analysis.families), 1)
        family = analysis.families[0]
        self.assertEqual(family.assessment, "expected_outcome_logged_as_error")
        self.assertEqual(family.raw_error_lines, 1)
        self.assertEqual(family.traced_error_lines, 1)
        self.assertEqual(family.unique_operations, 1)

    def test_daily_analysis_does_not_copy_context_from_another_trace(self):
        incident = SimpleNamespace(
            fingerprint="fp-cancel",
            stats=SimpleNamespace(current_count=1),
            trace_event_counts={"trace-other": 1},
            app_event_counts={"bff-card-v1": 1},
            normalized_message="cardTokenizationCompletedAction -> 400",
            error_type="CardsServiceCallError",
        )
        error_timeline = TraceTimeline("trace-other", [
            TraceEvent(
                None,
                "bff-card-v1",
                "CardsServiceCallError",
                "CardsServiceImpl#cardTokenizationCompletedAction -> 400",
            ),
        ])
        another_trace_context = TraceTimeline("trace-representative", [
            TraceEvent(
                None,
                "bff-card-v1",
                "info",
                "result=CANCELLED; case cancelled by user",
                level="INFO",
            ),
        ])

        analysis = build_daily_cause_analysis(
            {"cancel": SimpleNamespace(incidents=[incident])},
            {"trace-other": error_timeline},
            {"cancel": SimpleNamespace(owned_trace_ids=["trace-other"])},
            {"trace-other": SimpleNamespace(representative=another_trace_context)},
        )

        self.assertEqual(analysis.families[0].assessment, "unknown")

    def test_collection_analysis_attaches_reconciled_facts(self):
        incident = Incident(id="inc-1", fingerprint="fp-untraced")
        incident.stats.current_count = 3
        incident.app_event_counts = {"app-a": 3}
        incident.apps = ["app-a"]
        incident.normalized_message = "Client does not exist"
        incident.error_type = "ServiceBusinessException"
        collection = SimpleNamespace(
            incidents=[incident],
            input_records=3,
            trace_timelines={},
            trace_pattern_index={},
        )

        analysis = build_collection_cause_analysis(collection)

        self.assertIs(collection.cause_analysis, analysis)
        self.assertEqual(analysis.source_raw_error_lines, 3)
        self.assertEqual(analysis.unsegmented_error_lines, 3)


if __name__ == "__main__":
    unittest.main()