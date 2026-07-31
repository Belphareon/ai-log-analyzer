#!/usr/bin/env python3
"""
ES Fetcher - Truly unlimited data fetching via search_after
Uses HTTPBasicAuth + search_after for cursor-based pagination
No artificial limits - fetches ALL records in date range
"""

import requests
from requests.auth import HTTPBasicAuth
import json
import os
import time
import urllib3
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import yaml

urllib3.disable_warnings()
load_dotenv()

BASE_URL = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')

# ============================================================================
# OOM PROTECTION (extrémní okna s miliony logů)
# ============================================================================
# Init/regular/backfill pody dříve padaly na OOM, když okno obsahovalo miliony
# logů (celý den / dlouhý rozsah). Tady fetch hlídá paměť a počet záznamů a
# raději přestane stahovat (degradovaná, ale živá analýza) než aby ho OOM zabil.
try:
    import resource as _resource
except ImportError:  # ne-Linux (dev)
    _resource = None

# Hard backstop na počet záznamů (když nejde detekovat cgroup limit).
MAX_FETCH_RECORDS = int(os.getenv('MAX_FETCH_RECORDS', '2000000'))
# Rozpočet paměti = % z detekovaného cgroup limitu podu. 50 % nechává hlavu
# pro 2× expanzi v pipeline (raw dicts + NormalizedRecord kopie).
FETCH_MEMORY_BUDGET_PCT = float(os.getenv('FETCH_MEMORY_BUDGET_PCT', '50'))
# Explicitní override v MB (0 = auto z cgroup).
FETCH_MEMORY_BUDGET_MB = int(os.getenv('FETCH_MEMORY_BUDGET_MB', '0'))
# Absolutní strop RSS chrání pod, i když fetch začíná s vysokou baseline.
FETCH_MEMORY_CEILING_PCT = float(os.getenv('FETCH_MEMORY_CEILING_PCT', '90'))

# Poslední výsledek (pro volající: byla data oříznuta?).
LAST_FETCH_STATS = {
    'truncated': False,
    'failed': False,
    'complete': False,
    'reason': None,
    'fetched': 0,
    'expected': None,
}


def _source_value(source, *paths, default=None):
    """Read the first non-null value from dotted or nested ES source fields."""
    for path in paths:
        if path in source and source[path] is not None:
            return source[path]

        current = source
        for part in path.split('.'):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return default


def _load_monitored_namespaces():
    env_namespaces = os.getenv('MONITORED_NAMESPACES', '').strip()
    if env_namespaces:
        return list(dict.fromkeys(
            namespace.strip()
            for namespace in env_namespaces.split(',')
            if namespace.strip()
        ))

    config_path = Path(__file__).resolve().parents[2] / 'config' / 'namespaces.yaml'
    try:
        config = yaml.safe_load(config_path.read_text(encoding='utf-8')) or {}
    except (OSError, yaml.YAMLError) as error:
        print(f"   ❌ Cannot load monitored namespaces from {config_path}: {error}")
        return []
    return list(dict.fromkeys(
        namespace.strip()
        for namespace in config.get('namespaces', [])
        if isinstance(namespace, str) and namespace.strip()
    ))


def _source_to_error(source, message_limit=500):
    """Preserve fields required by Phase A for nested and dotted ES mappings."""
    message = _source_value(source, 'message', default='')
    if isinstance(message, dict):
        message = json.dumps(message)
    if not isinstance(message, str):
        message = str(message)
    message = message[:message_limit]

    application = _source_value(
        source, 'application.name', 'service.name', default='unknown'
    ) or 'unknown'
    application_version = _source_value(
        source, 'application.version', 'app_version', 'appVersion'
    )
    namespace = _source_value(source, 'kubernetes.namespace', default='unknown') or 'unknown'
    exception = _source_value(source, 'exception', default={})
    error = _source_value(source, 'error', default={})
    exception = exception if isinstance(exception, dict) else {}
    error = error if isinstance(error, dict) else {}
    trace_id = _source_value(source, 'traceId', 'trace.id', default='') or ''

    return {
        'message': message,
        'application': application,
        'application.name': application,
        'application.version': application_version,
        'app_version': application_version,
        'cluster': _source_value(source, 'topic', default='unknown') or 'unknown',
        'namespace': namespace,
        'kubernetes.namespace': namespace,
        'timestamp': _source_value(source, '@timestamp', default='') or '',
        'trace_id': trace_id,
        'traceId': trace_id,
        'spanId': _source_value(source, 'spanId', 'span.id', default='') or '',
        'parentId': _source_value(source, 'parentId', 'parent.id', default='') or '',
        'originator_application': _source_value(
            source, 'context.originatorApplication', default=''
        ) or '',
        'pcbs_master': _source_value(
            source, 'kubernetes.labels.eamApplication', default='unknown'
        ) or 'unknown',
        'exception': exception,
        'exception.type': _source_value(source, 'exception.type', default='') or '',
        'error': error,
        'error.type': _source_value(source, 'error.type', default='') or '',
        'error_type': _source_value(source, 'error_type', default='') or '',
        'errorType': _source_value(source, 'errorType', default='') or '',
        'error.message': _source_value(source, 'error.message', default='') or '',
        'http.status_code': _source_value(source, 'http.status_code'),
        'stack_trace': _source_value(source, 'stack_trace', 'stackTrace', default='') or '',
        'service.name': _source_value(source, 'service.name', default='') or '',
    }


