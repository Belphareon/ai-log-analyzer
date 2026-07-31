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
from core.email_notifier import EmailNotifier  # noqa: E402


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

    def test_digest_reports_unique_apps_and_namespaces_without_clusters(self):
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
        self.assertIn('Applications affected: 3', combined)
        self.assertIn('Namespaces affected: 4', combined)
        self.assertNotIn('Clusters detected', combined)
        self.assertNotIn('cluster sent', combined.lower())

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