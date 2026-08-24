import json

from scripts import recent_incidents_publisher as publisher


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

    def open(self, request):
        self.requests.append(request)
        if request.get_method() == "GET":
            return FakeResponse({"title": "Existing daily page", "version": {"number": 1}})
        return FakeResponse({"version": {"number": 2}})


def test_recent_incidents_page_id_comes_from_environment(monkeypatch):
    monkeypatch.setenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', '1485297360')

    assert publisher.get_confluence_page_id() == '1485297360'


def test_recent_incidents_page_id_has_no_legacy_fallback(monkeypatch):
    monkeypatch.delenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', raising=False)

    assert publisher.get_confluence_page_id() == ''


def test_confluence_password_fallback_uses_bearer_auth(monkeypatch):
    monkeypatch.setattr(publisher, "CONFLUENCE_TOKEN", "cyberark-password-value")

    assert publisher.get_confluence_auth_header() == "Bearer cyberark-password-value"


def test_explicit_confluence_token_uses_bearer_auth(monkeypatch):
    monkeypatch.setattr(publisher, "CONFLUENCE_TOKEN", "personal-access-token")

    assert publisher.get_confluence_auth_header() == "Bearer personal-access-token"


def test_publisher_keeps_existing_page_title(monkeypatch):
    fake_opener = FakeOpener()
    monkeypatch.setattr(publisher, "CONFLUENCE_TOKEN", "test-token")
    monkeypatch.setenv("CONFLUENCE_RECENT_INCIDENTS_PAGE_ID", "1485297360")
    monkeypatch.setattr(publisher.urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(
        publisher.urllib.request,
        "build_opener",
        lambda *handlers: fake_opener,
    )

    assert publisher.upload_via_confluence_api("<p>content</p>") is True

    update_payload = json.loads(fake_opener.requests[1].data.decode())
    assert update_payload["title"] == "Existing daily page"
    assert update_payload["version"]["number"] == 2