def _build_error_query(date_from, date_to, batch_size, namespaces):
    return {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": date_from, "lt": date_to}}},
                    {"term": {"level": "ERROR"}},
                ],
                "filter": [
                    {"terms": {"kubernetes.namespace": namespaces}},
                ],
            }
        },
        "sort": [
            {"@timestamp": {"order": "asc"}},
            {"_shard_doc": {"order": "asc"}},
        ],
        "size": batch_size,
        "_source": [
            "message",
            "application",
            "application.name",
            "application.version",
            "app_version",
            "appVersion",
            "@timestamp",
            "traceId",
            "trace.id",
            "spanId",
            "span.id",
            "parentId",
            "parent.id",
            "kubernetes.labels.eamApplication",
            "kubernetes.namespace",
            "topic",
            "exception",
            "exception.type",
            "error",
            "error.type",
            "error_type",
            "errorType",
            "error.message",
            "service.name",
            "http.status_code",
            "stack_trace",
            "stackTrace",
            "context.originatorApplication",
        ],
    }


def _detect_cgroup_memory_limit_mb():
    """Přečte memory limit podu/kontejneru z cgroup (v2, pak v1). None = neomezeno."""
    for path in (
        '/sys/fs/cgroup/memory.max',                    # cgroup v2
        '/sys/fs/cgroup/memory/memory.limit_in_bytes',  # cgroup v1
    ):
        try:
            with open(path) as f:
                raw = f.read().strip()
        except OSError:
            continue
        if raw in ('max', ''):
            continue
        try:
            limit = int(raw)
        except ValueError:
            continue
        # Ignoruj "bez limitu" sentinely (obrovské hodnoty).
        if 0 < limit < (1 << 62):
            return limit / (1024 * 1024)
    return None


def _process_rss_mb():
    """AKTUÁLNÍ (ne peak) RSS procesu v MB.

    Dřív se používalo ru_maxrss (peak za celý život procesu) — to je ale
    monotónní a NIKDY neklesá, takže zahrnovalo i paměť, kterou volající
    (regular_phase.py) spotřeboval PŘED fetchem na yaml.safe_load velkého
    known_peaks.yaml/known_problems.yaml registru (desítky MB souborů, které
    se v čistém Pythonu nafouknou na stovky MB-1+GB objektů). To způsobovalo
    falešně brzké OOM guard triggery i při malých regular-phase oknech.
    Čteme proto live VmRSS z /proc/self/status (Linux); jinde fallback na
    ru_maxrss (peak) jako konzervativní odhad.
    """
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    if _resource is None:
        return 0.0
    return _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _fetch_memory_budget_mb():
    """Efektivní paměťový rozpočet: explicitní MB, jinak % z detekovaného limitu."""
    if FETCH_MEMORY_BUDGET_MB > 0:
        return float(FETCH_MEMORY_BUDGET_MB)
    limit = _detect_cgroup_memory_limit_mb()
    if limit and limit > 0:
        return limit * (FETCH_MEMORY_BUDGET_PCT / 100.0)
    return 0.0  # nedetekovatelné a bez override → vypnuto (jen record cap chrání)


def _fetch_memory_ceiling_mb():
    """Absolutní RSS strop jako procento cgroup limitu; 0 znamená nedetekovatelný."""
    limit = _detect_cgroup_memory_limit_mb()
    if limit and limit > 0:
        return limit * (FETCH_MEMORY_CEILING_PCT / 100.0)
    return 0.0


