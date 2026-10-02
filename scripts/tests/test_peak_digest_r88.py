#!/usr/bin/env python3
"""Regression tests for r88 peak digest correlation and rendering."""

import os
import signal
import sys
import unittest
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.normpath(os.path.join(HERE, '..'))
sys.path.insert(0, SCRIPTS)

import regular_phase as rp  # noqa: E402
from analysis.operational_cause import build_cause_family  # noqa: E402
from core.email_notifier import EmailNotifier  # noqa: E402
from pipeline.incident import Evidence  # noqa: E402


def _problem(key, message, count=127, error_class='not_found', traces=()):
    incident = SimpleNamespace(
        trace_event_counts={trace_id: 1 for trace_id in traces},
        trace_ids=list(traces),
    )
    return SimpleNamespace(
        problem_key=key,
        normalized_message=message,
        sample_messages=[message],
        total_occurrences=count,
        apps={'bl-pcb-v1'},
        namespaces={'pcb-uat-01-app'},
        error_class=error_class,
        incidents=[incident] if traces else [],
        max_score=80,
    )


def _payload(problem, *_args, **_kwargs):
    return {
        'error_count': problem.total_occurrences,
        'app_counts': {'bl-pcb-v1': 127},
        'all_app_counts': {'bl-pcb-v1': 127},
        'namespace_counts': {'pcb-uat-01-app': 65},
        'all_namespace_counts': {'pcb-uat-01-app': 65, 'pcb-sit-01-app': 62},
        'affected_apps': ['bl-pcb-v1'],
        'affected_namespaces': ['pcb-uat-01-app', 'pcb-sit-01-app'],
        'originator_application_counts': {},
        'trace_counts': {
            trace_id: 1
            for incident in problem.incidents
            for trace_id in getattr(incident, 'trace_ids', [])
        },
        'trace_steps': [{
            'app': 'bl-pcb-v1',
            'count': 127,
            'message': problem.normalized_message,
        }],
        'behavior_text': problem.normalized_message,
    }


