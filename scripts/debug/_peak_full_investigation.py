import os
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
import statistics

repo = Path('/home/jvsete/git/ai-log-analyzer')
os.chdir(repo)

import sys
sys.path.insert(0, str(repo / 'scripts'))
sys.path.insert(0, str(repo))

from dotenv import load_dotenv

from scripts.core.fetch_unlimited import fetch_unlimited
from scripts.core.problem_registry import ProblemRegistry
from scripts.core.baseline_loader import BaselineLoader
from scripts.pipeline import PipelineV6
from scripts.pipeline.phase_a_parse import PhaseA_Parser
from scripts.analysis import aggregate_by_problem_key
from scripts.regular_phase_v6 import get_db_connection


load_dotenv(repo / '.env')
load_dotenv(repo / 'config/.env')


OUT_DIR = repo / 'ai-data'
latest_peaks_csv = OUT_DIR / 'latest' / 'peaks_table.csv'
known_md = OUT_DIR / 'known_peaks_clean.md'
active_md = OUT_DIR / 'active_peaks_24h_investigation.md'
active_csv = OUT_DIR / 'active_peaks_24h_investigation.csv'
active_json = OUT_DIR / 'active_peaks_24h_investigation.json'

window_minutes = 1440


def parse_iso_utc(value: str) -> datetime:
    s = (value or '').strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


window_from_env = os.getenv('INVESTIGATION_FROM_UTC', '').strip()
window_to_env = os.getenv('INVESTIGATION_TO_UTC', '').strip()

if window_from_env and window_to_env:
    window_start = parse_iso_utc(window_from_env)
    window_end = parse_iso_utc(window_to_env)
    if window_end <= window_start:
        raise ValueError('INVESTIGATION_TO_UTC must be greater than INVESTIGATION_FROM_UTC')
    window_minutes = int((window_end - window_start).total_seconds() // 60)
else:
    now_auto = datetime.now(timezone.utc)
    quarter = (now_auto.minute // 15) * 15
    window_end = now_auto.replace(minute=quarter, second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=window_minutes)

now = datetime.now(timezone.utc)


def parse_ts(s: str):
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)


def fmt_ts(ts: datetime):
    return ts.strftime('%Y-%m-%d %H:%M') if ts else ''


def parse_peak_key(k: str):
    parts = (k or '').split(':')
    if len(parts) >= 4:
        return parts[1].lower(), parts[2].lower(), parts[3].lower()
    return 'unknown', 'unknown', 'unknown'


def incident_evidence_eval(inc, peak_type):
    checks = []
    for ev in (inc.evidence or []):
        ok = None
        if peak_type == 'spike' and ev.rule in ('spike_ewma', 'spike_mad', 'spike_new_error_type'):
            if ev.rule == 'spike_ewma':
                ratio = (inc.stats.current_rate / inc.stats.baseline_rate) if inc.stats.baseline_rate else 0.0
                ok = ratio > float(ev.threshold)
            elif ev.rule == 'spike_mad':
                ok = inc.stats.current_rate > float(ev.threshold)
            elif ev.rule == 'spike_new_error_type':
                ok = (inc.stats.baseline_rate == 0 and inc.stats.current_count >= 5)
        elif peak_type == 'burst' and ev.rule == 'burst':
            ok = True if ('ratio' in (ev.message or '') and '>' in (ev.message or '')) else None

        if ok is not None:
            checks.append(
                {
                    'rule': ev.rule,
                    'baseline': ev.baseline,
                    'current': ev.current,
                    'threshold': ev.threshold,
                    'message': ev.message,
                    'ok': bool(ok),
                }
            )
    return checks


def clipped_interval(incidents):
    starts = []
    ends = []
    for inc in incidents:
        fs = getattr(inc.time, 'first_seen', None)
        ls = getattr(inc.time, 'last_seen', None)
        if fs:
            starts.append(max(fs, window_start))
        if ls:
            ends.append(min(ls, window_end))
    if not starts or not ends:
        return None, None, None
    start_ts = min(starts)
    end_ts = max(ends)
    duration_min = int((end_ts - start_ts).total_seconds() / 60)
    if duration_min < 0:
        duration_min = 0
    return start_ts, end_ts, duration_min


def floor_to_30min(ts: datetime):
    minute = 0 if ts.minute < 30 else 30
    return ts.replace(minute=minute, second=0, microsecond=0)


def derive_ns_peak_windows(records):
    """
    Derive 30-minute peak windows per namespace from matched records.

    Peak bucket threshold per NS:
      max(50, median(bucket_counts) + 3*MAD)
    """
    ns_bucket_counts = defaultdict(lambda: defaultdict(int))

    for rec in records:
        ts = getattr(rec, 'timestamp', None)
        if not ts:
            continue
        if ts < window_start or ts > window_end:
            continue
        ns = (getattr(rec, 'namespace', None) or 'unknown').strip()
        bucket = floor_to_30min(ts)
        ns_bucket_counts[ns][bucket] += 1

    result = {}
    for ns, bucket_map in ns_bucket_counts.items():
        if not bucket_map:
            result[ns] = {
                'threshold': 50,
                'buckets': [],
                'windows': [],
            }
            continue

        sorted_items = sorted(bucket_map.items(), key=lambda x: x[0])
        values = [v for _, v in sorted_items]
        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations) if deviations else 0
        threshold = int(max(50, median + 3 * mad))

        hot = [(ts, c) for ts, c in sorted_items if c >= threshold]

        windows = []
        if hot:
            win_start, win_end = hot[0][0], hot[0][0]
            total = hot[0][1]
            peak = hot[0][1]
            for ts, cnt in hot[1:]:
                if ts == win_end + timedelta(minutes=30):
                    win_end = ts
                    total += cnt
                    peak = max(peak, cnt)
                else:
                    windows.append(
                        {
                            'from': win_start,
                            'to': win_end + timedelta(minutes=30),
                            'bucket_count_sum': total,
                            'bucket_count_max': peak,
                        }
                    )
                    win_start, win_end = ts, ts
                    total = cnt
                    peak = cnt
            windows.append(
                {
                    'from': win_start,
                    'to': win_end + timedelta(minutes=30),
                    'bucket_count_sum': total,
                    'bucket_count_max': peak,
                }
            )

        result[ns] = {
            'threshold': threshold,
            'buckets': sorted_items,
            'windows': windows,
        }

    return result


