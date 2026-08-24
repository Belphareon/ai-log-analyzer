from scripts import recent_incidents_publisher as publisher


def test_recent_incidents_page_id_comes_from_environment(monkeypatch):
    monkeypatch.setenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', '1485297360')

    assert publisher.get_confluence_page_id() == '1485297360'


def test_recent_incidents_page_id_has_no_legacy_fallback(monkeypatch):
    monkeypatch.delenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', raising=False)

    assert publisher.get_confluence_page_id() == ''
