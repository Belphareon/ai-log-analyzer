import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

repo = Path('/home/jvsete/git/ai-log-analyzer')
peaks_csv = repo / 'ai-data' / 'latest' / 'peaks_table.csv'
out_md = repo / 'ai-data' / 'peak_review_24h_condensed.md'
out_csv = repo / 'ai-data' / 'peak_review_24h_condensed.csv'

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=24)

def parse_ts(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)

def parse_flow(problem_key: str):
    # PEAK:category:flow:type
    parts = problem_key.split(':')
    return parts[2] if len(parts) >= 4 else 'unknown'

rows=[]
with peaks_csv.open('r', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        ls = parse_ts(r['last_seen'])
        if ls < cutoff:
            continue
        fs = parse_ts(r['first_seen'])
        rows.append({
            'peak_id': r['peak_id'],
            'namespace': r['affected_namespaces'],
            'peak_type': r['peak_type'],
            'flow': parse_flow(r['problem_key']),
            'error_count': int(r['peak_count']),
            'duration_h': round((ls-fs).total_seconds()/3600,2),
            'first_seen': fs,
            'last_seen': ls,
            'problem_key': r['problem_key'],
        })

clusters=defaultdict(list)
for r in rows:
    key=(r['namespace'], r['flow'], r['peak_type'])
    clusters[key].append(r)

agg=[]
for (ns,flow,typ),items in clusters.items():
    agg.append({
        'namespace': ns,
        'flow': flow,
        'peak_type': typ,
        'cluster_size': len(items),
        'total_errors': sum(i['error_count'] for i in items),
        'min_first_seen': min(i['first_seen'] for i in items).strftime('%Y-%m-%d %H:%M'),
        'max_last_seen': max(i['last_seen'] for i in items).strftime('%Y-%m-%d %H:%M'),
        'peak_ids': ', '.join(i['peak_id'] for i in items),
        'problem_keys': ' | '.join(sorted(set(i['problem_key'] for i in items)))
    })

agg.sort(key=lambda x:(x['cluster_size'],x['total_errors']), reverse=True)

with out_csv.open('w', encoding='utf-8', newline='') as f:
    w=csv.DictWriter(f, fieldnames=['namespace','flow','peak_type','cluster_size','total_errors','min_first_seen','max_last_seen','peak_ids','problem_keys'])
    w.writeheader(); w.writerows(agg)

lines=['# Peak review 24h - condensed','',f'- Generated UTC: {now.strftime("%Y-%m-%d %H:%M:%S")}',f'- Input rows: {len(rows)}',f'- Clusters: {len(agg)}','', '| namespace | flow | peak_type | cluster_size | total_errors | min_first_seen | max_last_seen | peak_ids |','|---|---|---|---:|---:|---|---|---|']
for a in agg:
    lines.append(f"| {a['namespace']} | {a['flow']} | {a['peak_type']} | {a['cluster_size']} | {a['total_errors']} | {a['min_first_seen']} | {a['max_last_seen']} | {a['peak_ids']} |")
out_md.write_text('\n'.join(lines), encoding='utf-8')
print(f'written_md={out_md}')
print(f'written_csv={out_csv}')
print(f'clusters={len(agg)}')