def merge_time_windows(windows):
    """Merge overlapping/contiguous windows and return merged list + active minutes."""
    if not windows:
        return [], 0

    sorted_windows = sorted(windows, key=lambda x: x[0])
    merged = []
    cur_start, cur_end = sorted_windows[0]

    for start_ts, end_ts in sorted_windows[1:]:
        if start_ts <= cur_end:
            if end_ts > cur_end:
                cur_end = end_ts
        else:
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start_ts, end_ts

    merged.append((cur_start, cur_end))

    active_min = 0
    for start_ts, end_ts in merged:
        delta_min = int((end_ts - start_ts).total_seconds() / 60)
        if delta_min > 0:
            active_min += delta_min

    return merged, active_min


def ns_breakdown_from_records(records):
    counts = defaultdict(int)
    for r in records:
        ns = (getattr(r, 'namespace', None) or 'unknown').strip()
        counts[ns] += 1
    return dict(sorted(counts.items(), key=lambda x: (-x[1], x[0])))


def components_from_incidents(incidents):
    apps = defaultdict(int)
    for inc in incidents:
        c = int(getattr(inc.stats, 'current_count', 0) or 0)
        if c <= 0:
            c = 1
        for app in (inc.apps or []):
            apps[app] += c
    ordered = sorted(apps.items(), key=lambda x: (-x[1], x[0]))
    top = [k for k, _ in ordered[:8]]
    return top, ordered


