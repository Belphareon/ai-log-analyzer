from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from scripts.core import delivery_persistence


@pytest.mark.parametrize(
    ('statuses', 'expected_status'),
    [
        (['delivered'], 'complete'),
        (['failed'], 'failed'),
        (['failed', 'delivered'], 'partial'),
        (['suppressed'], 'suppressed'),
        (['skipped'], 'skipped'),
    ],
)
def test_summarizes_outcomes_per_payload(statuses, expected_status):
    outcomes = [
        {
            'dedup_key': 'payload-a',
            'destination': f'destination-{index}',
            'status': status,
        }
        for index, status in enumerate(statuses)
    ]

    summary = delivery_persistence.summarize_delivery_outcomes(outcomes)

    assert summary['status'] == expected_status
    assert summary['failed_dedup_keys'] == (
        ['payload-a'] if expected_status == 'failed' else []
    )


def test_any_payload_without_delivery_makes_batch_failed():
    outcomes = [
        {'dedup_key': 'payload-a', 'destination': 'email', 'status': 'delivered'},
        {'dedup_key': 'payload-b', 'destination': 'email', 'status': 'failed'},
    ]

    summary = delivery_persistence.summarize_delivery_outcomes(outcomes)

    assert summary['status'] == 'failed'
    assert summary['failed_dedup_keys'] == ['payload-b']


def test_persists_one_immutable_row_per_destination(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    captured = {}

    def capture_values(actual_cursor, statement, rows, page_size):
        captured['cursor'] = actual_cursor
        captured['statement'] = statement
        captured['rows'] = rows
        captured['page_size'] = page_size

    monkeypatch.setattr(delivery_persistence, 'execute_values', capture_values)
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)

    inserted = delivery_persistence.persist_notification_deliveries(
        lambda: connection,
        [
            {
                'dedup_key': 'peak-a:20260731T0800',
                'destination': 'teams_webhook',
                'status': 'failed',
                'provider_message': 'HTTP 503',
                'metadata': {'attempt_kind': 'digest'},
            },
            {
                'dedup_key': 'peak-a:20260731T0800',
                'destination': 'teams_email',
                'status': 'delivered',
            },
        ],
        notification_type='regular_peak',
        run_id='regular-1',
        window_start=window_start,
    )

    assert inserted == 2
    assert captured['cursor'] is cursor
    assert len(captured['rows']) == 2
    assert [row[5:7] for row in captured['rows']] == [
        ('teams_webhook', 'failed'),
        ('teams_email', 'delivered'),
    ]
    assert all(row[1] == 'regular-1' and row[2] == window_start for row in captured['rows'])
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize('field', ['dedup_key', 'destination'])
def test_rejects_missing_delivery_identity_without_connecting(field):
    delivery = {
        'dedup_key': 'peak-a',
        'destination': 'teams_email',
        'status': 'delivered',
    }
    delivery[field] = ''
    connection_factory = MagicMock()

    with pytest.raises(ValueError, match='dedup_key and destination'):
        delivery_persistence.persist_notification_deliveries(
            connection_factory,
            [delivery],
            notification_type='regular_peak',
        )

    connection_factory.assert_not_called()