def _should_stop_fetch(
    record_count,
    rss_mb,
    budget_mb,
    max_records=None,
    baseline_mb=0.0,
    memory_ceiling_mb=0.0,
):
    """Čistá (testovatelná) logika OOM guardu. Vrací důvod (str) nebo None.

    budget_mb je rozpočet PRO SAMOTNÝ FETCH — porovnává se proti RŮSTU RSS
    (rss_mb - baseline_mb), ne proti absolutní hodnotě. baseline_mb je RSS
    naměřené TĚSNĚ PŘED spuštěním fetche (viz fetch_unlimited), takže paměť
    už spotřebovaná voláním kódem (registry, baseline loader, ...) guard
    nesprávně nepenalizuje.
    """
    cap = max_records if max_records is not None else MAX_FETCH_RECORDS
    if cap and record_count >= cap:
        return f"record cap {cap:,}"
    if memory_ceiling_mb > 0 and rss_mb >= memory_ceiling_mb:
        return f"memory ceiling {memory_ceiling_mb:.0f}MB (RSS {rss_mb:.0f}MB)"
    growth_mb = rss_mb - baseline_mb
    if budget_mb > 0 and growth_mb >= budget_mb:
        return f"memory budget {budget_mb:.0f}MB (fetch growth {growth_mb:.0f}MB, RSS {rss_mb:.0f}MB)"
    return None