class PeakDigestR88Tests(unittest.TestCase):
    def setUp(self):
        self.first = _problem(
            'a',
            'Called operation has failed, description Person with CustomerID '
            'specified in the request not found',
        )
        self.second = _problem(
            'b',
            'PrimeIssuerServicesSoap FindEntityRequest ends with error: Person '
            'with CustomerID specified in the request not found',
        )

    def test_duplicate_behavior_rows_are_collapsed(self):
        behavior = rp._summarize_behavior_steps([
            {
                'app': 'bl-pcb-v1',
                'count': 127,
                'share_pct': 50,
                'message': 'An unexpected error occurred during case step processing.',
            },
            {
                'app': 'bl-pcb-v1',
                'count': 127,
                'share_pct': 50,
                'message': 'An unexpected error occurred during step processing, case 7542571.',
            },
        ])

        self.assertEqual(behavior.count('\n'), 0)
        self.assertIn('127 events', behavior)
        self.assertNotIn('[50%]', behavior)

    def test_alert_limit_records_skipped_policy_outcome(self):
        payload = {
            'peak_key': 'peak-omitted',
            'window_key': '2026-07-31T08:00:00Z',
            'error_count': 42,
        }

        with patch.object(rp, '_notification_destinations', return_value=['teams_webhook']):
            outcomes = rp._policy_delivery_outcomes(
                payload,
                'skipped',
                'MAX_PEAK_ALERTS_PER_WINDOW limit (3)',
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]['status'], 'skipped')
        self.assertEqual(outcomes[0]['destination'], 'teams_webhook')
        self.assertEqual(outcomes[0]['dedup_key'], 'peak-omitted:2026-07-31T08:00:00Z')
        self.assertEqual(outcomes[0]['metadata']['attempt_kind'], 'policy')

    def test_provider_delivery_keeps_notification_decision_link(self):
        payload = {
            'peak_key': 'peak-linked',
            'window_key': '2026-07-31T08:00:00Z',
            'notification_decision_id': 'decision-linked',
        }

        outcomes = rp._payload_delivery_outcomes(
            payload,
            [{'destination': 'teams_email', 'status': 'delivered'}],
            'digest',
        )

        self.assertEqual(outcomes[0]['notification_decision_id'], 'decision-linked')

    def test_cluster_delivery_links_all_episode_decisions(self):
        payload = {
            'peak_key': 'peak-clustered',
            'window_key': '2026-07-31T08:00:00Z',
            'notification_decision_ids': ['decision-a', 'decision-b'],
        }

        outcomes = rp._payload_delivery_outcomes(
            payload,
            [{'destination': 'teams_email', 'status': 'delivered'}],
            'digest',
        )

        self.assertEqual(
            [outcome['notification_decision_id'] for outcome in outcomes],
            ['decision-a', 'decision-b'],
        )

    def test_cause_signature_separates_cooldown_and_delivery_identity(self):
        first = {
            'peak_key': 'PEAK:business:card:spike',
            'window_key': 'w1',
            'cause_families': [{'signature': 'cause-a'}],
        }
        second = {
            'peak_key': 'PEAK:business:card:spike',
            'window_key': 'w1',
            'cause_families': [{'signature': 'cause-b'}],
        }

        self.assertNotEqual(rp._alert_identity(first), rp._alert_identity(second))
        self.assertNotEqual(
            rp._delivery_dedup_key(first),
            rp._delivery_dedup_key(second),
        )

    def test_authoritative_families_replace_payload_on_exact_trace_and_count_match(self):
        client_missing = build_cause_family({
            'error_count': 1,
            'root_cause': {'service': 'app', 'message': 'Client does not exist'},
            'trace_counts': {'session-trace': 1},
            'unique_operations': 1,
            'operation_count_method': 'root_span',
            'operation_count_confidence': 'high',
        })
        lock_failure = build_cause_family({
            'error_count': 1,
            'root_cause': {
                'service': 'app',
                'message': 'HibernateOptimisticLockingFailureException',
            },
            'trace_counts': {'session-trace': 1},
            'unique_operations': 1,
            'operation_count_method': 'root_span',
            'operation_count_confidence': 'high',
        })
        payload = {
            'error_count': 2,
            'trace_counts': {'session-trace': 2},
            'cause_families': [{'signature': 'legacy'}],
        }

        attached = rp._attach_authoritative_cause_families(
            payload,
            SimpleNamespace(families=(client_missing, lock_failure)),
        )

        self.assertTrue(attached)
        self.assertEqual(len(payload['cause_families']), 2)
        self.assertEqual(
            {family['operation_count_method'] for family in payload['cause_families']},
            {'root_span'},
        )
        self.assertNotIn('legacy', payload['alert_identity'])

    def test_authoritative_families_mark_partial_scope_and_unexplained_lines(self):
        family = build_cause_family({
            'error_count': 1,
            'root_cause': {'service': 'app', 'message': 'Client does not exist'},
            'trace_counts': {'session-trace': 1},
        })
        legacy = {'signature': 'legacy'}
        payload = {
            'error_count': 2,
            'trace_counts': {'session-trace': 2},
            'cause_families': [legacy],
        }

        attached = rp._attach_authoritative_cause_families(
            payload,
            SimpleNamespace(families=(family,)),
        )

        self.assertFalse(attached)
        self.assertEqual(payload['cause_evidence_status'], 'partial')
        self.assertEqual(payload['cause_reconciliation']['unexplained_raw_lines'], 1)
        self.assertEqual(
            payload['cause_families'][0]['canonical_cause'],
            'Client does not exist',
        )

    def test_missing_cause_analysis_is_explicitly_degraded(self):
        payload = {
            'error_count': 2,
            'trace_counts': {'session-trace': 2},
            'cause_families': [{'signature': 'legacy'}],
        }

        attached = rp._attach_authoritative_cause_families(payload, None)

        self.assertFalse(attached)
        self.assertEqual(payload['cause_evidence_status'], 'degraded')
        self.assertEqual(payload['unexplained_raw_lines'], 2)
        self.assertEqual(payload['cause_families'], [{'signature': 'legacy'}])

    def test_signal_handler_exits_nonzero(self):
        with patch.object(rp.sys, 'exit', side_effect=SystemExit) as exit_mock:
            with self.assertRaises(SystemExit):
                rp.signal_handler(signal.SIGTERM, None)

        exit_mock.assert_called_once_with(1)

    def test_alias_messages_merge_without_double_counting(self):
        unrelated = _problem('c', 'Card configuration is missing for requested product')
        similar_left = _problem(
            'similar-a', 'Payment authorization failed for customer account unavailable'
        )
        similar_right = _problem(
            'similar-b', 'Payment settlement failed for customer account unavailable'
        )

        self.assertTrue(rp._problems_represent_same_events(self.first, self.second))
        self.assertFalse(rp._problems_represent_same_events(self.first, unrelated))
        self.assertFalse(rp._problems_represent_same_events(similar_left, similar_right))
        clusters = rp._merge_peak_clusters([self.first, self.second, unrelated])
        self.assertEqual(sorted(len(cluster) for cluster in clusters), [1, 2])

        with patch.object(rp, '_build_peak_alert_payload', side_effect=_payload):
            payload = rp._build_cluster_payload(
                [self.first, self.second], {}, {}, None, None, 15
            )

        self.assertEqual(payload['error_count'], 127)
        self.assertEqual(payload['all_app_counts'], {'bl-pcb-v1': 127})
        self.assertEqual(
            payload['all_namespace_counts'],
            {'pcb-uat-01-app': 65, 'pcb-sit-01-app': 62},
        )
        self.assertEqual(payload['behavior_text'].count('\n'), 0)
        self.assertEqual(len(payload['cause_families']), 1)

    def test_shared_trace_messages_merge_without_double_counting(self):
        first = _problem('trace-a', 'First log message', count=127, traces=('trace-1',))
        second = _problem('trace-b', 'Second log message', count=254, traces=('trace-1',))

        self.assertTrue(rp._problems_share_event_traces(first, second))
        with patch.object(rp, '_build_peak_alert_payload', side_effect=_payload):
            payload = rp._build_cluster_payload(
                [first, second], {}, {}, None, None, 15
            )

        self.assertEqual(payload['error_count'], 254)
        self.assertEqual(payload['behavior_text'].count('\n'), 0)
        self.assertEqual(len(payload['cause_families']), 1)

    def test_independent_cluster_members_keep_distinct_cause_families(self):
        optimistic_lock = _problem(
            'lock',
            'HibernateOptimisticLockingFailureException while updating Card',
            count=11,
            error_class='ServiceBusinessException',
            traces=('trace-lock',),
        )
        client_missing = _problem(
            'client',
            'Client does not exist',
            count=9,
            error_class='ServiceBusinessException',
            traces=('trace-client',),
        )

        with patch.object(rp, '_build_peak_alert_payload', side_effect=_payload):
            payload = rp._build_cluster_payload(
                [optimistic_lock, client_missing], {}, {}, None, None, 15
            )

        self.assertEqual(payload['error_count'], 20)
        self.assertEqual(len(payload['cause_families']), 2)
        self.assertEqual(
            {family['canonical_cause'] for family in payload['cause_families']},
            {
                'HibernateOptimisticLockingFailureException while updating Card',
                'Client does not exist',
            },
        )

    def test_payload_exposes_structured_threshold_decision(self):
        decision = rp._threshold_evidence([
            SimpleNamespace(evidence=[Evidence(
                rule='spike_p93_cap',
                current=393,
                threshold=120,
                details={
                    'namespace': 'pcb-prod-01-app',
                    'p93_threshold': 120,
                    'percentile_level': 0.98,
                    'percentile_threshold': 120,
                    'cap_threshold': 180,
                    'triggered_by': 'p93',
                    'threshold_snapshot_id': 'snapshot-1',
                    'fingerprint_contribution': 200,
                    'detector_version': 'namespace_p93_cap_v2',
                },
            )]),
        ])[0]

        self.assertEqual(decision['observed_value'], 393)
        self.assertEqual(decision['effective_threshold'], 120)
        self.assertEqual(decision['p93_threshold'], 120)
        self.assertEqual(decision['percentile_level'], 0.98)
        self.assertEqual(decision['percentile_threshold'], 120)
        self.assertEqual(decision['cap_threshold'], 180)
        self.assertEqual(decision['threshold_snapshot_id'], 'snapshot-1')

    def test_operator_digest_falls_back_for_legacy_payload(self):
        class CaptureNotifier:
            is_enabled = lambda self: True

            def _send_email(self, subject, body, html_body):
                self.result = subject, body, html_body
                return True

        notifier = CaptureNotifier()
        alerts = [{
            'error_class': 'not_found',
            'error_count': 127,
            'peak_type': 'SPIKE',
            'is_known': True,
            'trend': 'rising',
            'all_app_counts': {'bl-pcb-v1': 127, 'bff-pcb-v1': 127},
            'all_namespace_counts': {
                'pcb-uat-01-app': 65,
                'pcb-sit-01-app': 62,
                'pcb-dev-01-app': 3,
            },
            'app_counts': {'bl-pcb-v1': 127},
            'namespace_counts': {'pcb-uat-01-app': 65},
            'root_cause_text': 'Person not found',
            'behavior_text': '1. bl-pcb-v1 (127 events): Person not found',
        }]

        sent = EmailNotifier.send_regular_phase_peak_digest(
            notifier,
            datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 27, 4, 15, tzinfo=timezone.utc),
            alerts,
            {
                'raw_window_errors': 1223,
                'detected_peak_problems': 2,
                'suppressed_alerts': 1,
                'omitted_alerts': 1,
                'max_alerts': 3,
                'affected_apps': ['bl-pcb-v1', 'bff-pcb-v1', 'feapi-pcb-v1'],
                'affected_namespaces': [
                    'pcb-uat-01-app', 'pcb-sit-01-app', 'pcb-dev-01-app', 'pcb-prod-01-app'
                ],
            },
        )

        self.assertTrue(sent)
        combined = notifier.result[1] + notifier.result[2]
        self.assertIn('WHY ALERTED', combined)
        self.assertIn('WHAT ACTUALLY FAILED', combined)
        self.assertIn('Cause families represented: 1', combined)
        self.assertIn('trace coverage unavailable', combined)
        self.assertNotIn('Behavior:', combined)
        self.assertNotIn('Clusters detected', combined)
        self.assertNotIn('cluster sent', combined.lower())

    def test_operator_digest_renders_threshold_impact_assessment_and_action(self):
        class CaptureNotifier:
            is_enabled = lambda self: True

            def _send_email(self, subject, body, html_body):
                self.result = subject, body, html_body
                return True

        notifier = CaptureNotifier()
        alert = {
            'peak_type': 'SPIKE',
            'is_known': False,
            'error_count': 200,
            'threshold_evidence': [{
                'namespace': 'pcb-prod-01-app',
                'observed_value': 393,
                'p93_threshold': 120,
                'percentile_level': 0.98,
                'percentile_threshold': 120,
                'cap_threshold': 180,
                'effective_threshold': 120,
                'triggered_by': 'p93',
                'threshold_snapshot_id': 'snapshot-1',
            }],
            'cause_families': [{
                'canonical_cause': 'Card with product instance null not found',
                'root_app': 'bl-pcb-v1',
                'operation': 'findCard',
                'outward_status': 404,
                'assessment': 'business_rejection',
                'confidence': 'medium',
                'next_action': 'Validate product-instance data.',
                'raw_error_lines': 200,
                'unique_operations': 40,
                'amplification': 5.0,
                'app_counts': {'bl-pcb-v1': 200},
                'namespace_counts': {'pcb-prod-01-app': 200},
                'representative_trace_id': 'trace-example',
                'trace_ids': [f'trace-{index}' for index in range(40)],
            }],
        }

        sent = EmailNotifier.send_regular_phase_peak_digest(
            notifier,
            datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 8, 15, tzinfo=timezone.utc),
            [alert],
            {'raw_window_errors': 393},
        )

        self.assertTrue(sent)
        _subject, body, html_body = notifier.result
        self.assertIn('393 ERROR lines vs effective threshold 120, 3.3x', body)
        self.assertIn('P98=120', body)
        self.assertIn('40 unique operations | 200 raw ERROR lines | 5.0x amplification', body)
        self.assertIn('coverage: 200 traced, 0 unsegmented ERROR lines', body)
        self.assertIn('Cause evidence: UNKNOWN; unexplained raw lines=0', body)
        self.assertIn('BUSINESS / DATA REJECTION (medium confidence)', body)
        self.assertIn('NEXT ACTION\n  Validate product-instance data.', body)
        self.assertIn('snapshot=snapshot-1', body)
        self.assertIn('WHAT ACTUALLY FAILED', html_body)

    def test_operator_digest_labels_partial_cause_coverage(self):
        class CaptureNotifier:
            is_enabled = lambda self: True

            def _send_email(self, subject, body, html_body):
                self.result = subject, body, html_body
                return True

        notifier = CaptureNotifier()
        sent = EmailNotifier.send_regular_phase_peak_digest(
            notifier,
            datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 8, 15, tzinfo=timezone.utc),
            [{
                'error_count': 10,
                'cause_evidence_status': 'partial',
                'cause_reconciliation': {
                    'status': 'partial',
                    'represented_raw_error_lines': 7,
                    'unexplained_raw_lines': 3,
                    'reason': 'trace or raw-line evidence covers only part of current scope',
                },
                'cause_families': [{
                    'canonical_cause': 'Client does not exist',
                    'root_app': 'service-a',
                    'raw_error_lines': 7,
                    'unsegmented_error_lines': 0,
                    'unique_operations': 2,
                    'amplification': 3.5,
                    'representative_trace_id': 'trace-1',
                }],
            }],
            {'raw_window_errors': 10},
        )

        assert sent
        _subject, body, html_body = notifier.result
        assert 'Cause evidence status: partial' in body
        assert 'Cause unexplained raw lines: 3' in body
        assert 'Cause evidence: PARTIAL; unexplained raw lines=3' in body
        assert 'trace or raw-line evidence covers only part of current scope' in html_body

    def test_operator_digest_escapes_log_content_in_html(self):
        class CaptureNotifier:
            is_enabled = lambda self: True

            def _send_email(self, subject, body, html_body):
                self.result = subject, body, html_body
                return True

        notifier = CaptureNotifier()
        EmailNotifier.send_regular_phase_peak_digest(
            notifier,
            datetime(2026, 8, 25, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 25, 8, 15, tzinfo=timezone.utc),
            [{
                'error_count': 1,
                'cause_families': [{
                    'canonical_cause': '<script>alert(1)</script>',
                    'root_app': 'service-a',
                    'assessment': 'unknown',
                    'confidence': 'low',
                    'raw_error_lines': 1,
                    'next_action': 'Inspect <unsafe> evidence.',
                }],
            }],
            {},
        )

        html_body = notifier.result[2]
        self.assertNotIn('<script>', html_body)
        self.assertIn('&lt;script&gt;', html_body)
        self.assertIn('&lt;unsafe&gt;', html_body)

    def test_failed_fallback_payload_does_not_receive_cooldown(self):
        payloads = [
            {'peak_key': 'peak-a', 'window_key': 'w1', 'error_count': 10},
            {'peak_key': 'peak-b', 'window_key': 'w1', 'error_count': 20},
        ]
        now_utc = datetime(2026, 7, 31, 8, 15, tzinfo=timezone.utc)

        with patch.object(rp, '_send_peak_alert_digest', return_value=False), patch.object(
            rp, '_send_peak_alert_email', side_effect=[False, True]
        ):
            delivered = rp._dispatch_peak_alerts(
                now_utc, now_utc, payloads, True, {}
            )

        with self.subTest('dispatch returns only successful payloads'):
            self.assertEqual(delivered, [payloads[1]])

        with self.subTest('dispatch exposes attempts for delivery audit'):
            self.assertEqual(delivered.delivery_outcomes, [])

        with unittest.mock.patch('tempfile.tempdir', None):
            import tempfile

            with tempfile.TemporaryDirectory() as registry_dir:
                registry = SimpleNamespace(registry_dir=registry_dir)
                rp._record_delivered_peak_alerts(registry, delivered, now_utc, 45)
                with open(rp._alert_state_path(registry), encoding='utf-8') as state_file:
                    state = json.load(state_file)

        self.assertNotIn('peak-a', state['peaks'])
        self.assertIn('peak-b', state['peaks'])

    def test_dispatch_exposes_per_destination_fallback_attempts(self):
        payload = {'peak_key': 'peak-a', 'window_key': 'w1', 'error_count': 10}
        now_utc = datetime(2026, 7, 31, 8, 15, tzinfo=timezone.utc)
        digest_result = (False, [{
            'destination': 'teams_webhook',
            'status': 'failed',
            'provider_message': 'HTTP 503',
        }])
        fallback_result = (True, [{
            'destination': 'teams_email',
            'status': 'delivered',
            'provider_message': 'SMTP accepted message',
        }])

        with patch.object(rp, '_send_peak_alert_digest', return_value=digest_result), patch.object(
            rp, '_send_peak_alert_email', return_value=fallback_result
        ):
            delivered = rp._dispatch_peak_alerts(
                now_utc, now_utc, [payload], True, {}
            )

        self.assertEqual(delivered, [payload])
        self.assertEqual(
            [
                (outcome['destination'], outcome['status'], outcome['metadata']['attempt_kind'])
                for outcome in delivered.delivery_outcomes
            ],
            [
                ('teams_webhook', 'failed', 'digest'),
                ('teams_email', 'delivered', 'individual'),
            ],
        )

    def test_alert_state_merge_preserves_existing_peak(self):
        import tempfile

        now_utc = datetime(2026, 7, 31, 8, 15, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as registry_dir:
            registry = SimpleNamespace(registry_dir=registry_dir)
            state_path = rp._alert_state_path(registry)
            state_path.write_text(json.dumps({'peaks': {'existing': {'last_sent_window': 'w0'}}}))

            rp._record_delivered_peak_alerts(
                registry,
                [{'peak_key': 'new', 'window_key': 'w1', 'error_count': 1}],
                now_utc,
                45,
            )
            state = json.loads(state_path.read_text())

        self.assertEqual(set(state['peaks']), {'existing', 'new'})


if __name__ == '__main__':
    unittest.main()