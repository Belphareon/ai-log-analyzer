import importlib
import json
from pathlib import Path

from scripts import confluence_csv_uploader as uploader


def test_confluence_password_fallback_uses_bearer_auth(monkeypatch):
    monkeypatch.delenv('CONFLUENCE_TOKEN', raising=False)
    monkeypatch.setenv('CONFLUENCE_PASSWORD', 'cyberark-password-value')
    reloaded_uploader = importlib.reload(uploader)

    assert reloaded_uploader.get_confluence_auth_header() == 'Bearer cyberark-password-value'


def test_explicit_confluence_token_uses_bearer_auth(monkeypatch):
    monkeypatch.setenv('CONFLUENCE_TOKEN', 'personal-access-token')
    monkeypatch.setenv('CONFLUENCE_PASSWORD', 'cyberark-password-value')
    reloaded_uploader = importlib.reload(uploader)

    assert reloaded_uploader.get_confluence_auth_header() == 'Bearer personal-access-token'

def _write_csv(path: Path) -> None:
    path.write_text('name,count\nexample,1\n', encoding='utf-8')


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeOpener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if request.get_method() == 'GET':
            return FakeResponse({'title': 'Existing page title', 'version': {'number': 41}})
        return FakeResponse({'version': {'number': 42}})


def test_uploader_keeps_existing_page_title(monkeypatch, capsys):
    fake_opener = FakeOpener()
    monkeypatch.setattr(uploader, 'CONFLUENCE_TOKEN', 'test-token')
    monkeypatch.setattr(uploader.urllib.request, 'getproxies', lambda: {})
    monkeypatch.setattr(uploader.urllib.request, 'build_opener', lambda *handlers: fake_opener)

    assert uploader.upload_to_confluence('123', '<p>content</p>') is True

    update_payload = json.loads(fake_opener.requests[1].data.decode())
    assert update_payload['title'] == 'Existing page title'
    assert update_payload['version']['number'] == 42
    prepared = json.loads(capsys.readouterr().out.splitlines()[0])
    assert prepared['event'] == 'confluence_request_prepared'
    assert prepared['request_bytes'] == len(fake_opener.requests[1].data)
    assert prepared['max_request_bytes'] == uploader.MAX_CONFLUENCE_REQUEST_BYTES


def test_uploader_rejects_oversized_request_before_put(monkeypatch):
    fake_opener = FakeOpener()
    monkeypatch.setattr(uploader, 'CONFLUENCE_TOKEN', 'test-token')
    monkeypatch.setattr(uploader.urllib.request, 'getproxies', lambda: {})
    monkeypatch.setattr(uploader.urllib.request, 'build_opener', lambda *handlers: fake_opener)

    assert not uploader.upload_to_confluence(
        '123', 'x' * (uploader.MAX_CONFLUENCE_REQUEST_BYTES + 1),
    )
    assert [request.get_method() for request in fake_opener.requests] == ['GET']


def test_uploader_measures_serialized_request_not_html_character_count(monkeypatch):
    fake_opener = FakeOpener()
    monkeypatch.setattr(uploader, 'CONFLUENCE_TOKEN', 'test-token')
    monkeypatch.setattr(uploader, 'MAX_CONFLUENCE_REQUEST_BYTES', 300)
    monkeypatch.setattr(uploader.urllib.request, 'getproxies', lambda: {})
    monkeypatch.setattr(uploader.urllib.request, 'build_opener', lambda *handlers: fake_opener)
    content = '\U0001f4a5' * 100

    assert len(content) < uploader.MAX_CONFLUENCE_REQUEST_BYTES
    assert not uploader.upload_to_confluence('123', content)
    assert [request.get_method() for request in fake_opener.requests] == ['GET']


def test_uploader_persists_one_outcome_per_page(tmp_path, monkeypatch):
    _write_csv(tmp_path / 'errors_table.csv')
    _write_csv(tmp_path / 'peaks_table.csv')
    monkeypatch.setattr(uploader, 'EXPORTS_DIR', tmp_path)
    monkeypatch.setattr(
        uploader,
        'upload_to_confluence',
        lambda page_id, html: page_id == uploader.CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
    )
    captured = {}

    def capture_persistence(connection_factory, outcomes, **context):
        captured['outcomes'] = outcomes
        captured['context'] = context
        return len(outcomes)

    monkeypatch.setattr(uploader, 'persist_notification_deliveries', capture_persistence)

    assert uploader.main() is False
    assert [
        (outcome['destination'], outcome['status'])
        for outcome in captured['outcomes']
    ] == [
        ('confluence_known_errors', 'delivered'),
        ('confluence_known_peaks', 'failed'),
    ]
    assert captured['context']['notification_type'] == 'backfill_registry_publication'


def test_missing_expected_csv_files_are_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader, 'EXPORTS_DIR', tmp_path)
    captured = {}

    def capture_persistence(connection_factory, outcomes, **context):
        captured['outcomes'] = outcomes
        return len(outcomes)

    monkeypatch.setattr(uploader, 'persist_notification_deliveries', capture_persistence)

    assert uploader.main() is False
    assert len(captured['outcomes']) == 2
    assert {outcome['status'] for outcome in captured['outcomes']} == {'failed'}