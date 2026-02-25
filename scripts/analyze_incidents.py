#!/usr/bin/env python3
"""
ANALYZE INCIDENTS
=================

Hlavní skript pro incident analýzu.

Režimy:
1. 15-minute mode (real-time operational)
   python analyze_incidents.py --mode 15min --minutes 15

2. Daily mode (denní přehled)
   python analyze_incidents.py --mode daily --date 2026-01-21

3. Backfill mode (historická analýza)
   python analyze_incidents.py --mode backfill --days 14

Výstup:
- Co se rozbilo
- Proč (root cause)
- Kde (affected apps)
- Co s tím (recommended actions)

Exporty:
- Console
- Markdown
- JSON
- Slack webhook
"""

import os
import sys
import argparse
import requests
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from collections import defaultdict
import hashlib
import json

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'pipeline'))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

# Import incident analysis components
from incident_analysis import (
    IncidentAnalysisEngine,
    IncidentReportFormatter,
    IncidentAnalysisResult,
)
from incident_analysis.knowledge_base import KnowledgeBase, create_knowledge_base_template
from incident_analysis.knowledge_matcher import KnowledgeMatcher, TriageReportGenerator

# Import detection components
from pipeline.incident import (
    Incident, IncidentCollection, IncidentSeverity, IncidentCategory,
)


def guess_category(error_type: str, message: str) -> IncidentCategory:
    """Odhadne kategorii z error type a message"""
    text = f"{error_type} {message}".lower()
    
    # Database
    if any(kw in text for kw in ['hikaripool', 'connection pool', 'no available connection']):
        return IncidentCategory.DATABASE
    if any(kw in text for kw in ['deadlock', 'lock wait timeout', 'could not serialize']):
        return IncidentCategory.DATABASE
    if any(kw in text for kw in ['database', 'sql', 'jdbc', 'postgres', 'constraint violation']):
        return IncidentCategory.DATABASE
    
    # Timeout
    if any(kw in text for kw in ['timeout', 'timed out', 'read timed', 'connect timed']):
        return IncidentCategory.TIMEOUT
    
    # Network
    if any(kw in text for kw in ['connection refused', 'connection reset', 'econnrefused', 'econnreset']):
        return IncidentCategory.NETWORK
    if any(kw in text for kw in ['network', 'dns', 'broken pipe', 'socket']):
        return IncidentCategory.NETWORK
    
    # Auth
    if any(kw in text for kw in ['401', '403', 'unauthorized', 'forbidden', 'auth', 'token expired']):
        return IncidentCategory.AUTH
    
    # Business
    if any(kw in text for kw in ['not found', 'does not exist', '404', 'validation', 'invalid']):
        return IncidentCategory.BUSINESS
    if any(kw in text for kw in ['illegalargument', 'constraint', 'missing']):
        return IncidentCategory.BUSINESS
    
    # Memory
    if any(kw in text for kw in ['outofmemory', 'oom', 'heap', 'gc overhead']):
        return IncidentCategory.MEMORY
    
    # External
    if any(kw in text for kw in ['external', '503', '502', 'upstream', 'service unavailable', '429', 'rate limit']):
        return IncidentCategory.EXTERNAL
    
    return IncidentCategory.UNKNOWN


def guess_subcategory(category: IncidentCategory, error_type: str, message: str) -> str:
    """Odhadne subkategorii"""
    text = f"{error_type} {message}".lower()
    
    if category == IncidentCategory.DATABASE:
        if 'pool' in text or 'hikari' in text:
            return 'connection_pool'
        if 'deadlock' in text:
            return 'deadlock'
        if 'constraint' in text or 'duplicate' in text:
            return 'constraint'
        return 'general'
    
    if category == IncidentCategory.TIMEOUT:
        if 'read' in text:
            return 'read'
        if 'connect' in text:
            return 'connect'
        return 'general'
    
    if category == IncidentCategory.NETWORK:
        if 'refused' in text:
            return 'connection_refused'
        if 'reset' in text:
            return 'connection_reset'
        return 'general'
    
    if category == IncidentCategory.AUTH:
        if 'token' in text or 'expired' in text:
            return 'token_expired'
        if '403' in text or 'forbidden' in text:
            return 'forbidden'
        return 'unauthorized'
    
    if category == IncidentCategory.EXTERNAL:
        if '429' in text or 'rate' in text:
            return 'rate_limit'
        if '503' in text or 'unavailable' in text:
            return 'unavailable'
        return 'general'
    
    if category == IncidentCategory.BUSINESS:
        if 'not found' in text or 'does not exist' in text:
            return 'not_found'
        if 'validation' in text or 'invalid' in text:
            return 'validation'
        return 'general'
    
    return 'general'


