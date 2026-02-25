import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

repo = Path('/home/jvsete/git/ai-log-analyzer')
out = repo / 'ai-data' / 'peaks_24h_clear_table.md'
out_main = repo / 'ai-data' / 'active_peaks_24h_investigation.md'
src_json = repo / 'ai-data' / 'active_peaks_24h_investigation.json'
raw_cache_json = repo / 'ai-data' / 'source_logs_24h_cache.json'

sys.path.insert(0, str(repo / 'scripts'))
sys.path.insert(0, str(repo))

load_dotenv(repo / '.env')
load_dotenv(repo / 'config/.env')

from scripts.regular_phase_v6 import get_db_connection, set_db_role


now = datetime.now(timezone.utc)
local_tz = ZoneInfo(os.getenv('REPORT_TIMEZONE', 'Europe/Prague'))
payload = json.loads(src_json.read_text(encoding='utf-8'))
window_start = payload.get('window_start_utc', '')
window_end = payload.get('window_end_utc', '')
peaks = payload.get('peaks', [])

time_re = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})->(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')
ns_time_re = re.compile(r'([^\[]+?)\s*\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})->(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')


def parse_utc_z(ts: str) -> datetime:
    return datetime.strptime(ts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def parse_minute(ts: str) -> datetime:
    return datetime.strptime(ts, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)


def parse_windows(text: str):
    if not text:
        return []
    return [(m.group(1), m.group(2)) for m in time_re.finditer(text)]


def parse_ns_windows(text: str):
    if not text or text.strip() == '-':
        return []
    windows = []
    for part in text.split(';'):
        part = part.strip()
        if not part:
            continue
        m = ns_time_re.search(part)
        if not m:
            continue
        ns = m.group(1).strip()
        frm = m.group(2)
        to = m.group(3)
        windows.append((ns, frm, to))
    return windows


def overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return max(start_a, start_b) < min(end_a, end_b)


def fmt_utc(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')


def fmt_local(ts: datetime) -> str:
    return ts.astimezone(local_tz).strftime('%Y-%m-%d %H:%M')


def fetch_db_15m_buckets(threshold: int, start_dt: datetime, end_dt: datetime):
    conn = None
    rows = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        set_db_role(cur)
        cur.execute(
            """
            SELECT
                date_trunc('hour', timestamp)
                  + (floor(date_part('minute', timestamp) / 15)::int * interval '15 minutes') AS bucket_15m,
                namespace,
                SUM(original_value)::bigint AS total_value,
                COUNT(*)::int AS incident_rows,
                SUM(CASE WHEN is_spike OR is_burst THEN 1 ELSE 0 END)::int AS flagged_rows
            FROM ailog_peak.peak_investigation
            WHERE timestamp >= %s
              AND timestamp < %s
            GROUP BY 1, 2
            HAVING SUM(original_value) >= %s
            ORDER BY bucket_15m DESC, total_value DESC
            """,
            (start_dt, end_dt, threshold),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as exc:
        return [], str(exc)
    finally:
        if conn:
            conn.close()
    return rows, None


def fetch_db_15m_all(start_dt: datetime, end_dt: datetime):
    conn = None
    rows = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        set_db_role(cur)
        cur.execute(
            """
            SELECT
                date_trunc('hour', timestamp)
                  + (floor(date_part('minute', timestamp) / 15)::int * interval '15 minutes') AS bucket_15m,
                namespace,
                SUM(original_value)::bigint AS total_value,
                COUNT(*)::int AS incident_rows,
                SUM(CASE WHEN is_spike OR is_burst THEN 1 ELSE 0 END)::int AS flagged_rows
            FROM ailog_peak.peak_investigation
            WHERE timestamp >= %s
              AND timestamp < %s
            GROUP BY 1, 2
            ORDER BY bucket_15m ASC, namespace ASC
            """,
            (start_dt, end_dt),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as exc:
        return [], str(exc)
    finally:
        if conn:
            conn.close()
    return rows, None


def parse_error_ts(ts: str):
    if not ts:
        return None
    s = str(ts).strip()
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def floor_to_15m(ts: datetime) -> datetime:
    return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)


def load_raw_cache_rows(path: Path):
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('errors', 'logs', 'events', 'items', 'data'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return None


def latest_window_to(item):
    windows = parse_windows(item.get('peak_windows_24h', ''))
    if not windows:
        return ''
    return max(w[1] for w in windows)


rows = sorted(peaks, key=latest_window_to, reverse=True)

window_start_dt = parse_utc_z(window_start)
window_end_dt = parse_utc_z(window_end)

global_peak_intervals = []
ns_peak_intervals = defaultdict(list)
peak_index_by_ns = defaultdict(list)

for item in rows:
    peak_id = item.get('peak_id', '')
    for frm, to in parse_windows(item.get('peak_windows_24h', '')):
        fdt = parse_minute(frm)
        tdt = parse_minute(to)
        global_peak_intervals.append((fdt, tdt, peak_id))

    for ns, frm, to in parse_ns_windows(item.get('namespace_peak_windows_30m', '')):
        fdt = parse_minute(frm)
        tdt = parse_minute(to)
        ns_peak_intervals[ns].append((fdt, tdt, peak_id))
        peak_index_by_ns[ns].append(peak_id)

threshold_15m = int(os.getenv('DB_PEAK_THRESHOLD_15M', '200'))
db_rows, db_error = fetch_db_15m_buckets(threshold_15m, window_start_dt, window_end_dt)
db_all_rows, db_all_error = fetch_db_15m_all(window_start_dt, window_end_dt)

db_totals_by_ns = defaultdict(int)
db_bucket_ns_map = {}
for bucket_ts, namespace, total_value, incident_rows, flagged_rows in db_all_rows:
    bucket_start = bucket_ts.replace(tzinfo=timezone.utc) if bucket_ts.tzinfo is None else bucket_ts.astimezone(timezone.utc)
    db_totals_by_ns[namespace] += int(total_value)
    db_bucket_ns_map[(bucket_start, namespace)] = {
        'total_value': int(total_value),
        'incident_rows': int(incident_rows),
        'flagged_rows': int(flagged_rows),
    }

db_eval_rows = []
missed_candidates = []
for bucket_ts, namespace, total_value, incident_rows, flagged_rows in db_rows:
    bucket_start = bucket_ts.replace(tzinfo=timezone.utc) if bucket_ts.tzinfo is None else bucket_ts.astimezone(timezone.utc)
    bucket_end = bucket_start + timedelta(minutes=15)

    matched_peak_ids = set()
    for frm, to, pid in ns_peak_intervals.get(namespace, []):
        if overlaps(bucket_start, bucket_end, frm, to):
            matched_peak_ids.add(pid)

    covered_by_ns = len(matched_peak_ids) > 0

    if not covered_by_ns:
        for frm, to, pid in global_peak_intervals:
            if overlaps(bucket_start, bucket_end, frm, to):
                matched_peak_ids.add(f'{pid} (global-only)')

    covered_any = len(matched_peak_ids) > 0
    status = 'COVERED' if covered_by_ns else ('PARTIAL_GLOBAL_ONLY' if covered_any else 'MISSED_CANDIDATE')

    row = {
        'bucket_start': bucket_start,
        'bucket_end': bucket_end,
        'namespace': namespace,
        'total_value': int(total_value),
        'incident_rows': int(incident_rows),
        'flagged_rows': int(flagged_rows),
        'status': status,
        'matched_peak_ids': ', '.join(sorted(matched_peak_ids)) if matched_peak_ids else '-',
    }
    db_eval_rows.append(row)

    if status == 'MISSED_CANDIDATE':
        missed_candidates.append(row)

raw_rows = load_raw_cache_rows(raw_cache_json)
raw_bucket_ns_map = {}
raw_totals_by_ns = defaultdict(int)
raw_eval_rows = []
raw_missed_candidates = []

if raw_rows is not None:
    for rec in raw_rows:
        ts = parse_error_ts(rec.get('timestamp') if isinstance(rec, dict) else None)
        if ts is None or ts < window_start_dt or ts >= window_end_dt:
            continue
        namespace = ((rec.get('namespace') if isinstance(rec, dict) else None) or 'unknown').strip()
        bucket_start = floor_to_15m(ts)
        key = (bucket_start, namespace)
        raw_bucket_ns_map[key] = raw_bucket_ns_map.get(key, 0) + 1
        raw_totals_by_ns[namespace] += 1

    for (bucket_start, namespace), total_value in sorted(raw_bucket_ns_map.items(), key=lambda x: (x[0][0], x[0][1])):
        if total_value < threshold_15m:
            continue
        bucket_end = bucket_start + timedelta(minutes=15)
        matched_peak_ids = set()

        for frm, to, pid in ns_peak_intervals.get(namespace, []):
            if overlaps(bucket_start, bucket_end, frm, to):
                matched_peak_ids.add(pid)

        covered_by_ns = len(matched_peak_ids) > 0
        if not covered_by_ns:
            for frm, to, pid in global_peak_intervals:
                if overlaps(bucket_start, bucket_end, frm, to):
                    matched_peak_ids.add(f'{pid} (global-only)')

        covered_any = len(matched_peak_ids) > 0
        status = 'COVERED' if covered_by_ns else ('PARTIAL_GLOBAL_ONLY' if covered_any else 'MISSED_CANDIDATE')

        row = {
            'bucket_start': bucket_start,
            'bucket_end': bucket_end,
            'namespace': namespace,
            'total_value': int(total_value),
            'status': status,
            'matched_peak_ids': ', '.join(sorted(matched_peak_ids)) if matched_peak_ids else '-',
        }
        raw_eval_rows.append(row)
        if status == 'MISSED_CANDIDATE':
            raw_missed_candidates.append(row)

lines = []
lines.append('# Peaks za poslednich 24 hodin (realna detekce)')
lines.append('')
lines.append(f"- Generovano UTC: {now.strftime('%Y-%m-%d %H:%M:%S')}")
lines.append(f"- Okno UTC: {window_start} -> {window_end}")
lines.append(f"- Report timezone: {local_tz.key} (local = UTC + offset dle DST)")
lines.append(f"- Pocet peaku v tabulce: {len(rows)}")
lines.append('')
lines.append('## Prehledna tabulka')
lines.append('')
lines.append('| peak_id | type | problem_key | windows_count | active_min | last_window_utc | last_window_local | top_namespace_errors | verdict |')
lines.append('|---|---|---|---:|---:|---|---|---|---|')
for x in rows:
    windows = parse_windows(x.get('peak_windows_24h', ''))
    last_to = parse_minute(max((w[1] for w in windows), default='1970-01-01 00:00')) if windows else None
    last_to_utc = fmt_utc(last_to) if last_to else '-'
    last_to_local = fmt_local(last_to) if last_to else '-'
    top_ns = x.get('namespace_breakdown_errors', '-')
    if top_ns != '-':
        top_ns = ', '.join(top_ns.split(', ')[:3])
    lines.append(
        f"| {x.get('peak_id','')} | {str(x.get('peak_type','')).upper()} | {x.get('problem_key','')} | "
        f"{x.get('peak_window_count_24h',0)} | {x.get('peak_duration_min_24h',0)} | {last_to_utc} | {last_to_local} | {top_ns} | {x.get('verdict','')} |"
    )

lines.append('')
lines.append('## RAW totals 24h per namespace (source cache)')
lines.append('')
if raw_rows is None:
    lines.append(f'- Source cache not found: {raw_cache_json}')
else:
    lines.append('| namespace | total_errors_24h |')
    lines.append('|---|---:|')
    for ns, total in sorted(raw_totals_by_ns.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f'| {ns} | {total} |')

lines.append('')
lines.append('## RAW validace (15min, threshold >= 200)')
lines.append('')
if raw_rows is None:
    lines.append('- RAW validation skipped (missing source cache file).')
else:
    lines.append(f'- Threshold_15m: {threshold_15m}')
    lines.append(f'- Buckets over threshold: {len(raw_eval_rows)}')
    lines.append(f'- Missed candidates (not covered by namespace peak windows): {len(raw_missed_candidates)}')
    lines.append('')
    lines.append('| bucket_from_utc | bucket_from_local | namespace | total_value | status | matched_peak_ids |')
    lines.append('|---|---|---|---:|---|---|')
    for r in raw_eval_rows[:220]:
        lines.append(
            f"| {fmt_utc(r['bucket_start'])} | {fmt_local(r['bucket_start'])} | "
            f"{r['namespace']} | {r['total_value']} | {r['status']} | {r['matched_peak_ids']} |"
        )

    lines.append('')
    lines.append('### Missed peak candidates (RAW threshold hit but no namespace peak window match)')
    lines.append('')
    lines.append('| bucket_from_utc | bucket_from_local | namespace | total_value |')
    lines.append('|---|---|---|---:|')
    if raw_missed_candidates:
        for r in raw_missed_candidates:
            lines.append(
                f"| {fmt_utc(r['bucket_start'])} | {fmt_local(r['bucket_start'])} | {r['namespace']} | {r['total_value']} |"
            )
    else:
        lines.append('| - | - | - | 0 |')

lines.append('')
lines.append('## DB totals 24h per namespace (secondary / processed table)')
lines.append('')
if db_all_error:
    lines.append(f'- DB totals query failed: {db_all_error}')
else:
    lines.append('| namespace | total_value_24h |')
    lines.append('|---|---:|')
    for ns, total in sorted(db_totals_by_ns.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f'| {ns} | {total} |')

lines.append('')
lines.append('## Window probe (local time + sousedni okna)')
lines.append('')
probe_local_times = [
    datetime(2026, 2, 23, 15, 30, tzinfo=local_tz),
    datetime(2026, 2, 23, 16, 30, tzinfo=local_tz),
    datetime(2026, 2, 23, 18, 0, tzinfo=local_tz),
]
probe_namespaces = ['pcb-sit-01-app', 'pcb-dev-01-app', 'pcb-uat-01-app', 'pcb-fat-01-app']
lines.append('| probe_local | bucket_local | bucket_utc | namespace | total_value | incident_rows | flagged_rows |')
lines.append('|---|---|---|---|---:|---:|---:|')
for probe in probe_local_times:
    for shift in (-15, 0, 15):
        bucket_local = probe + timedelta(minutes=shift)
        bucket_utc = bucket_local.astimezone(timezone.utc)
        bucket_utc = bucket_utc.replace(minute=(bucket_utc.minute // 15) * 15, second=0, microsecond=0)
        for ns in probe_namespaces:
            item = db_bucket_ns_map.get((bucket_utc, ns), {'total_value': 0, 'incident_rows': 0, 'flagged_rows': 0})
            lines.append(
                f"| {probe.strftime('%Y-%m-%d %H:%M')} | {bucket_local.strftime('%Y-%m-%d %H:%M')} | {fmt_utc(bucket_utc)} | "
                f"{ns} | {item['total_value']} | {item['incident_rows']} | {item['flagged_rows']} |"
            )

lines.append('')
lines.append('## Interpretace ISSUE')
lines.append('- ISSUE znamena, ze pro peak exportovany v registry se v tomhle 24h runu nenasel odpovidajici aktivni incident/evidence match v pipeline datech.')
lines.append('- Neni to chyba formatu; je to signal k overeni, jestli jde o historicky peak, jinou klasifikaci, nebo kandidat na missed detection.')
lines.append('')
lines.append('## Detaily pod tabulkou')
for item in rows:
    lines.append('')
    lines.append(f"### {item.get('peak_id','')} - {item.get('problem_key','')}")
    lines.append(f"- Typ: {str(item.get('peak_type','')).upper()}")
    lines.append(f"- Peak windows (real): {item.get('peak_windows_24h','-')}")
    lines.append(f"- Aktivni trvani v 24h (min): {item.get('peak_duration_min_24h',0)}")
    lines.append(f"- Pocet oken: {item.get('peak_window_count_24h',0)}")
    lines.append(f"- Namespace breakdown (errors): {item.get('namespace_breakdown_errors','-')}")
    lines.append(f"- Namespace windows 30m: {item.get('namespace_peak_windows_30m','-')}")
    lines.append(f"- Detected occurrences v 24h: {item.get('detected_occurrences_24h',0)}")
    lines.append(f"- Detected incidents: {item.get('detected_incidents',0)}")
    lines.append(f"- Evidence checks / OK: {item.get('evidence_checks',0)} / {item.get('evidence_ok',False)}")
    lines.append(f"- Verdict: {item.get('verdict','')}")
    incident_evidence = item.get('incident_evidence', [])
    rule_counts = defaultdict(int)
    baseline_zero = 0
    for inc in incident_evidence:
        if float(inc.get('baseline_rate', 0) or 0) == 0:
            baseline_zero += 1
        for ev in inc.get('evidence', []):
            rule_counts[ev.get('rule', 'unknown')] += 1
    if incident_evidence:
        rules_text = ', '.join(f'{k}:{v}' for k, v in sorted(rule_counts.items()))
        lines.append(f"- Rule summary: {rules_text}")
        lines.append(f"- Fingerprints with baseline=0: {baseline_zero}/{len(incident_evidence)}")
        if baseline_zero > 0:
            lines.append('- Poznamka: baseline=0 + rule spike_new_error_type znamena novy/neznamy error typ; muze se objevit vice fingerprintu se strednim countem, i kdyz jen cast z nich tvori hlavni volumetricky peak.')
    lines.append('')
    lines.append('| fingerprint | first_seen | last_seen | current_count | current_rate | baseline_rate | rules |')
    lines.append('|---|---|---|---:|---:|---:|---|')
    incidents = item.get('incident_evidence', [])
    if incidents:
        for inc in incidents[:30]:
            rules = ', '.join(ev.get('rule', '') for ev in inc.get('evidence', [])) if inc.get('evidence') else '-'
            lines.append(
                f"| {inc.get('fingerprint','')} | {inc.get('first_seen','')} | {inc.get('last_seen','')} | "
                f"{inc.get('current_count',0)} | {round(float(inc.get('current_rate',0) or 0),2)} | "
                f"{round(float(inc.get('baseline_rate',0) or 0),2)} | {rules} |"
            )
    else:
        lines.append('| - | - | - | 0 | 0 | 0 | - |')


unique_windows = len({item.get('peak_windows_24h', '') for item in rows})
same_window_rows = sum(1 for item in rows if item.get('peak_windows_24h', '') == (rows[0].get('peak_windows_24h', '') if rows else ''))
lines.append('')
lines.append('## Validace')
lines.append(f'- unique_peak_windows_values: {unique_windows}')
lines.append(f'- rows_sharing_first_window_pattern: {same_window_rows}/{len(rows)}')
if raw_rows is not None:
    lines.append(f"- raw_threshold_15m: {threshold_15m}")
    lines.append(f"- raw_buckets_over_threshold: {len(raw_eval_rows)}")
    lines.append(f"- raw_missed_candidates: {len(raw_missed_candidates)}")
if not db_error:
    lines.append(f"- db_threshold_15m: {threshold_15m}")
    lines.append(f"- db_buckets_over_threshold: {len(db_eval_rows)}")
    lines.append(f"- db_missed_candidates: {len(missed_candidates)}")
if rows and same_window_rows == len(rows):
    lines.append('- WARNING: vsechny peaky maji stejny window pattern -> zkontrolovat zdroj data.')
else:
    lines.append('- OK: peaky nejsou vsechny ve stejnem case, casy odpovidaji realnym detekovanym oknum.')
lines.append(f"- casovy posun: report zobrazuje UTC i local ({local_tz.key}), aby nedochazelo k posunu o 1h pri manualni kontrole.")

out.write_text('\n'.join(lines), encoding='utf-8')
out_main.write_text('\n'.join(lines), encoding='utf-8')
print(out)
print(out_main)
print(f'rows={len(rows)}')
