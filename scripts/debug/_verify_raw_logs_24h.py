import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

repo = Path('/home/jvsete/git/ai-log-analyzer')
ai_data = repo / 'ai-data'
cache_file = ai_data / 'source_logs_24h_cache.json'
investigation_json = ai_data / 'active_peaks_24h_investigation.json'
out_file = ai_data / 'raw_logs_24h_validation.md'

tz_local = ZoneInfo('Europe/Prague')
threshold_15m = 200

if not cache_file.exists():
    raise SystemExit(f'Missing cache file: {cache_file}')
if not investigation_json.exists():
    raise SystemExit(f'Missing investigation file: {investigation_json}')

window_re = re.compile(r'([\w\-]+)\s*\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})->(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]')


def parse_iso_utc(ts: str):
    if not ts:
        return None
    s = ts.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_minute_utc(ts: str):
    return datetime.strptime(ts, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)


def fmtu(dt):
    return dt.strftime('%Y-%m-%d %H:%M')


def fmtl(dt):
    return dt.astimezone(tz_local).strftime('%Y-%m-%d %H:%M')


def floor_15m(ts: datetime):
    return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)


def overlaps(a_start, a_end, b_start, b_end):
    return max(a_start, b_start) < min(a_end, b_end)


payload = json.loads(investigation_json.read_text(encoding='utf-8'))
window_start = parse_iso_utc(payload.get('window_start_utc', ''))
window_end = parse_iso_utc(payload.get('window_end_utc', ''))
peaks = payload.get('peaks', [])

if not window_start or not window_end or window_end <= window_start:
    raise SystemExit('Invalid investigation window in active_peaks_24h_investigation.json')

rows = json.loads(cache_file.read_text(encoding='utf-8'))
if isinstance(rows, dict):
    rows = rows.get('errors') or rows.get('logs') or rows.get('data') or []
if not isinstance(rows, list):
    raise SystemExit('Unexpected source_logs_24h_cache.json format')

parsed = []
for item in rows:
    if not isinstance(item, dict):
        continue
    ts = parse_iso_utc(item.get('@timestamp') or item.get('timestamp') or '')
    if ts is None or ts < window_start or ts >= window_end:
        continue
    ns = (
        item.get('namespace')
        or item.get('kubernetes', {}).get('namespace')
        or item.get('kubernetes_namespace')
        or 'unknown'
    )
    ns = (ns or 'unknown').strip()
    parsed.append((ts, ns))

if not parsed:
    raise SystemExit('No timestamped rows found in cache file for investigation window')

ns_totals = Counter(ns for _, ns in parsed)
bucket_15m_by_ns = defaultdict(Counter)
for ts, ns in parsed:
    bucket_15m_by_ns[ns][floor_15m(ts)] += 1

all_peak_windows_ns = []
for p in peaks:
    peak_id = p.get('peak_id', '')
    problem_key = p.get('problem_key', '')
    text = p.get('namespace_peak_windows_30m', '')
    for ns, frm, to in window_re.findall(text):
        from_dt = parse_minute_utc(frm)
        to_dt = parse_minute_utc(to)
        if to_dt <= window_start or from_dt >= window_end:
            continue
        all_peak_windows_ns.append((peak_id, problem_key, ns.strip(), max(from_dt, window_start), min(to_dt, window_end)))

peak_window_rows = []
for peak_id, problem_key, ns, win_from, win_to in sorted(all_peak_windows_ns, key=lambda x: (x[0], x[3], x[2])):
    counter = bucket_15m_by_ns.get(ns, Counter())
    window_total = 0
    max_15m = 0
    b = floor_15m(win_from)
    while b < win_to:
        c = counter.get(b, 0)
        window_total += c
        if c > max_15m:
            max_15m = c
        b += timedelta(minutes=15)

    prev_bucket = floor_15m(win_from - timedelta(seconds=1))
    next_bucket = floor_15m(win_to)
    prev_count = counter.get(prev_bucket, 0)
    next_count = counter.get(next_bucket, 0)

    peak_window_rows.append(
        {
            'peak_id': peak_id,
            'problem_key': problem_key,
            'namespace': ns,
            'window_from': win_from,
            'window_to': win_to,
            'window_total_raw': window_total,
            'window_max_15m_raw': max_15m,
            'prev_15m_raw': prev_count,
            'next_15m_raw': next_count,
        }
    )

per_peak = defaultdict(lambda: {
    'problem_key': '',
    'window_rows': 0,
    'raw_total': 0,
    'max_15m': 0,
    'namespaces': set(),
})
for r in peak_window_rows:
    item = per_peak[r['peak_id']]
    item['problem_key'] = r['problem_key']
    item['window_rows'] += 1
    item['raw_total'] += r['window_total_raw']
    item['max_15m'] = max(item['max_15m'], r['window_max_15m_raw'])
    item['namespaces'].add(r['namespace'])

