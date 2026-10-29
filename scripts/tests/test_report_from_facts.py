"""DB report semantics independent of collection, PVC, and external services."""

from datetime import datetime, timedelta, timezone

import report_from_facts as report


def _snapshot(end, hours=48):
    return {
        'end': end,
        'namespace_counts': {end - timedelta(minutes=15 * index): 0 for index in range(1, hours * 4 + 1)},
        'knowledge': [], 'error_facts': [], 'family_facts': [], 'peak_facts': [],
    }


def test_peak_catalog_keeps_metadata_without_making_maximum_a_total():
    snapshot = {'knowledge': [('peak:test', [], {
        '_report_kind': 'peak', 'id': 'PK-1', 'problem_key': 'test:flow:SPIKE',
        'peak_type': 'SPIKE', 'max_value': 900, 'occurrences': 4,
        'first_seen': '2026-10-29T04:00:00+00:00', 'last_seen': '2026-10-30T06:00:00+00:00',
        'root_cause': 'Backend unavailable', 'jira': 'OPS-123', 'notes': 'Owner investigating',
    })]}
    rows = report.peak_catalog_rows(snapshot)
    assert rows[0]['jira'] == 'OPS-123'
    assert rows[0]['notes'] == 'Owner investigating'
    assert rows[0]['total_errors'] is None
    assert rows[0]['max_observed_errors'] == 900


def test_report_cadence_is_stable_across_retries_and_odd_daily_hour():
    now = datetime(2026, 10, 29, 8, 10, tzinfo=timezone.utc)
    assert report.report_periods(now) == (now.replace(minute=0), now.replace(hour=7, minute=0))
    assert report.report_periods(now + timedelta(minutes=50)) == report.report_periods(now)
    before_daily = now.replace(hour=6)
    assert report.report_periods(before_daily)[1] == now.replace(day=28, hour=7, minute=0)


def test_trends_include_observed_zero_windows_and_preserve_missing_coverage():
    end = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(end)
    snapshot['error_facts'] = [
        ('fp-a', 'ns-a', 'cards', 'RuntimeError', 'business', end - timedelta(hours=3),
         end - timedelta(minutes=15), 'Client missing', 20, 10, 20, 40, 100),
    ]
    row = report.error_rows(snapshot)[0]
    assert row['trend_2h'] == 'rising (+100.0%)'
    assert row['trend_24h'] == 'falling (-50.0%)'
    assert row['error_lines_2h'] == 20
    assert row['coverage_2h'] == '8/8 complete 15-minute windows'

    snapshot['namespace_counts'].pop(end - timedelta(hours=3))
    row = report.error_rows(snapshot)[0]
    assert row['trend_2h'] == 'N/A (incomplete coverage)'
    assert report.trend_label(0, 0, True) == 'stable (0%)'
    assert report.trend_label(10, 0, True) == 'new (+10 ERROR lines)'


def test_catalog_metadata_and_raw_counts_survive_db_aggregation():
    end = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(end)
    snapshot['knowledge'] = [('business:repair:missing', ['fp-a', 'fp-b'], {
        'id': 'KP-1', 'root_cause': 'Client missing', 'status': 'ACKNOWLEDGED',
        'jira': 'KB-1', 'notes': 'Owner: cards',
    })]
    snapshot['error_facts'] = [
        (fingerprint, namespace, app, 'RuntimeError', 'business', end - timedelta(hours=3),
         end - timedelta(minutes=15), 'wrapper message', 20, 10, 20, 40, 100)
        for fingerprint, namespace, app in [('fp-a', 'ns-a', 'cards'), ('fp-b', 'ns-b', 'gateway')]
    ]
    rows = report.error_rows(snapshot)
    assert len(rows) == 1
    assert rows[0]['cause'] == 'Client missing'
    assert rows[0]['error_lines_2h'] == 40
    assert rows[0]['jira'] == 'KB-1'
    assert rows[0]['notes'] == 'Owner: cards'
    assert rows[0]['affected_namespaces'] == 'ns-a\nns-b'


def test_daily_report_marks_missing_diagnostics_instead_of_claiming_no_incidents():
    end = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
    snapshot = _snapshot(end, hours=24)
    snapshot['namespace_counts'][end - timedelta(minutes=15)] = 10
    text = report.daily_text(snapshot)
    assert '96/96' in text
    assert 'INCOMPLETE DIAGNOSTICS' in text
    assert '0/10 ERROR lines' in text
    assert 'not deduplicated across the day' in text


def test_rendered_report_escapes_log_content_and_exposes_owner_metadata(tmp_path):
    end = datetime(2026, 10, 29, 8, tzinfo=timezone.utc)
    content = report.render_table(tmp_path / 'report.csv', 'Known Errors', [{
        'cause': '<script>bad</script>', 'jira': 'KB-1', 'notes': 'Owner: cards',
    }], ['cause', 'jira', 'notes'], _snapshot(end))
    assert '<script>' not in content
    assert '&lt;script&gt;' in content
    assert 'KB-1' in content
    assert 'Owner: cards' in content