def load_from_db(date_from: datetime, date_to: datetime, mode: str = '15min') -> IncidentCollection:
    """
    Načte z DB a vytvoří IncidentCollection.
    
    OPRAVY v5.2:
    - Fingerprint = category|subcategory|normalized_message (ne jen text)
    - Baseline = None pro 15min mode (nemá smysl)
    - Grouping = per-day pro daily/backfill mode
    - Incident ID = stabilní mezi běhy
    """
    import psycopg2
    import re
    
    print(f"📥 Loading from database...")
    print(f"   Period: {date_from.strftime('%Y-%m-%d %H:%M')} to {date_to.strftime('%Y-%m-%d %H:%M')}")
    print(f"   Mode: {mode}")
    
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
    )
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            timestamp, namespace, original_value, reference_value,
            is_new, is_spike, is_burst, is_cross_namespace,
            error_type, error_message, score, severity
        FROM ailog_peak.peak_investigation
        WHERE timestamp >= %s AND timestamp < %s
        ORDER BY timestamp
    """, (date_from, date_to))
    
    rows = cursor.fetchall()
    print(f"   Loaded {len(rows):,} records")
    
    cursor.close()
    conn.close()
    
    if not rows:
        return IncidentCollection(
            run_id=f"db-{date_from.strftime('%Y%m%d%H%M')}-{date_to.strftime('%Y%m%d%H%M')}",
            run_timestamp=datetime.now(timezone.utc),
            pipeline_version="1.0",
            input_records=0,
        )
    
    # === OPRAVA #1: Fingerprint = category|subcategory|normalized_message ===
    def compute_fingerprint(error_type: str, error_message: str) -> str:
        """
        Fingerprint reprezentuje TYP PROBLÉMU, ne jen text.
        Zahrnuje category a subcategory pro správné seskupování.
        """
        category = guess_category(error_type, error_message)
        subcategory = guess_subcategory(category, error_type, error_message)
        
        # Normalizace message - odstranění dynamických částí
        normalized = error_message or ''
        normalized = re.sub(r'\b\d+\b', 'N', normalized)  # Čísla → N
        normalized = re.sub(r'\b[0-9a-f]{8,}\b', 'ID', normalized, flags=re.I)  # Hexa IDs
        normalized = re.sub(r'\s+', ' ', normalized).strip()[:100]  # Zkrátit
        
        fp_src = f"{category.value}|{subcategory}|{normalized}"
        return hashlib.md5(fp_src.encode()).hexdigest()[:16]
    
    # === OPRAVA #3: Grouping podle mode ===
    grouped = defaultdict(list)
    for row in rows:
        (timestamp, namespace, original_value, reference_value,
         is_new, is_spike, is_burst, is_cross_namespace,
         error_type, error_message, score, severity) = row
        
        fp = compute_fingerprint(error_type, error_message)
        
        if mode == '15min':
            # Pro 15min: group jen by fingerprint
            group_key = fp
        else:
            # Pro daily/backfill: group by (fingerprint, day)
            day = timestamp.date() if timestamp else date_from.date()
            group_key = (fp, day)
        
        grouped[group_key].append(row)
    
    print(f"   Found {len(grouped):,} unique incident groups")
    
    collection = IncidentCollection(
        run_id=f"db-{date_from.strftime('%Y%m%d%H%M')}-{date_to.strftime('%Y%m%d%H%M')}",
        run_timestamp=datetime.now(timezone.utc),
        pipeline_version="1.0",
        input_records=len(rows),
    )
    
    # === OPRAVA #5: Version regex ===
    version_pattern = re.compile(r'^v?\d+\.\d+(?:\.\d+)?(?:-\w+)?$|^release-\d{4}\.\d{2}')
    
    for group_key, fp_rows in grouped.items():
        # Extrahuj fingerprint z group_key
        if mode == '15min':
            fp = group_key
            incident_day = date_from.date()
        else:
            fp, incident_day = group_key
        
        row = fp_rows[0]
        (timestamp, namespace, original_value, reference_value,
         is_new, is_spike, is_burst, is_cross_namespace,
         error_type, error_message, score, severity) = row
        
        namespaces = list(set(r[1] for r in fp_rows if r[1]))
        total_count = int(sum(r[2] or 0 for r in fp_rows))
        
        timestamps = [r[0] for r in fp_rows if r[0]]
        first_seen = min(timestamps) if timestamps else None
        last_seen = max(timestamps) if timestamps else None
        
        # === OPRAVA #5: Verze - explicitní regex, ne heuristika ===
        versions = []
        for ns in namespaces:
            parts = ns.split('-')
            for p in parts:
                if version_pattern.match(p):
                    versions.append(p)
        versions = list(set(versions))
        
        # === OPRAVA #7: Stabilní Incident ID ===
        # Formát: INC-{date}-{fp[:6]} pro jednoznačnou identifikaci
        inc_id = f"INC-{incident_day.strftime('%Y%m%d')}-{fp[:6]}"
        
        inc = Incident(
            id=inc_id,
            fingerprint=fp,
            pipeline_version="1.0",
        )
        
        inc.normalized_message = error_message or ''
        inc.error_type = error_type or 'Unknown'
        inc.namespaces = namespaces
        inc.apps = list(set(ns.replace('-app', '').rsplit('-', 2)[0] for ns in namespaces[:10]))
        inc.versions = versions
        
        inc.time.first_seen = first_seen
        inc.time.last_seen = last_seen
        if first_seen and last_seen:
            inc.time.duration_sec = int((last_seen - first_seen).total_seconds())
        
        inc.stats.current_count = total_count
        
        # === OPRAVA #2: Baseline = None pro 15min mode ===
        if mode == '15min':
            # Pro real-time analýzu baseline nemá smysl
            inc.stats.current_rate = total_count
            inc.stats.baseline_rate = None
            inc.stats.trend_ratio = None
        else:
            # Pro daily/backfill můžeme použít reference_value
            avg_ref = sum(r[3] or 0 for r in fp_rows) / len(fp_rows) if fp_rows else 0
            duration_min = max(1, inc.time.duration_sec / 60) if inc.time.duration_sec else 1
            inc.stats.current_rate = total_count / duration_min
            inc.stats.baseline_rate = avg_ref if avg_ref > 0 else None
            inc.stats.trend_ratio = (inc.stats.current_rate / avg_ref) if avg_ref > 0 else None
        
        inc.flags.is_new = any(r[4] for r in fp_rows)
        inc.flags.is_spike = any(r[5] for r in fp_rows)
        inc.flags.is_burst = any(r[6] for r in fp_rows)
        inc.flags.is_cross_namespace = any(r[7] for r in fp_rows)
        
        inc.score = max(r[10] or 0 for r in fp_rows)
        
        sev_map = {
            'critical': IncidentSeverity.CRITICAL,
            'high': IncidentSeverity.HIGH,
            'medium': IncidentSeverity.MEDIUM,
            'low': IncidentSeverity.LOW,
            'info': IncidentSeverity.INFO,
        }
        inc.severity = sev_map.get(severity, IncidentSeverity.INFO)
        
        inc.category = guess_category(error_type, error_message)
        inc.subcategory = guess_subcategory(inc.category, error_type, error_message)
        
        collection.add_incident(inc)
    
    print(f"   Created {collection.total_incidents:,} incidents")
    return collection


def send_to_slack(webhook_url: str, message_json: str) -> bool:
    """
    Odešle zprávu do Slacku.
    
    OPRAVA v5.2: Timeout 3s (ne 10s) aby neblokoval 15min cron.
    """
    try:
        response = requests.post(
            webhook_url,
            data=message_json,
            headers={'Content-Type': 'application/json'},
            timeout=3  # OPRAVA: Krátký timeout pro cron
        )
        return response.status_code == 200
    except requests.exceptions.Timeout:
        print(f"   ⚠️ Slack timeout (3s) - continuing")
        return False
    except Exception as e:
        print(f"   ❌ Slack error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Analyze incidents')
    parser.add_argument('--mode', choices=['15min', 'daily', 'backfill'], default='15min',
                       help='Analysis mode')
    parser.add_argument('--minutes', type=int, default=15, 
                       help='Minutes to analyze (for 15min mode)')
    parser.add_argument('--date', type=str,
                       help='Date to analyze (for daily mode, format: YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=1,
                       help='Days to analyze (for backfill mode)')
    parser.add_argument('--date-from', type=str,
                       help='Start date (format: YYYY-MM-DD)')
    parser.add_argument('--date-to', type=str,
                       help='End date (format: YYYY-MM-DD)')
    parser.add_argument('--output', type=str, default='./reports',
                       help='Output directory')
    parser.add_argument('--format', choices=['console', 'all'], default='all',
                       help='Output format')
    parser.add_argument('--slack-webhook', type=str,
                       help='Slack webhook URL')
    parser.add_argument('--slack-channel', type=str, default='#alerts',
                       help='Slack channel')
    parser.add_argument('--only-critical', action='store_true',
                       help='Show only critical/high incidents')
    parser.add_argument('--knowledge-dir', type=str, default='./knowledge',
                       help='Path to knowledge base directory')
    parser.add_argument('--init-knowledge', action='store_true',
                       help='Initialize empty knowledge base')
    parser.add_argument('--triage', action='store_true',
                       help='Generate triage report for NEW incidents')
    
    args = parser.parse_args()
    
    # Init knowledge base if requested
    if args.init_knowledge:
        create_knowledge_base_template(args.knowledge_dir)
        return 0
    
    # Determine time range based on mode
    now = datetime.now(timezone.utc)
    
    if args.mode == '15min':
        date_to = now
        date_from = now - timedelta(minutes=args.minutes)
    elif args.mode == 'daily':
        if args.date:
            target_date = datetime.strptime(args.date, '%Y-%m-%d')
        else:
            target_date = now - timedelta(days=1)
        date_from = target_date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
        date_to = date_from + timedelta(days=1)
    else:  # backfill
        if args.date_from and args.date_to:
            date_from = datetime.strptime(args.date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            date_to = datetime.strptime(args.date_to, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        else:
            date_to = now.replace(hour=0, minute=0, second=0, microsecond=0)
            date_from = date_to - timedelta(days=args.days)
    
    # Load data - OPRAVA: předáváme mode pro správný grouping
    collection = load_from_db(date_from, date_to, mode=args.mode)
    
    if collection.total_incidents == 0:
        print("✅ No data to analyze")
        return 0
    
    # Analyze
    print(f"\n🔍 Analyzing incidents...")
    engine = IncidentAnalysisEngine()
    result = engine.analyze(
        collection.incidents,
        analysis_start=date_from,
        analysis_end=date_to,
    )
    
    print(f"   Found {result.total_incidents} incident(s)")
    print(f"   Critical: {result.critical_count} | High: {result.high_count} | Medium: {result.medium_count}")
    print(f"   Analysis time: {result.analysis_duration_ms}ms")
    
    # Knowledge matching
    kb = KnowledgeBase(args.knowledge_dir)
    matcher = None
    if Path(args.knowledge_dir).exists():
        kb.load()
        print(f"\n📚 Knowledge base loaded: {kb.error_count} known errors, {kb.peak_count} known peaks")
        
        matcher = KnowledgeMatcher(kb)
        result = matcher.enrich_incidents(result)
        
        # === OPRAVA #4: Přepočet priority PO knowledge matching ===
        # Priority musí znát knowledge_status (KNOWN vs NEW)
        from incident_analysis.models import calculate_priority
        for incident in result.incidents:
            incident.priority, incident.priority_reasons = calculate_priority(
                knowledge_status=incident.knowledge_status,
                severity=incident.severity,
                blast_radius=incident.scope.blast_radius,
                is_worsening=False,  # TODO: porovnat s předchozím během
            )
        
        stats = matcher.get_stats(result)
        print(f"   Matching: {stats['known']} KNOWN, {stats['new']} NEW")
        print(f"   Priority recalculated after knowledge matching")
    else:
        print(f"\n⚠️ Knowledge base not found at {args.knowledge_dir}")
        print(f"   Run with --init-knowledge to create template")
    
    # Filter if needed
    if args.only_critical:
        result.incidents = [i for i in result.incidents 
                          if i.severity.value in ('critical', 'high')]
        result.total_incidents = len(result.incidents)
    
    # Format output
    formatter = IncidentReportFormatter()
    
    if args.mode == '15min':
        output = formatter.format_15min(result)
    else:
        output = formatter.format_daily(result)
    
    print("\n" + output)
    
    # Save files
    if args.format == 'all':
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        files = formatter.save_all(result, str(output_dir), mode=args.mode)
        print(f"\n📄 Reports saved:")
        for fmt, path in files.items():
            print(f"   {fmt}: {path}")
    
    # Send to Slack
    if args.slack_webhook:
        print(f"\n📤 Sending to Slack...")
        slack_json = formatter.to_slack_json(result, args.slack_channel)
        if send_to_slack(args.slack_webhook, slack_json):
            print(f"   ✅ Sent to {args.slack_channel}")
        else:
            print(f"   ❌ Failed")
    
    # Triage report
    if args.triage:
        if matcher is not None:
            triage_gen = TriageReportGenerator(matcher)
            triage_report = triage_gen.generate_triage_report(result)
            print("\n" + triage_report)
            
            # Save triage report
            triage_path = Path(args.output) / f"triage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(triage_path, 'w') as f:
                f.write(triage_report)
                
                # Add suggested YAML for each NEW incident
                new_incidents = matcher.get_new_incidents(result)
                if new_incidents:
                    f.write("\n\n")
                    f.write("=" * 70 + "\n")
                    f.write("SUGGESTED YAML FOR NEW INCIDENTS\n")
                    f.write("=" * 70 + "\n")
                    for i, inc in enumerate(new_incidents, 1):
                        f.write(f"\n# --- Incident {i}: {inc.incident_id} ---\n")
                        f.write(triage_gen.generate_suggested_yaml(inc, f"KE-{kb.error_count + i:03d}"))
                        f.write("\n")
            
            print(f"   📝 Triage report: {triage_path}")
        else:
            print(f"\n⚠️ Cannot generate triage - knowledge base not found")
    
    print("\n✅ Done")
    return 0


if __name__ == '__main__':
    sys.exit(main())
