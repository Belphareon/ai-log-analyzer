from unittest.mock import MagicMock

from scripts.core.email_notifier import EmailNotifier


def test_webhook_exception_never_exposes_webhook_token(monkeypatch, capsys):
    secret_url = 'https://teams.invalid/webhook/secret-token-value'
    monkeypatch.setenv('TEAMS_ENABLED', 'true')
    monkeypatch.setenv('TEAMS_WEBHOOK_URL', secret_url)
    monkeypatch.delenv('TEAMS_EMAIL', raising=False)
    notifier = EmailNotifier()

    from requests.exceptions import ConnectionError

    monkeypatch.setattr(
        'scripts.core.email_notifier.requests.post',
        MagicMock(side_effect=ConnectionError(f'Failed to connect to {secret_url}')),
    )

    assert notifier._send_email('subject', 'body') is False
    captured = capsys.readouterr().out
    outcomes = notifier.get_last_delivery_results()

    assert secret_url not in captured
    assert 'secret-token-value' not in captured
    assert outcomes[0]['provider_message'] == 'ConnectionError'
    assert secret_url not in outcomes[0]['provider_message']


def test_partial_channel_success_returns_true_and_preserves_both_outcomes(monkeypatch):
    monkeypatch.setenv('TEAMS_ENABLED', 'true')
    monkeypatch.setenv('TEAMS_WEBHOOK_URL', 'https://teams.invalid/webhook')
    monkeypatch.setenv('TEAMS_EMAIL', 'channel@example.invalid')
    notifier = EmailNotifier()

    response = MagicMock(status_code=503)
    response.raise_for_status.side_effect = notifier_module_error(response)
    monkeypatch.setattr('scripts.core.email_notifier.requests.post', MagicMock(return_value=response))

    smtp = MagicMock()
    smtp.__enter__.return_value.send_message.return_value = {}
    monkeypatch.setattr('scripts.core.email_notifier.smtplib.SMTP', MagicMock(return_value=smtp))

    assert notifier._send_email('subject', 'body') is True
    assert [
        (result['destination'], result['status'])
        for result in notifier.get_last_delivery_results()
    ] == [
        ('teams_webhook', 'failed'),
        ('teams_email', 'delivered'),
    ]


def notifier_module_error(response):
    from requests.exceptions import HTTPError

    return HTTPError('service unavailable', response=response)