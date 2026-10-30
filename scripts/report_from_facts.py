#!/usr/bin/env python3
"""Publish two-hour trends and rolling daily reports from scoped DB facts only."""

import argparse
import csv
import hashlib
import html
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

from core.delivery_persistence import connect_from_env
from core.namespace_contract import load_monitored_namespaces
from core.run_persistence import build_query_hash
from exports.table_exporter import TableExporter


AUTHORITY_SQL = """
    WITH authority AS (
        SELECT DISTINCT ON (run_row.window_start) run_row.run_id, run_row.window_start
        FROM ailog_peak.analysis_runs run_row
        WHERE run_row.query_hash = %s AND run_row.status = 'complete'
          AND run_row.superseded_by_run_id IS NULL
          AND run_row.window_end = run_row.window_start + INTERVAL '15 minutes'
          AND run_row.window_start >= %s AND run_row.window_end <= %s
        ORDER BY run_row.window_start, run_row.completed_at DESC, run_row.run_id DESC
    )
"""
MAX_REPORT_ROWS = 100
MAX_REPORT_CELL_CHARS = 192
MAX_DAILY_REPORT_TEXT_CHARS = 128 * 1024


def report_periods(now, daily_hour=7):
    if now.tzinfo is None or not 0 <= daily_hour <= 23:
        raise ValueError('report time must be aware and daily hour between 0 and 23')
    now = now.astimezone(timezone.utc)
    trend_end = now.replace(hour=(now.hour // 2) * 2, minute=0, second=0, microsecond=0)
    daily_end = now.replace(hour=daily_hour, minute=0, second=0, microsecond=0)
    if daily_end > now:
        daily_end -= timedelta(days=1)
    return trend_end, daily_end


def coverage_label(complete_windows, end, hours):
    expected = hours * 4
    observed = sum(end - timedelta(hours=hours) <= window < end for window in complete_windows)
    return observed == expected, f'{observed}/{expected} complete 15-minute windows'


def trend_label(current, previous, complete):
    if not complete:
        return 'N/A (incomplete coverage)'
    if current == previous:
        return 'stable (0%)'
    if not previous:
        return f'new (+{current} ERROR lines)'
    change = (current - previous) / previous * 100
    return f'{"rising" if change > 0 else "falling"} ({change:+.1f}%)'


def load_snapshot(connection, query_hash, namespaces, end):
    start = end - timedelta(days=7)
    parameters = (query_hash, start, end)
    with connection.cursor() as cursor:
        cursor.execute(AUTHORITY_SQL + """
            SELECT fact.window_start, SUM(fact.error_count)
            FROM ailog_peak.namespace_error_counts fact
            JOIN authority ON authority.run_id = fact.run_id AND authority.window_start = fact.window_start
            WHERE fact.namespace = ANY(%s)
            GROUP BY fact.window_start HAVING COUNT(DISTINCT fact.namespace) = %s
        """, (*parameters, namespaces, len(namespaces)))
        namespace_counts = dict(cursor.fetchall())
        cursor.execute(AUTHORITY_SQL + """
            SELECT fact.fingerprint, fact.namespace, fact.application, fact.error_type, fact.category,
                   MIN(fact.first_event_at), MAX(fact.last_event_at), MAX(fact.sample_message),
                   COALESCE(SUM(fact.error_count) FILTER (WHERE fact.window_start >= %s), 0),
                   COALESCE(SUM(fact.error_count) FILTER (WHERE fact.window_start >= %s AND fact.window_start < %s), 0),
                   COALESCE(SUM(fact.error_count) FILTER (WHERE fact.window_start >= %s), 0),
                   COALESCE(SUM(fact.error_count) FILTER (WHERE fact.window_start >= %s AND fact.window_start < %s), 0),
                   SUM(fact.error_count)
            FROM ailog_peak.error_kind_counts fact
            JOIN authority ON authority.run_id = fact.run_id AND authority.window_start = fact.window_start
            WHERE fact.namespace = ANY(%s)
            GROUP BY fact.fingerprint, fact.namespace, fact.application, fact.error_type, fact.category
        """, (*parameters, end - timedelta(hours=2), end - timedelta(hours=4), end - timedelta(hours=2),
              end - timedelta(hours=24), end - timedelta(hours=48), end - timedelta(hours=24), namespaces))
        error_facts = cursor.fetchall()
        cursor.execute(
            'SELECT problem_key, fingerprints, payload FROM ailog_peak.report_knowledge WHERE query_hash = %s',
            (query_hash,),
        )
        knowledge = cursor.fetchall()
        cursor.execute(AUTHORITY_SQL + """
            SELECT fact.cause_signature, fact.canonical_cause, fact.root_application,
                   fact.operation, fact.outward_status, fact.assessment,
                   CASE MAX(CASE fact.confidence WHEN 'low' THEN 3 WHEN 'medium' THEN 2 ELSE 1 END)
                       WHEN 3 THEN 'low' WHEN 2 THEN 'medium' ELSE 'high' END,
                   SUM(fact.raw_error_lines), SUM(fact.traced_error_lines),
                   SUM(fact.unsegmented_error_lines),
                   CASE WHEN COUNT(fact.unique_operations) = COUNT(*) THEN SUM(fact.unique_operations) END,
                   MIN(NULLIF(fact.representative_trace_id, '')), MIN(fact.next_action),
                   MIN(fact.window_start), MAX(fact.window_start)
            FROM ailog_peak.cause_family_facts fact
            JOIN authority ON authority.run_id = fact.run_id AND authority.window_start = fact.window_start
            WHERE fact.window_start >= %s
            GROUP BY fact.cause_signature, fact.canonical_cause, fact.root_application,
                     fact.operation, fact.outward_status, fact.assessment
            ORDER BY SUM(fact.raw_error_lines) DESC, fact.cause_signature
        """, (*parameters, end - timedelta(hours=24)))
        family_facts = cursor.fetchall()
        cursor.execute("""
            SELECT DISTINCT ON (decision.window_start_utc, decision.signal_namespace)
                   decision.window_start_utc, decision.signal_namespace,
                   decision.namespace_raw_lines, decision.effective_threshold,
                   decision.profile_status, decision.threshold_samples,
                   decision.threshold_snapshot_id, decision.diagnosis_status
            FROM ailog_peak.namespace_peak_decisions decision
            JOIN ailog_peak.analysis_runs run_row ON run_row.run_id = decision.run_id
            WHERE run_row.query_hash = %s AND run_row.status IN ('complete', 'superseded')
              AND decision.stream_key = 'live' AND decision.is_peak AND decision.is_evaluated
              AND decision.window_start_utc >= %s AND decision.window_start_utc < %s
              AND decision.signal_namespace = ANY(%s)
            ORDER BY decision.window_start_utc, decision.signal_namespace, run_row.completed_at DESC
        """, (query_hash, end - timedelta(hours=24), end, namespaces))
        peak_facts = cursor.fetchall()
    return {'end': end, 'namespace_counts': namespace_counts, 'error_facts': error_facts,
            'knowledge': knowledge, 'family_facts': family_facts, 'peak_facts': peak_facts}


def error_rows(snapshot):
    exporter = TableExporter(None)
    index = {fingerprint: (key, payload)
             for key, fingerprints, payload in snapshot['knowledge'] for fingerprint in fingerprints}
    complete = set(snapshot['namespace_counts'])
    end = snapshot['end']
    short_complete = coverage_label(complete, end, 4)[0]
    long_complete = coverage_label(complete, end, 48)[0]
    grouped = {}
    for fact in snapshot['error_facts']:
        fingerprint, namespace, application, error_type, category, first, last, sample, current_2h, previous_2h, current_24h, previous_24h, total = fact
        key, metadata = index.get(fingerprint, (f'{category}:{error_type}:{fingerprint}', {}))
        cause = metadata.get('root_cause') or metadata.get('description') or sample or error_type
        row = grouped.setdefault(key, {
            'cause': exporter._shorten(exporter._normalize_operator_text(cause), 220),
            'problem_id': metadata.get('id', fingerprint), 'problem_key': key,
            'status': metadata.get('status', 'OPEN'), 'jira': metadata.get('jira') or '',
            'notes': metadata.get('notes') or '', 'first_seen': first, 'last_seen': last,
            'error_lines_2h': 0, 'previous_error_lines_2h': 0,
            'error_lines_24h': 0, 'previous_error_lines_24h': 0, 'error_lines_7d': 0,
            'affected_namespaces': set(), 'affected_apps': set(),
        })
        row['first_seen'] = min(row['first_seen'], first)
        row['last_seen'] = max(row['last_seen'], last)
        for field, value in zip(
            ('error_lines_2h', 'previous_error_lines_2h', 'error_lines_24h', 'previous_error_lines_24h', 'error_lines_7d'),
            (current_2h, previous_2h, current_24h, previous_24h, total),
        ):
            row[field] += int(value)
        row['affected_namespaces'].add(namespace)
        row['affected_apps'].add(application)
    for row in grouped.values():
        row['trend_2h'] = trend_label(row['error_lines_2h'], row['previous_error_lines_2h'], short_complete)
        row['trend_24h'] = trend_label(row['error_lines_24h'], row['previous_error_lines_24h'], long_complete)
        row['coverage_2h'] = coverage_label(complete, end, 2)[1]
        row['coverage_24h'] = coverage_label(complete, end, 24)[1]
        row['metric_scope'] = 'Authoritative ERROR lines; trends compare adjacent equal periods; not unique operations'
        for field in ('affected_namespaces', 'affected_apps'):
            row[field] = '\n'.join(sorted(row[field]))
        for field in ('first_seen', 'last_seen'):
            row[field] = row[field].isoformat()
    return sorted(grouped.values(), key=lambda row: (-row['error_lines_2h'], -row['error_lines_24h'], row['problem_key']))


def family_rows(snapshot):
    fields = ('cause_signature', 'cause', 'root_application', 'operation', 'outward_status',
              'assessment', 'confidence', 'raw_error_lines', 'traced_error_lines',
              'unsegmented_error_lines', 'operation_occurrences', 'representative_trace',
              'next_action', 'first_window', 'last_window')
    return [dict(zip(fields, fact)) for fact in snapshot['family_facts']]


def peak_rows(snapshot):
    fields = ('window_start', 'namespace', 'detected_error_lines', 'effective_threshold',
              'profile_status', 'threshold_samples', 'threshold_snapshot_id', 'diagnosis_status')
    rows = [dict(zip(fields, fact)) for fact in snapshot['peak_facts']]
    for row in rows:
        row['metric_scope'] = 'Historical detector decision; not corrected volume or proof of notification delivery'
    return rows


def peak_catalog_rows(snapshot):
    from core.problem_registry import PeakEntry, ProblemEntry

    problems, peaks = {}, {}
    for key, _fingerprints, payload in snapshot['knowledge']:
        if payload.get('_report_kind') == 'peak':
            peaks[key] = PeakEntry.from_dict(payload)
        else:
            problems[key] = ProblemEntry.from_dict(payload)
    registry = SimpleNamespace(problems=problems, peaks=peaks)
    return [asdict(row) for row in TableExporter(registry).get_peaks_rows()]


def render_table(path, title, rows, fields, snapshot, *, heading_level=1):
    from confluence_csv_uploader import csv_to_html_table

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {key: '' if row.get(key) is None else row.get(key, '') for key in fields}
            for row in rows
        )
    complete, coverage = coverage_label(set(snapshot['namespace_counts']), snapshot['end'], 24)
    header = f'<h{heading_level}>{html.escape(title)}</h{heading_level}>'
    header += f'<p>As of {snapshot["end"].isoformat()}; {coverage}. '
    header += 'Complete data.</p>' if complete else 'INCOMPLETE DATA: missing windows are not zero.</p>'
    visible_rows = min(len(rows), MAX_REPORT_ROWS)
    if visible_rows < len(rows):
        header += (
            f'<p>Showing {visible_rows} of {len(rows)} rows; remaining rows are omitted from this page. '
            'Underlying database facts are unchanged.</p>'
        )
    has_long_cells = any(
        value is not None and len(str(value)) > MAX_REPORT_CELL_CHARS
        for row in rows[:MAX_REPORT_ROWS]
        for value in (row.get(field) for field in fields)
    )
    if has_long_cells:
        header += (
            f'<p>Cell values longer than {MAX_REPORT_CELL_CHARS} characters are truncated on this page.</p>'
        )
    return header + csv_to_html_table(
        path, max_rows=MAX_REPORT_ROWS, max_cell_chars=MAX_REPORT_CELL_CHARS,
    )


def bound_daily_report_text(text):
    if len(text) <= MAX_DAILY_REPORT_TEXT_CHARS:
        return text
    marker = '\n[Report text truncated to fit Confluence request limits.]'
    return text[:MAX_DAILY_REPORT_TEXT_CHARS - len(marker)] + marker


def daily_text(snapshot):
    complete, coverage = coverage_label(set(snapshot['namespace_counts']), snapshot['end'], 24)
    total = sum(count for window, count in snapshot['namespace_counts'].items()
                if window >= snapshot['end'] - timedelta(hours=24))
    families = family_rows(snapshot)
    family_total = sum(int(row['raw_error_lines']) for row in families)
    lines = [
        'Recent Daily Incidents: last 24 hours',
        f'UTC interval: [{(snapshot["end"] - timedelta(hours=24)).isoformat()}, {snapshot["end"].isoformat()})',
        f'Coverage: {coverage}; {"complete" if complete else "INCOMPLETE, not proof of quiet operation"}',
        f'Observed ERROR lines in complete windows: {total}',
        f'Diagnostic coverage: {family_total}/{total} ERROR lines',
        'Operation occurrences are summed per 15-minute window, not deduplicated across the day.',
        'Representative traces are historical examples; full trace context coverage is not persisted.',
        '',
    ]
    if family_total != total:
        lines.append('INCOMPLETE DIAGNOSTICS: cause facts do not reconcile to observed volume.')
    for row in families[:20]:
        operations = row['operation_occurrences'] if row['operation_occurrences'] is not None else 'N/A'
        lines.extend([
            f'{row["cause"]} [{row["assessment"]}; confidence={row["confidence"]}]',
            f'  Root app: {row["root_application"]}; operation: {row["operation"]}; status: {row["outward_status"]}',
            f'  ERROR lines: {row["raw_error_lines"]}; operation occurrences: {operations}',
            f'  Representative trace: {row["representative_trace"] or "N/A"}',
            f'  Next action: {row["next_action"]}',
            '',
        ])
    if len(families) > 20:
        included = min(len(families), MAX_REPORT_ROWS) - 20
        lines.append(f'{included} additional cause families are included in the Confluence table.')
    if len(families) > MAX_REPORT_ROWS:
        lines.append(
            f'{len(families) - MAX_REPORT_ROWS} additional cause families are omitted from the page; '
            'complete data remain in the database and CSV export.'
        )
    return '\n'.join(lines)


def publish_once(connection, query_hash, kind, end, destination, sender):
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT 1 FROM ailog_peak.report_publications WHERE query_hash=%s AND report_kind=%s AND period_end=%s AND destination=%s',
            (query_hash, kind, end, destination),
        )
        delivered = cursor.fetchone() is not None
    connection.commit()
    if delivered:
        return True
    if not sender():
        return False
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO ailog_peak.report_publications (query_hash, report_kind, period_end, destination)
            VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING
        """, (query_hash, kind, end, destination))
    connection.commit()
    return True


def run_reports(*, connection_factory=connect_from_env, now=None, output_dir=None, dry_run=False):
    from confluence_csv_uploader import upload_to_confluence
    from core.email_notifier import EmailNotifier

    now = now or datetime.now(timezone.utc)
    namespaces = load_monitored_namespaces(strict=True)
    source_index = os.environ['ES_INDEX']
    query_hash = build_query_hash(source_index, namespaces)
    trend_end, daily_end = report_periods(now, int(os.getenv('DAILY_REPORT_HOUR_UTC') or '7'))
    output = Path(output_dir or os.getenv('REPORT_OUTPUT_DIR', '/tmp/log-analyzer-reports'))
    writer = connection_factory()
    reader = None
    try:
        with writer.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(hashtextextended(%s, 0))', (f'reports:{query_hash}',))
            acquired = cursor.fetchone()[0]
        writer.commit()
        if not acquired:
            return {'status': 'busy'}
        reader = connection_factory()
        reader.set_session(isolation_level='REPEATABLE READ', readonly=True)
        trends = load_snapshot(reader, query_hash, namespaces, trend_end)
        daily = load_snapshot(reader, query_hash, namespaces, daily_end)
        reader.rollback()
        daily_complete = (
            coverage_label(set(daily['namespace_counts']), daily_end, 24)[0]
            and sum(int(row['raw_error_lines']) for row in family_rows(daily)) == sum(
                count for window, count in daily['namespace_counts'].items()
                if window >= daily_end - timedelta(hours=24)
            )
        )
        rows = error_rows(trends)
        daily_body = daily_text(daily)
        specs = [
            ('trends', trend_end, 'CONFLUENCE_KNOWN_ERRORS_PAGE_ID', 'Known Errors: Trends', rows,
             ['cause', 'trend_2h', 'trend_24h', 'error_lines_2h', 'previous_error_lines_2h',
              'error_lines_24h', 'previous_error_lines_24h', 'error_lines_7d', 'coverage_2h', 'coverage_24h',
              'affected_namespaces', 'affected_apps', 'status', 'jira', 'notes', 'last_seen', 'problem_id', 'metric_scope'], trends),
            ('peaks', daily_end, 'CONFLUENCE_KNOWN_PEAKS_PAGE_ID', 'Known Peaks: Last 24 Hours', peak_rows(daily),
             ['window_start', 'namespace', 'detected_error_lines', 'effective_threshold', 'profile_status',
              'threshold_samples', 'threshold_snapshot_id', 'diagnosis_status', 'metric_scope'], daily),
            ('daily', daily_end, 'CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', 'Recent Daily Incidents: Last 24 Hours', family_rows(daily),
             ['cause', 'assessment', 'confidence', 'raw_error_lines', 'operation_occurrences', 'root_application',
              'operation', 'outward_status', 'representative_trace', 'next_action', 'first_window', 'last_window'], daily),
        ]
        outcomes = []
        for kind, end, page_env, title, table_rows, fields, snapshot in specs:
            content = render_table(output / f'{kind}.csv', title, table_rows, fields, snapshot)
            if kind == 'peaks':
                catalog = peak_catalog_rows(snapshot)
                catalog_fields = ['peak_id', 'peak_type', 'diagnosis', 'root_cause', 'behavior',
                                  'max_observed_errors', 'total_errors', 'occurrence_count', 'periodicity',
                                  'affected_namespaces', 'affected_apps', 'status', 'jira', 'notes', 'metric_scope']
                catalog_path = output / 'peaks-catalog.csv'
                content += ('<p>Registry metadata at report time. '
                            'Historical counts and patterns are not limited to this daily interval; '
                            'they are not current-slot thresholds or notification evidence.</p>')
                content += render_table(
                    catalog_path, 'Historical Peak Catalog', catalog, catalog_fields, snapshot,
                    heading_level=2,
                )
            if kind == 'daily':
                content = '<pre>' + html.escape(bound_daily_report_text(daily_body)) + '</pre>' + content
            (output / f'{kind}.html').write_text(content, encoding='utf-8')
            if dry_run:
                continue
            page_id = os.getenv(page_env, '').strip()
            if not page_id or page_id.startswith('<'):
                raise RuntimeError(f'Missing configured {page_env}')
            destination = f'confluence:{os.getenv("CONFLUENCE_URL", "https://wiki.kb.cz")}:{page_id}'
            period_complete = coverage_label(set(snapshot['namespace_counts']), end, 24)[0]
            if not period_complete or (kind == 'daily' and not daily_complete):
                revision = hashlib.sha256(content.encode()).hexdigest()
                destination += f':partial:{revision}'
            success = publish_once(writer, query_hash, kind, end, destination,
                                   lambda page_id=page_id, content=content: upload_to_confluence(page_id, content))
            outcomes.append({'kind': kind, 'destination': page_env, 'success': success})
        notifier = EmailNotifier()
        if not dry_run and notifier.is_enabled() and daily_complete:
            channels = []
            if notifier.teams_email:
                channels.append(('teams_email', notifier.teams_email, notifier._send_email_smtp))
            if notifier.webhook_url:
                channels.append(('teams_webhook', notifier.webhook_url, notifier._send_webhook))
            for name, address, sender in channels:
                destination = f'{name}:{hashlib.sha256(address.encode()).hexdigest()}'
                success = publish_once(writer, query_hash, 'daily', daily_end, destination,
                                       lambda sender=sender: sender('[Log Analyzer] Daily Report: Last 24 Hours', daily_body))
                outcomes.append({'kind': 'daily', 'destination': name, 'success': success})
        return {'status': 'success' if all(item['success'] for item in outcomes) else 'error',
            'daily_complete': daily_complete,
                'trend_end': trend_end.isoformat(), 'daily_end': daily_end.isoformat(), 'outcomes': outcomes}
    finally:
        if reader is not None:
            reader.close()
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        result = run_reports(output_dir=args.output, dry_run=args.dry_run)
        print(json.dumps(result, default=str), flush=True)
        return 0 if result['status'] in {'success', 'busy'} else 1
    except Exception as error:
        print(f'Report failed: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())