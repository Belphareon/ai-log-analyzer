import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

repo = Path('/home/jvsete/git/ai-log-analyzer')
peaks_csv = repo / 'ai-data' / 'latest' / 'peaks_table.csv'
out_md = repo / 'ai-data' / 'peak_review_24h_namespace.md'
out_csv = repo / 'ai-data' / 'peak_review_24h_namespace.csv'

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=24)

def parse_ts(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)

rows = []
with peaks_csv.open('r', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        ls = parse_ts(r['last_seen'])
        if ls < cutoff:
            continue
        fs = parse_ts(r['first_seen'])
        dur_h = round((ls - fs).total_seconds()/3600, 2)
        rows.append({
            'peak_id': r['peak_id'],
            'namespace': r['affected_namespaces'],
            'peak_type': r['peak_type'],
            'duration_h': dur_h,
            'error_count': int(r['peak_count']),
            'first_seen': r['first_seen'],
            'last_seen': r['last_seen'],
            'peak_ratio': round(float(r['peak_ratio']), 2),
            'problem_key': r['problem_key'],
        })

rows.sort(key=lambda x: x['last_seen'], reverse=True)

with out_csv.open('w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['peak_id','namespace','peak_type','duration_h','error_count','peak_ratio','first_seen','last_seen','problem_key'])
    w.writeheader()
    w.writerows(rows)

# Similarity groups
by_ns_type = defaultdict(list)
for r in rows:
    by_ns_type[(r['namespace'], r['peak_type'])].append(r)

groups = []
for (ns, typ), items in by_ns_type.items():
    groups.append({
        'namespace': ns,
        'peak_type': typ,
        'similar_rows': len(items),
        'total_errors': sum(i['error_count'] for i in items),
        'peak_ids': ', '.join(i['peak_id'] for i in items),
        'problem_keys': ' | '.join(sorted(set(i['problem_key'] for i in items))),
    })

groups.sort(key=lambda g: (g['similar_rows'], g['total_errors']), reverse=True)

lines = []
lines.append('# Peak review 24h (namespace-first)')
lines.append('')
lines.append(f'- Generated UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}' )
lines.append(f'- Window: last 24h')
lines.append(f'- Rows: {len(rows)}')
lines.append('')
lines.append('## Detail')
lines.append('')
lines.append('| peak_id | namespace | peak_type | duration_h | error_count | peak_ratio | first_seen | last_seen | problem_key |')
lines.append('|---|---|---:|---:|---:|---:|---|---|---|')
for r in rows:
    lines.append(f"| {r['peak_id']} | {r['namespace']} | {r['peak_type']} | {r['duration_h']} | {r['error_count']} | {r['peak_ratio']} | {r['first_seen']} | {r['last_seen']} | {r['problem_key']} |")

lines.append('')
lines.append('## Similar peaks (namespace + type)')
lines.append('')
lines.append('| namespace | peak_type | similar_rows | total_errors | peak_ids | problem_keys |')
lines.append('|---|---:|---:|---:|---|---|')
for g in groups:
    lines.append(f"| {g['namespace']} | {g['peak_type']} | {g['similar_rows']} | {g['total_errors']} | {g['peak_ids']} | {g['problem_keys']} |")

out_md.write_text('\n'.join(lines), encoding='utf-8')

print(f'written_md={out_md}')
print(f'written_csv={out_csv}')
print(f'rows={len(rows)} groups={len(groups)}')