def fetch_unlimited(
    date_from,
    date_to,
    batch_size=10000,
    retry=3,
    page_consumer=None,
    collect_results=True,
    stats_out=None,
):
    """Fetch ERROR logs using search_after pagination.

    ``page_consumer`` receives each parsed page. Set ``collect_results=False``
    for bounded-memory callers that consume pages incrementally.
    """
    
    all_errors = []
    batch_num = 0
    search_after = None
    expected_total = None
    fetched_count = 0

    # OOM guard: rozpočet spočítáme jednou na začátku. baseline_rss_mb = paměť,
    # kterou volající kód (registry.load(), baseline loader, ...) spotřeboval
    # PŘED fetchem — guard hlídá jen RŮST RSS způsobený samotným fetchem.
    mem_budget_mb = _fetch_memory_budget_mb()
    mem_ceiling_mb = _fetch_memory_ceiling_mb()
    baseline_rss_mb = _process_rss_mb()
    truncated_reason = None
    def update_stats(values):
        LAST_FETCH_STATS.update(values)
        if stats_out is not None:
            stats_out.update(values)

    update_stats({
        'truncated': False,
        'failed': False,
        'complete': False,
        'reason': None,
        'fetched': 0,
        'expected': None,
    })
    monitored_namespaces = _load_monitored_namespaces()
    if not monitored_namespaces:
        update_stats({'failed': True, 'reason': 'no monitored namespaces configured'})
        print("   ❌ Fetch aborted: no monitored namespaces configured")
        return None
    if not collect_results:
        print(
            "   Streaming mode: pages are consumed immediately; fetch memory/record "
            "caps do not truncate input"
        )
    elif mem_budget_mb > 0 or mem_ceiling_mb > 0:
        print(
            f"   🧷 OOM guard: memory budget {mem_budget_mb:.0f}MB for fetch growth "
            f"(baseline RSS {baseline_rss_mb:.0f}MB excluded), absolute RSS ceiling "
            f"{mem_ceiling_mb:.0f}MB, record cap {MAX_FETCH_RECORDS:,}"
        )
    print("🔄 Fetcher - UNLIMITED via search_after")
    print(f"   Time range: {date_from} to {date_to}")
    print(f"   Batch size: {batch_size:,}")
    print()

    session = requests.Session()
    session.auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    session.verify = False
    session.trust_env = True

    pit_id = None
    pit_keep_alive = '5m'

    try:
        pit_resp = session.post(f"{BASE_URL}/{INDICES}/_pit?keep_alive={pit_keep_alive}", timeout=120)
        if pit_resp.status_code != 200:
            reason = f"PIT open failed ({pit_resp.status_code})"
            update_stats({'failed': True, 'reason': reason})
            print(f"   ❌ {reason}; fetch aborted")
            return None
        pit_id = pit_resp.json().get('id')
        if not pit_id:
            reason = "PIT open response did not contain an id"
            update_stats({'failed': True, 'reason': reason})
            print(f"   ❌ {reason}; fetch aborted")
            return None

        while True:
            batch_num += 1
            query = _build_error_query(
                date_from, date_to, batch_size, monitored_namespaces
            )
            query["track_total_hits"] = batch_num == 1
            query["pit"] = {"id": pit_id, "keep_alive": pit_keep_alive}

            if search_after:
                query["search_after"] = search_after
            
            # Retry logic
            success = False
            for attempt in range(retry):
                try:
                    resp = session.post(
                        f"{BASE_URL}/_search",
                        json=query,
                        timeout=120,
                    )
                    
                    if resp.status_code == 200:
                        success = True
                        break
                    elif resp.status_code in [401, 403]:
                        if attempt < retry - 1:
                            time.sleep(2)
                            continue
                        else:
                            print(f"   ❌ Auth failed after {retry} retries")
                            update_stats({'failed': True, 'reason': 'authentication failed'})
                            return None
                    else:
                        error_msg = resp.json().get('error', {}).get('reason', 'Unknown error')
                        print(f"   ❌ Error {resp.status_code}: {error_msg[:100]}")
                        update_stats({
                            'failed': True,
                            'reason': f'Elasticsearch search failed ({resp.status_code})',
                        })
                        return None
                except Exception as e:
                    if attempt < retry - 1:
                        time.sleep(1)
                        continue
                    else:
                        print(f"   ❌ Exception: {e}")
                        update_stats({'failed': True, 'reason': f'Elasticsearch request failed: {e}'})
                        return None
            
            if not success:
                break
            
            data = resp.json()
            hits = data['hits']['hits']
            if expected_total is None:
                total_obj = data.get('hits', {}).get('total', 0)
                if isinstance(total_obj, dict):
                    expected_total = int(total_obj.get('value', 0))
                else:
                    expected_total = int(total_obj or 0)
                print(f"📊 Expected total hits: {expected_total:,}")

            if pit_id and isinstance(data.get('pit_id'), str):
                pit_id = data.get('pit_id')
            
            if not hits:
                print(f"🔄 Batch {batch_num:3d}... ✅ DONE (no more hits)")
                break
            
            # Process hits
            page_errors = [
                _source_to_error(hit.get('_source', {}))
                for hit in hits
            ]

            fetched_count += len(page_errors)
            if page_consumer is not None:
                page_consumer(page_errors)
            if collect_results:
                all_errors.extend(page_errors)

            print(f"🔄 Batch {batch_num:3d}... ✅ {len(hits):,} | Total: {fetched_count:,}")

            # === OOM PROTECTION: zastav fetch, než nás zabije OOM killer ===
            truncated_reason = None
            if collect_results:
                truncated_reason = _should_stop_fetch(
                    fetched_count,
                    _process_rss_mb(),
                    mem_budget_mb,
                    baseline_mb=baseline_rss_mb,
                    memory_ceiling_mb=mem_ceiling_mb,
                )
            if truncated_reason:
                total_str = f"{expected_total:,}" if expected_total else "?"
                print(
                    f"   ⚠️ OOM GUARD: stopping fetch early — {truncated_reason}. "
                    f"Fetched {fetched_count:,} of ~{total_str} total. "
                    f"Analysis will be PARTIAL (degraded, but pod survives)."
                )
                break

            # Set search_after for next iteration (last document's sort values)
            if len(hits) < batch_size:
                # Got less than batch size = we're at the end
                break
            
            search_after = hits[-1]['sort']
    finally:
        if pit_id:
            try:
                session.delete(f"{BASE_URL}/_pit", json={"id": pit_id}, timeout=30)
            except Exception:
                pass
    
        session.close()

    print()
    print(f"✅ Total fetched: {fetched_count:,} errors")
    update_stats({
        'truncated': bool(truncated_reason),
        'failed': False,
        'complete': (
            not truncated_reason
            and expected_total is not None
            and fetched_count == expected_total
        ),
        'reason': truncated_reason,
        'fetched': fetched_count,
        'expected': expected_total,
    })
    if truncated_reason:
        print(
            f"⚠️ PARTIAL fetch ({truncated_reason}): analyzed {fetched_count:,} "
            f"of ~{expected_total or '?'} — counts/peaks are a LOWER BOUND."
        )
    if expected_total is not None:
        if truncated_reason:
            pass  # mismatch je z\u00e1m\u011brn\u00fd (OOM guard), u\u017e nahl\u00e1\u0161eno v\u00fd\u0161e
        elif fetched_count == expected_total:
            print("✅ Completeness check: fetched count matches hits.total")
        else:
            print(
                f"⚠️ Completeness check mismatch: expected {expected_total:,}, fetched {fetched_count:,}"
            )
            update_stats({
                'failed': True,
                'complete': False,
                'reason': 'fetched count does not match hits.total',
            })
            return None
    return all_errors