# ---------------------------------------------------------------------
# 1) Known peaks split active/inactive (without duration)
# ---------------------------------------------------------------------
peak_rows = []
with latest_peaks_csv.open('r', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        fs = parse_ts(r['first_seen'])
        ls = parse_ts(r['last_seen'])
        peak_rows.append(
            {
                'peak_id': r['peak_id'],
                'problem_key': r['problem_key'],
                'category': r['category'],
                'peak_type': r['peak_type'].lower(),
                'namespace': r['affected_namespaces'],
                'apps': r['affected_apps'],
                'error_count': int(r['peak_count']),
                'ratio': float(r['peak_ratio']),
                'first_seen': fs,
                'last_seen': ls,
                'status': r['status'],
                'is_active_24h': ls >= window_start,
                'is_new_in_24h': fs >= window_start,
            }
        )

active_rows = [r for r in peak_rows if r['is_active_24h']]
inactive_rows = [r for r in peak_rows if not r['is_active_24h']]

known_lines = []
known_lines.append('# Known peaks (clean table - no duration)')
known_lines.append('')
known_lines.append(f'- Generated UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}')
known_lines.append(f'- Active (last 24h): {len(active_rows)}')
known_lines.append(f'- Historical/inactive: {len(inactive_rows)}')
known_lines.append('')
known_lines.append('## Active peaks (last 24h)')
known_lines.append('')
known_lines.append('| peak_id | peak_type | new_in_24h | first_seen | last_seen | error_count | namespace | problem_key |')
known_lines.append('|---|---|---|---|---|---:|---|---|')
for r in sorted(active_rows, key=lambda x: x['last_seen'], reverse=True):
    known_lines.append(
        f"| {r['peak_id']} | {r['peak_type'].upper()} | {r['is_new_in_24h']} | {fmt_ts(r['first_seen'])} | {fmt_ts(r['last_seen'])} | {r['error_count']} | {r['namespace']} | {r['problem_key']} |"
    )

known_lines.append('')
known_lines.append('## Historical peaks (inactive)')
known_lines.append('')
known_lines.append('| peak_id | peak_type | first_seen | last_seen | error_count | namespace | problem_key |')
known_lines.append('|---|---|---|---|---:|---|---|')
for r in sorted(inactive_rows, key=lambda x: x['last_seen'], reverse=True):
    known_lines.append(
        f"| {r['peak_id']} | {r['peak_type'].upper()} | {fmt_ts(r['first_seen'])} | {fmt_ts(r['last_seen'])} | {r['error_count']} | {r['namespace']} | {r['problem_key']} |"
    )

known_md.write_text('\n'.join(known_lines), encoding='utf-8')


# ---------------------------------------------------------------------
# 2) Fetch ES + run pipeline + parse records for NS breakdown
# ---------------------------------------------------------------------
registry = ProblemRegistry(str(repo / 'registry'))
registry.load()

errors = fetch_unlimited(
    window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
    window_end.strftime('%Y-%m-%dT%H:%M:%SZ')
)

parser = PhaseA_Parser()
records = parser.parse_batch(errors)
records_by_fp = defaultdict(list)
for rec in records:
    records_by_fp[rec.fingerprint].append(rec)

historical_baseline = {}
try:
    db_conn = get_db_connection()
    baseline_loader = BaselineLoader(db_conn)
    sample_error_types = set()
    for e in errors[:1000]:
        et = parser.extract_error_type(e.get('message', ''))
        if et and et != 'Unknown':
            sample_error_types.add(et)
    if sample_error_types:
        historical_baseline = baseline_loader.load_historical_rates(
            error_types=list(sample_error_types),
            lookback_days=7,
            min_samples=3
        )
    db_conn.close()
except Exception:
    historical_baseline = {}

pipeline = PipelineV6(
    spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
    ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
    window_minutes=window_minutes,
)
pipeline.phase_b.error_type_baseline = historical_baseline
pipeline.phase_c.registry = registry
pipeline.phase_c.known_fingerprints = registry.get_all_known_fingerprints().copy()
collection = pipeline.run(errors, run_id='investigation-24h')
problems = aggregate_by_problem_key(collection.incidents)

index_cf = defaultdict(list)
for p in problems.values():
    index_cf[(p.category.lower(), p.flow.lower())].append(p)


# ---------------------------------------------------------------------
# 3) Per-peak investigation for active peaks
# ---------------------------------------------------------------------
invest_rows = []
invest_json_rows = []
timeline_rows = []

for pr in sorted(active_rows, key=lambda x: x['last_seen'], reverse=True):
    cat, flow, ptype = parse_peak_key(pr['problem_key'])
    candidates = index_cf.get((cat, flow), [])

    matched_problems = []
    for p in candidates:
        if ptype == 'spike' and p.has_spike:
            matched_problems.append(p)
        elif ptype == 'burst' and p.has_burst:
            matched_problems.append(p)

    incidents = []
    for p in matched_problems:
        for inc in p.incidents:
            if ptype == 'spike' and inc.flags.is_spike:
                incidents.append(inc)
            elif ptype == 'burst' and inc.flags.is_burst:
                incidents.append(inc)

    evidence_checks = []
    for inc in incidents:
        evidence_checks.extend(incident_evidence_eval(inc, ptype))

    all_ok = bool(evidence_checks) and all(x['ok'] for x in evidence_checks)

    incident_start, incident_end, duration_min = clipped_interval(incidents)
    fp_set = {inc.fingerprint for inc in incidents}

    relevant_records = []
    for fp in fp_set:
        relevant_records.extend(records_by_fp.get(fp, []))

    ns_windows = derive_ns_peak_windows(relevant_records)
    ns_counts = ns_breakdown_from_records(relevant_records)
    ns_breakdown_text = ', '.join(f'{k}:{v}' for k, v in ns_counts.items()) if ns_counts else '-'

    occ_sum = int(sum(ns_counts.values()))

    window_entries = []
    for ns, data in ns_windows.items():
        for w in data['windows']:
            window_entries.append((w['from'], w['to'], ns, w['bucket_count_sum'], w['bucket_count_max'], data['threshold']))
    window_entries.sort(key=lambda x: x[0])

    global_raw_windows = [(w_from, w_to) for w_from, w_to, _, _, _, _ in window_entries]
    merged_windows, active_duration_min = merge_time_windows(global_raw_windows)

    peak_windows_24h_text = '; '.join(
        f'[{fmt_ts(ws)}->{fmt_ts(we)}]'
        for ws, we in merged_windows
    ) if merged_windows else '-'

    ns_peak_windows_text = '; '.join(
        f"{ns} [{fmt_ts(w_from)}->{fmt_ts(w_to)}] sum={bucket_sum}, max_bucket={bucket_max}, thr={thr}"
        for w_from, w_to, ns, bucket_sum, bucket_max, thr in window_entries
    ) if window_entries else '-'

    top_components, components_with_counts = components_from_incidents(incidents)
    components_text = ', '.join(top_components) if top_components else '-'

    is_new_peak_24h = bool(pr['is_new_in_24h'])
    existed_before_24h = not is_new_peak_24h
    verdict = 'OK' if (incidents and all_ok) else 'ISSUE'

    if merged_windows:
        peak_from = merged_windows[0][0]
        peak_to = merged_windows[-1][1]
        duration_min = active_duration_min
    else:
        peak_from = None
        peak_to = None
        duration_min = 0

    inv = {
        'peak_id': pr['peak_id'],
        'problem_key': pr['problem_key'],
        'peak_type': ptype,
        'component_flow': flow,
        'components': components_text,
        'is_new_peak_24h': is_new_peak_24h,
        'existed_before_24h': existed_before_24h,
        'peak_from_24h': fmt_ts(peak_from),
        'peak_to_24h': fmt_ts(peak_to),
        'peak_duration_min_24h': duration_min,
        'peak_window_count_24h': len(merged_windows),
        'peak_windows_24h': peak_windows_24h_text,
        'namespace_count': len(ns_counts),
        'namespace_breakdown_errors': ns_breakdown_text,
        'namespace_peak_windows_30m': ns_peak_windows_text,
        'detected_occurrences_24h': int(occ_sum),
        'error_count_registry': pr['error_count'],
        'detected_incidents': len(incidents),
        'evidence_checks': len(evidence_checks),
        'evidence_ok': all_ok,
        'verdict': verdict,
    }
    invest_rows.append(inv)

    # Timeline rows: one output row per exact peak window (newest-first later)
    for w_from, w_to, ns, bucket_sum, bucket_max, thr in window_entries:
        timeline_rows.append(
            {
                'window_from_utc': w_from,
                'window_to_utc': w_to,
                'peak_id': pr['peak_id'],
                'problem_key': pr['problem_key'],
                'peak_type': ptype.upper(),
                'component_flow': flow,
                'is_new_peak_24h': is_new_peak_24h,
                'namespace': ns,
                'errors_in_window': int(bucket_sum),
                'window_max_bucket': int(bucket_max),
                'window_threshold': int(thr),
                'why_detected': 'evidence_rules_ok' if all_ok else 'no_current_match_or_evidence',
                'verdict': verdict,
            }
        )

    invest_json_rows.append(
        {
            **inv,
            'matched_problem_keys': [p.problem_key for p in matched_problems],
            'components_with_counts': components_with_counts,
            'incident_evidence': [
                {
                    'fingerprint': inc.fingerprint,
                    'current_count': inc.stats.current_count,
                    'current_rate': inc.stats.current_rate,
                    'baseline_rate': inc.stats.baseline_rate,
                    'first_seen': fmt_ts(getattr(inc.time, 'first_seen', None)),
                    'last_seen': fmt_ts(getattr(inc.time, 'last_seen', None)),
                    'flags': {
                        'is_spike': inc.flags.is_spike,
                        'is_burst': inc.flags.is_burst,
                        'is_new': inc.flags.is_new,
                        'is_cross_namespace': inc.flags.is_cross_namespace,
                    },
                    'evidence': [
                        {
                            'rule': e.rule,
                            'baseline': e.baseline,
                            'current': e.current,
                            'threshold': e.threshold,
                            'message': e.message,
                        }
                        for e in inc.evidence
                        if (
                            (ptype == 'spike' and e.rule in ('spike_ewma', 'spike_mad', 'spike_new_error_type'))
                            or (ptype == 'burst' and e.rule == 'burst')
                        )
                    ],
                }
                for inc in incidents
            ],
        }
    )


# Omission check
predicted = set()
for p in problems.values():
    if p.has_spike:
        predicted.add(f'peak:{p.category}:{p.flow}:spike')
    if p.has_burst:
        predicted.add(f'peak:{p.category}:{p.flow}:burst')

exported_active = {r['problem_key'].lower() for r in active_rows}
missing_in_export = sorted(predicted - exported_active)
extra_in_export = sorted(exported_active - predicted)


# CSV
with active_csv.open('w', encoding='utf-8', newline='') as f:
    timeline_sorted = sorted(timeline_rows, key=lambda x: x['window_from_utc'], reverse=True)
    w = csv.DictWriter(
        f,
        fieldnames=[
            'window_from_utc',
            'window_to_utc',
            'peak_id',
            'problem_key',
            'peak_type',
            'component_flow',
            'is_new_peak_24h',
            'namespace',
            'errors_in_window',
            'window_max_bucket',
            'window_threshold',
            'why_detected',
            'verdict',
        ],
    )
    w.writeheader()
    w.writerows(
        [
            {
                **row,
                'window_from_utc': fmt_ts(row['window_from_utc']),
                'window_to_utc': fmt_ts(row['window_to_utc']),
            }
            for row in timeline_sorted
        ]
    )


# JSON
active_json.write_text(
    json.dumps(
        {
            'generated_at_utc': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'window_start_utc': window_start.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'window_end_utc': window_end.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source_data': {
                'es_logs_fetched': len(errors),
                'normalized_records': len(records),
                'incidents_total': len(collection.incidents),
                'problems_total': len(problems),
                'active_peaks_exported': len(active_rows),
                'timeline_rows': len(timeline_rows),
            },
            'notes': {
                'ns_interpretation': 'Peak across multiple namespaces means same peak fingerprint/problem appeared in multiple namespaces within the 24h window; it does NOT mean all namespaces spiked at the exact same second.',
                'component_flow': 'Flow is middle part of problem_key (category:flow:error_class), e.g. card_servicing from PEAK:auth:card_servicing:burst.'
            },
            'possible_omissions': {
                'missing_in_export': missing_in_export,
                'extra_in_export': extra_in_export,
            },
            'peaks': invest_json_rows,
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding='utf-8',
)


# Markdown
md = []
md.append('# Active peaks 24h - investigation')
md.append('')
md.append(f'- Generated UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}')
md.append(f'- Window UTC: {window_start.strftime("%Y-%m-%d %H:%M")} -> {window_end.strftime("%Y-%m-%d %H:%M")}')
md.append(f'- Source ES logs: {len(errors)}')
md.append(f'- Pipeline incidents: {len(collection.incidents)}')
md.append(f'- Active peaks from registry export: {len(active_rows)}')
md.append('- Multi-NS meaning: peak across multiple NS = stejný peak pattern byl zachycen ve více namespace během 24h; neznamená to simultánní spike ve stejném okamžiku.')
md.append('- Component flow meaning: prostřední část problem_key (category:flow:error_class), např. card_servicing v PEAK:auth:card_servicing:burst.')
md.append('')
md.append('## Peak windows timeline (newest first)')
md.append('')
md.append('| window_from_utc | window_to_utc | peak_id | type | component(flow) | namespace | errors_in_window | max_bucket | threshold | new_in_24h | why_detected | verdict |')
md.append('|---|---|---|---|---|---|---:|---:|---:|---|---|---|')
for row in sorted(timeline_rows, key=lambda x: x['window_from_utc'], reverse=True):
    md.append(
        f"| {fmt_ts(row['window_from_utc'])} | {fmt_ts(row['window_to_utc'])} | {row['peak_id']} | {row['peak_type']} | {row['component_flow']} | {row['namespace']} | {row['errors_in_window']} | {row['window_max_bucket']} | {row['window_threshold']} | {row['is_new_peak_24h']} | {row['why_detected']} | {row['verdict']} |"
    )

md.append('')
md.append('## Peak summary (per peak)')
md.append('')
md.append('| peak_id | type | component(flow) | new_in_24h | windows_count | active_min | errors_per_ns | detected_occurrences_24h | verdict |')
md.append('|---|---|---|---|---:|---:|---|---:|---|')
for r in invest_rows:
    md.append(
        f"| {r['peak_id']} | {r['peak_type'].upper()} | {r['component_flow']} | {r['is_new_peak_24h']} | {r['peak_window_count_24h']} | {r['peak_duration_min_24h']} | {r['namespace_breakdown_errors']} | {r['detected_occurrences_24h']} | {r['verdict']} |"
    )

md.append('')
md.append('## Possible omissions check')
md.append('')
md.append(f'- Missing in export (detected by pipeline but not in active export): {len(missing_in_export)}')
for k in missing_in_export:
    md.append(f'  - {k}')
md.append(f'- Extra in export (in active export but not detected in this run): {len(extra_in_export)}')
for k in extra_in_export:
    md.append(f'  - {k}')

md.append('')
md.append('## Per-peak evidence (each separately)')
for item in invest_json_rows:
    md.append('')
    md.append(f"### {item['peak_id']} - {item['problem_key']}")
    md.append(f"- Peak windows in 24h: {item['peak_windows_24h']} (windows={item['peak_window_count_24h']}, active_min={item['peak_duration_min_24h']})")
    md.append(f"- New in 24h: {item['is_new_peak_24h']} (existed_before_24h={item['existed_before_24h']})")
    md.append(f"- Component flow: {item['component_flow']}")
    md.append(f"- Components (apps): {item['components']}")
    md.append(f"- Namespace breakdown (errors): {item['namespace_breakdown_errors']}")
    md.append(f"- Namespace peak windows (30m): {item['namespace_peak_windows_30m']}")
    md.append(f"- Detected occurrences in 24h: {item['detected_occurrences_24h']}")
    md.append(f"- Verdict: {item['verdict']} (evidence_ok={item['evidence_ok']})")
    md.append('')
    md.append('| fingerprint | first_seen | last_seen | current_count | current_rate | baseline_rate | relevant_rules |')
    md.append('|---|---|---|---:|---:|---:|---|')
    for inc in item['incident_evidence'][:30]:
        rules = ', '.join(e['rule'] for e in inc['evidence']) if inc['evidence'] else '-'
        md.append(
            f"| {inc['fingerprint']} | {inc['first_seen']} | {inc['last_seen']} | {inc['current_count']} | {round(inc['current_rate'], 2)} | {round(inc['baseline_rate'], 2)} | {rules} |"
        )

active_md.write_text('\n'.join(md), encoding='utf-8')


print(f'written_known={known_md}')
print(f'written_active_md={active_md}')
print(f'written_active_csv={active_csv}')
print(f'written_active_json={active_json}')
print(f'active_rows={len(active_rows)} issues={sum(1 for r in invest_rows if r["verdict"] != "OK")}')
print(f'missing_in_export={len(missing_in_export)} extra_in_export={len(extra_in_export)}')
