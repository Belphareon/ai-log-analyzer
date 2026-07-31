from pathlib import Path

from scripts import confluence_csv_uploader as uploader


def _write_csv(path: Path) -> None:
    path.write_text('name,count\nexample,1\n', encoding='utf-8')


def test_uploader_persists_one_outcome_per_page(tmp_path, monkeypatch):
    _write_csv(tmp_path / 'errors_table.csv')
    _write_csv(tmp_path / 'peaks_table.csv')
    monkeypatch.setattr(uploader, 'EXPORTS_DIR', tmp_path)
    monkeypatch.setattr(
        uploader,
        'upload_to_confluence',
        lambda page_id, title, html: title == 'Known Errors',
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