def fetch_trace_context(trace_ids, date_from, date_to, max_events=3000, retry=2):
    """Fetch ALL levels (ne jen ERROR) pro konkrétní trace_ids.

    Účel (#3): primární sběr běží jen na ERROR (fetch_unlimited), ale pro
    REPREZENTATIVNÍ trace reportovaných problémů dotáhneme kompletní balík eventů
    VŠECH levelů (WARN/INFO/DEBUG). Skutečná příčina totiž často PŘEDCHÁZÍ prvnímu
    ERRORu – tady ji zachytíme.

    Returns: dict[trace_id] -> list[event dict] (message, application, namespace,
    timestamp, trace_id, level, error_type). Časově NEseřazeno (řadí konzument).
    """
    if not trace_ids or not ES_PASSWORD:
        return {}
    ids = [t for t in dict.fromkeys(trace_ids) if t][:200]  # dedup + cap
    if not ids:
        return {}

    session = requests.Session()
    session.auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    session.verify = False
    session.trust_env = True

    out = {}
    try:
        namespaces = _load_monitored_namespaces()
        if not namespaces:
            print("   ⚠️ trace context fetch aborted: no monitored namespaces configured")
            return {}
        query = {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": date_from, "lt": date_to}}},
                {"terms": {"traceId": ids}},
            ], "filter": [
                {"terms": {"kubernetes.namespace": namespaces}},
            ]}},
            "sort": [{"@timestamp": {"order": "asc"}}],
            "size": max_events,
            "_source": [
                "message", "application", "application.name", "application.version",
                "@timestamp", "traceId", "trace.id", "spanId", "span.id",
                "parentId", "parent.id",
                "level", "kubernetes.namespace",
                "exception", "exception.type", "error", "error.type",
                "error_type", "errorType", "http.status_code", "stack_trace",
                "context.originatorApplication",
            ],
        }
        resp = None
        for attempt in range(retry):
            try:
                resp = session.post(f"{BASE_URL}/{INDICES}/_search", json=query, timeout=120)
                if resp.status_code == 200:
                    break
                if resp.status_code in (401, 403) and attempt < retry - 1:
                    time.sleep(2)
                    continue
                print(f"   ⚠️ trace context fetch error {resp.status_code}")
                return {}
            except requests.RequestException as e:
                if attempt < retry - 1:
                    time.sleep(1)
                    continue
                print(f"   ⚠️ trace context fetch exception: {e}")
                return {}
        if resp is None or resp.status_code != 200:
            return {}
        for hit in resp.json().get('hits', {}).get('hits', []):
            s = hit.get('_source', {})
            tid = _source_value(s, 'traceId', 'trace.id', default='') or ''
            if not tid:
                continue
            event = _source_to_error(s, message_limit=1000)
            event['level'] = _source_value(s, 'level', default='') or ''
            out.setdefault(tid, []).append(event)
    finally:
        session.close()
    return out


def main():
    parser = argparse.ArgumentParser(description='Fetch ERROR logs from ES (unlimited, search_after)')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format, e.g., 2025-12-02T07:30:00Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format, e.g., 2025-12-02T10:30:00Z)')
    parser.add_argument('--batch-size', type=int, default=10000, help='Batch size per request (default 10K)')
    parser.add_argument('--output', required=True, help='Output JSON file')

    args = parser.parse_args()

    all_errors = fetch_unlimited(args.date_from, args.date_to, batch_size=args.batch_size)
    
    if all_errors is None:
        print("❌ Fetch failed!")
        return 1

    # Save result
    result = {
        'period_start_utc': args.date_from,
        'period_end_utc': args.date_to,
        'fetched_errors': len(all_errors),
        'batch_size': args.batch_size,
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'errors': all_errors
    }

    with open(args.output, 'w') as f:
        json.dump(result, f, default=str)

    file_size_mb = len(json.dumps(result)) / (1024*1024)
    print(f"💾 Saved to {args.output} ({file_size_mb:.1f}MB)")

    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