covered_windows_ns = defaultdict(list)
for _, _, ns, wf, wt in all_peak_windows_ns:
    covered_windows_ns[ns].append((wf, wt))

raw_high_buckets = []
for ns, buckets in bucket_15m_by_ns.items():
    for bucket_start, value in buckets.items():
        if value < threshold_15m:
            continue
        bucket_end = bucket_start + timedelta(minutes=15)
        covered = any(overlaps(bucket_start, bucket_end, wf, wt) for wf, wt in covered_windows_ns.get(ns, []))
        raw_high_buckets.append(
            {
                'bucket_start': bucket_start,
                'namespace': ns,
                'raw_count': value,
                'covered': covered,
            }
        )

raw_high_buckets.sort(key=lambda x: (x['bucket_start'], x['namespace']))
uncovered = [x for x in raw_high_buckets if not x['covered']]

lines = []
lines.append('# RAW logs 24h verification (peak-centric)')
lines.append('')
lines.append(f'- Source file: {cache_file.name}')
lines.append(f'- Investigation source: {investigation_json.name}')
lines.append(f'- Total rows (filtered to window): {len(parsed)}')
lines.append(f'- Window UTC: {fmtu(window_start)} -> {fmtu(window_end)}')
lines.append(f'- Window local ({tz_local.key}): {fmtl(window_start)} -> {fmtl(window_end)}')
lines.append(f'- Threshold for high 15m buckets: {threshold_15m}')
lines.append('')

lines.append('## Totals per namespace (raw logs)')
lines.append('')
lines.append('| namespace | total_errors_24h_raw |')
lines.append('|---|---:|')
for ns, cnt in sorted(ns_totals.items(), key=lambda x: (-x[1], x[0])):
    lines.append(f'| {ns} | {cnt} |')

lines.append('')
lines.append('## Peak summary (compact kontrola)')
lines.append('')
lines.append('| peak_id | problem_key | ns_windows | namespaces | raw_total_across_peak_windows | max_15m_in_peak_windows |')
lines.append('|---|---|---:|---:|---:|---:|')
for peak_id, item in sorted(per_peak.items(), key=lambda x: x[0]):
    lines.append(
        f"| {peak_id} | {item['problem_key']} | {item['window_rows']} | {len(item['namespaces'])} | {item['raw_total']} | {item['max_15m']} |"
    )

lines.append('')
lines.append('## Peak windows - RAW counts for kontrola')
lines.append('')
lines.append('| peak_id | namespace | window_from_utc | window_from_local | window_to_utc | raw_total_30m | raw_max_15m | prev_15m_raw | next_15m_raw |')
lines.append('|---|---|---|---|---|---:|---:|---:|---:|')
for r in sorted(peak_window_rows, key=lambda x: (x['window_from'], x['peak_id'], x['namespace'])):
    lines.append(
        f"| {r['peak_id']} | {r['namespace']} | {fmtu(r['window_from'])} | {fmtl(r['window_from'])} | {fmtu(r['window_to'])} | "
        f"{r['window_total_raw']} | {r['window_max_15m_raw']} | {r['prev_15m_raw']} | {r['next_15m_raw']} |"
    )

lines.append('')
lines.append('## High RAW 15m buckets (>= threshold) vs peak coverage')
lines.append('')
lines.append(f'- Total high buckets: {len(raw_high_buckets)}')
lines.append(f'- Covered by namespace peak windows: {len(raw_high_buckets) - len(uncovered)}')
lines.append(f'- Uncovered (candidate gaps): {len(uncovered)}')
lines.append('')
lines.append('| bucket_from_utc | bucket_from_local | namespace | raw_count_15m | status |')
lines.append('|---|---|---|---:|---|')
for b in raw_high_buckets:
    status = 'COVERED' if b['covered'] else 'UNCOVERED'
    lines.append(
        f"| {fmtu(b['bucket_start'])} | {fmtl(b['bucket_start'])} | {b['namespace']} | {b['raw_count']} | {status} |"
    )

if uncovered:
    lines.append('')
    lines.append('## Uncovered high buckets (focus for manual check)')
    lines.append('')
    lines.append('| bucket_from_utc | bucket_from_local | namespace | raw_count_15m |')
    lines.append('|---|---|---|---:|')
    for b in uncovered:
        lines.append(
            f"| {fmtu(b['bucket_start'])} | {fmtl(b['bucket_start'])} | {b['namespace']} | {b['raw_count']} |"
        )

out_file.write_text('\n'.join(lines), encoding='utf-8')
print(out_file)
print(f'rows={len(parsed)} peak_windows={len(peak_window_rows)} high_buckets={len(raw_high_buckets)} uncovered={len(uncovered)}')
