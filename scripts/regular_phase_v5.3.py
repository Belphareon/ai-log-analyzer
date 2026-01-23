#!/usr/bin/env python3
"""
REGULAR PHASE - Hlavní pipeline pro cron (každých 15 minut)
===========================================================

Spouští se každých 15 minut pro zpracování nových dat s peak detection.

Použití:
    python regular_phase.py
    python regular_phase.py --output data/reports/
    python regular_phase.py --quiet  # pro cron
"""

import os
import sys
import argparse
import json
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR / 'v4'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from core.fetch_unlimited import fetch_unlimited

# Import V4 pipeline
from v4.pipeline_v4 import PipelineV4
from v4.phase_f_report import PhaseF_Report
from v4.incident import IncidentSeverity

# DB
try:
    import psycopg2
    HAS_DB = True
except ImportError:
    HAS_DB = False

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

# Incident Analysis v5.3
try:
    from incident_analysis import (
        IncidentAnalysisEngine,
        IncidentReportFormatter,
        IncidentAnalysisResult,
    )
    from incident_analysis.knowledge_base import KnowledgeBase
    from incident_analysis.knowledge_matcher import KnowledgeMatcher
    from incident_analysis.models import calculate_priority
    HAS_INCIDENT_ANALYSIS = True
except ImportError as e:
    HAS_INCIDENT_ANALYSIS = False
    print(f"⚠️ Incident Analysis import failed: {e}")


def run_incident_analysis(collection, window_start, window_end, output_dir=None, quiet=False):
    """
    Spustí Incident Analysis na výsledcích pipeline.
    
    OPRAVA v5.3: Report se generuje VŽDY, i když nejsou incidenty.
    
    Args:
        collection: IncidentCollection z pipeline
        window_start: Začátek okna
        window_end: Konec okna
        output_dir: Adresář pro uložení reportu (pokud None, neukládá se)
        quiet: Tichý režim
    
    Returns:
        str: Formátovaný report (nikdy None!)
    """
    if not HAS_INCIDENT_ANALYSIS:
        if not quiet:
            print("   ⚠️  Incident Analysis not available (missing module)")
        return "⚠️ Incident Analysis module not available"
    
    formatter = IncidentReportFormatter()
    
    # Pokud nejsou incidenty, generuj prázdný report
    if not collection.incidents:
        result = IncidentAnalysisResult(
            incidents=[],
            total_incidents=0,
            analysis_start=window_start,
            analysis_end=window_end,
        )
        report = formatter.format_15min(result)
        _save_report(report, output_dir, "15min", quiet)
        return report
    
    try:
        # 1. Analyzuj incidenty
        engine = IncidentAnalysisEngine()
        result = engine.analyze(
            collection.incidents,
            analysis_start=window_start,
            analysis_end=window_end,
        )
        
        # 2. Knowledge matching
        kb_path = SCRIPT_DIR.parent / 'config' / 'known_issues'
        if kb_path.exists():
            kb = KnowledgeBase(str(kb_path))
            kb.load()
            
            matcher = KnowledgeMatcher(kb)
            result = matcher.enrich_incidents(result)
            
            # Přepočti priority po knowledge matching
            for incident in result.incidents:
                incident.priority, incident.priority_reasons = calculate_priority(
                    knowledge_status=incident.knowledge_status,
                    severity=incident.severity,
                    blast_radius=incident.scope.blast_radius,
                    namespace_count=len(incident.scope.namespaces),
                    propagated=incident.propagation.propagated,
                    propagation_time_sec=incident.propagation.propagation_time_sec,
                )
        
        # 3. Formátuj report
        report = formatter.format_15min(result)
        
        # 4. Ulož report do souboru
        _save_report(report, output_dir, "15min", quiet)
        
        # 5. Aktualizuj registry (append-only)
        _update_registry(result, SCRIPT_DIR.parent / 'registry', quiet)
        
        return report
        
    except Exception as e:
        if not quiet:
            print(f"   ⚠️  Incident Analysis error: {e}")
            import traceback
            traceback.print_exc()
        # I při chybě vrať nějaký report
        return f"⚠️ Incident Analysis error: {e}"


def _save_report(report: str, output_dir, mode: str, quiet: bool):
    """Uloží report do souboru."""
    if not output_dir:
        return
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"incident_analysis_{mode}_{timestamp}.txt"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)
    
    if not quiet:
        print(f"   📄 Report saved: {filepath}")


def _update_registry(result: 'IncidentAnalysisResult', registry_dir: Path, quiet: bool):
    """
    Aktualizuje append-only registry known errors/peaks.
    
    Pravidla:
    - Nový fingerprint → nový záznam
    - Existující fingerprint → aktualizuj last_seen, occurrences++
    - Nikdy se nic nemaže
    - Řazení od nejnovějšího (last_seen DESC)
    """
    if not result.incidents:
        return
    
    registry_dir.mkdir(parents=True, exist_ok=True)
    
    errors_yaml = registry_dir / 'known_errors.yaml'
    errors_md = registry_dir / 'known_errors.md'
    
    # Načti existující registry
    existing = {}
    if errors_yaml.exists():
        try:
            with open(errors_yaml, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or []
                for item in data:
                    if 'fingerprint' in item:
                        existing[item['fingerprint']] = item
        except Exception as e:
            if not quiet:
                print(f"   ⚠️  Registry load error: {e}")
    
    now = datetime.now().isoformat()
    updated = False
    
    # Zpracuj každý incident
    for incident in result.incidents:
        for fp in incident.scope.fingerprints:
            if fp in existing:
                # Aktualizuj existující
                entry = existing[fp]
                entry['last_seen'] = now
                entry['occurrences'] = entry.get('occurrences', 1) + 1
                
                # Přidej nové apps/namespaces/versions
                for app in incident.scope.apps:
                    if app not in entry.get('affected_apps', []):
                        entry.setdefault('affected_apps', []).append(app)
                for ns in incident.scope.namespaces:
                    if ns not in entry.get('affected_namespaces', []):
                        entry.setdefault('affected_namespaces', []).append(ns)
                for app, versions in incident.scope.app_versions.items():
                    for v in versions:
                        if v not in entry.get('versions_seen', []):
                            entry.setdefault('versions_seen', []).append(v)
                
                updated = True
            else:
                # Nový záznam
                entry_id = f"KE-{len(existing) + 1:06d}"
                existing[fp] = {
                    'id': entry_id,
                    'fingerprint': fp,
                    'category': incident.causal_chain.root_cause_type if incident.causal_chain else 'unknown',
                    'first_seen': now,
                    'last_seen': now,
                    'occurrences': 1,
                    'affected_apps': list(incident.scope.apps),
                    'affected_namespaces': list(incident.scope.namespaces),
                    'versions_seen': [v for versions in incident.scope.app_versions.values() for v in versions],
                    'status': 'OPEN',
                    'jira': None,
                    'notes': None,
                }
                updated = True
    
    if not updated:
        return
    
    # Seřaď od nejnovějšího (last_seen DESC)
    sorted_entries = sorted(existing.values(), key=lambda x: x.get('last_seen', ''), reverse=True)
    
    # Ulož YAML
    with open(errors_yaml, 'w', encoding='utf-8') as f:
        yaml.dump(sorted_entries, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    
    # Ulož MD (human-readable)
    _write_registry_md(sorted_entries, errors_md)
    
    if not quiet:
        print(f"   📝 Registry updated: {len(sorted_entries)} entries")


def _write_registry_md(entries: list, filepath: Path):
    """Zapíše human-readable MD verzi registry."""
    lines = [
        "# Known Errors Registry",
        "",
        f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        f"_Total entries: {len(entries)}_",
        "",
        "---",
        "",
    ]
    
    for entry in entries:
        lines.extend([
            f"## {entry.get('id', 'N/A')} – {entry.get('category', 'Unknown')}",
            "",
            f"**Fingerprint:** `{entry.get('fingerprint', 'N/A')}`",
            f"**First seen:** {entry.get('first_seen', 'N/A')}",
            f"**Last seen:** {entry.get('last_seen', 'N/A')}",
            f"**Occurrences:** {entry.get('occurrences', 0)}",
            f"**Status:** {entry.get('status', 'OPEN')}",
            "",
            "### Affected",
            f"- Apps: {', '.join(entry.get('affected_apps', []))}",
            f"- Namespaces: {', '.join(entry.get('affected_namespaces', []))}",
            f"- Versions: {', '.join(entry.get('versions_seen', []))}",
            "",
            "### Jira",
            f"{entry.get('jira') or '_(not created yet)_'}",
            "",
            "### Notes",
            f"{entry.get('notes') or '_(none)_'}",
            "",
            "---",
            "",
        ])
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def get_db_connection():
    """Get database connection (uses DDL user for INSERT operations)"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_DDL_USER', os.getenv('DB_USER')),
        password=os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD'))
    )


def save_incidents_to_db(collection, conn) -> int:
    """Save incidents to database - BATCH INSERT"""
    cursor = conn.cursor()
    
    # Set role for DDL operations
    cursor.execute("SET ROLE role_ailog_analyzer_ddl")
    
    if not collection.incidents:
        return 0
    
    # Prepare data for batch insert
    data = []
    for incident in collection.incidents:
        ts = incident.time.first_seen or datetime.now(timezone.utc)
        data.append((
            ts,
            ts.weekday(),
            ts.hour,
            ts.minute // 15,
            incident.namespaces[0] if incident.namespaces else 'unknown',
            incident.stats.current_count,  # original_value
            int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else incident.stats.current_count,  # reference_value
            incident.flags.is_new,
            incident.flags.is_spike,
            incident.flags.is_burst,
            incident.flags.is_cross_namespace,
            incident.error_type or '',
            (incident.normalized_message or '')[:500],
            'v4_pipeline',
            incident.score,
            incident.severity.value
        ))
    
    # Batch insert using execute_values (much faster)
    try:
        from psycopg2.extras import execute_values
        
        execute_values(cursor, """
            INSERT INTO ailog_peak.peak_investigation
            (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
             original_value, reference_value, 
             is_new, is_spike, is_burst, is_cross_namespace,
             error_type, error_message, detection_method, score, severity)
            VALUES %s
        """, data, page_size=1000)
        
        conn.commit()
        return len(data)
    except Exception as e:
        print(f" ⚠️  Batch insert error: {e}")
        conn.rollback()
        return 0


def update_error_patterns(collection, conn) -> int:
    """Update error_patterns table with fingerprints"""
    cursor = conn.cursor()
    updated = 0
    
    for incident in collection.incidents:
        try:
            ts = incident.time.first_seen or datetime.now(timezone.utc)
            
            cursor.execute("""
                INSERT INTO ailog_peak.error_patterns
                (namespace, error_type, error_message, pattern_hash, 
                 first_seen, last_seen, occurrence_count, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pattern_hash) DO UPDATE SET
                    last_seen = GREATEST(error_patterns.last_seen, EXCLUDED.last_seen),
                    occurrence_count = error_patterns.occurrence_count + 1,
                    updated_at = NOW()
            """, (
                incident.namespaces[0] if incident.namespaces else 'unknown',
                incident.error_type,
                incident.normalized_message[:500],
                incident.fingerprint,
                ts,
                incident.time.last_seen or ts,
                incident.stats.current_count,
                incident.severity.value
            ))
            updated += 1
        except:
            pass
    
    conn.commit()
    return updated


def send_alerts(collection, webhook_url: str = None):
    """Send alerts for critical/high incidents"""
    critical = [i for i in collection.incidents if i.severity == IncidentSeverity.CRITICAL]
    high = [i for i in collection.incidents if i.severity == IncidentSeverity.HIGH]
    
    if not critical and not high:
        return
    
    print(f"\n🚨 ALERTS: {len(critical)} critical, {len(high)} high")
    
    # TODO: Implement Teams/Slack webhook
    if webhook_url:
        try:
            import requests
            payload = {
                "@type": "MessageCard",
                "themeColor": "FF0000" if critical else "FFA500",
                "summary": f"AI Log Analyzer: {len(critical)} critical, {len(high)} high incidents",
                "sections": [{
                    "activityTitle": "🚨 Incident Alert",
                    "facts": [
                        {"name": "Critical", "value": str(len(critical))},
                        {"name": "High", "value": str(len(high))},
                        {"name": "Time", "value": datetime.now().strftime("%Y-%m-%d %H:%M")},
                    ]
                }]
            }
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            print(f"   ⚠️  Alert send failed: {e}")


def run_regular_pipeline(
    date_from: str = None,
    date_to: str = None,
    output_dir: str = None,
    dry_run: bool = False,
    quiet: bool = False,
    skip_analysis: bool = False
) -> dict:
    """
    Spustí regular pipeline pro jedno 15-min okno.
    """
    start_time = datetime.now()
    
    if not quiet:
        print("=" * 70)
        print("🚀 REGULAR PHASE - 15-minute Pipeline")
        print(f"   Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
    
    # Determine time window
    now = datetime.now(timezone.utc)
    
    if date_from and date_to:
        window_start = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        window_end = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
    else:
        # Align to 15-min boundary (process previous window)
        minute = (now.minute // 15) * 15
        window_end = now.replace(minute=minute, second=0, microsecond=0)
        window_start = window_end - timedelta(minutes=15)
    
    window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    window_end_str = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    if not quiet:
        print(f"\n📅 Window: {window_start_str} → {window_end_str}")
    
    # Fetch from ES
    errors = fetch_unlimited(window_start_str, window_end_str)
    
    if errors is None:
        if not quiet:
            print("   ❌ Fetch failed")
        return {'status': 'error', 'reason': 'fetch_failed'}
    
    if len(errors) == 0:
        if not quiet:
            print("   ✅ No errors in this window")
        return {
            'status': 'success',
            'window': {'start': window_start_str, 'end': window_end_str},
            'error_count': 0,
            'incidents': 0
        }
    
    if not quiet:
        print(f"   📥 Fetched {len(errors):,} errors")
    
    # Create and run V4 pipeline
    pipeline = PipelineV4(
        spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
        ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
    )
    
    run_id = f"regular-{window_start.strftime('%Y%m%d-%H%M')}"
    
    if quiet:
        # Suppress pipeline output in quiet mode
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            collection = pipeline.run(errors, run_id=run_id)
    else:
        collection = pipeline.run(errors, run_id=run_id)
    
    if not quiet:
        print(f"\n📊 Results:")
        print(f"   Incidents: {collection.total_incidents}")
        print(f"   By severity: {collection.by_severity}")
    
    # Save to DB
    saved_incidents = 0
    if not dry_run and HAS_DB:
        try:
            conn = get_db_connection()
            saved_incidents = save_incidents_to_db(collection, conn)
            update_error_patterns(collection, conn)
            conn.close()
            
            if not quiet:
                print(f"\n💾 Saved {saved_incidents} incidents to DB")
        except Exception as e:
            if not quiet:
                print(f"   ⚠️  DB error: {e}")
    elif dry_run and not quiet:
        print("\n   ⏭️  DRY RUN - not saving to DB")
    
    # Save report
    if output_dir:
        reporter = PhaseF_Report()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        files = reporter.save_snapshot(collection, str(output_path))
        if not quiet:
            print(f"\n💾 Reports saved to: {output_dir}")
    
    # Send alerts
    webhook_url = os.getenv('TEAMS_WEBHOOK_URL')
    if collection.by_severity.get('critical', 0) > 0 or collection.by_severity.get('high', 0) > 0:
        send_alerts(collection, webhook_url)
    
    # === INCIDENT ANALYSIS v5.3 ===
    # OPRAVA: Report se generuje VŽDY, bez podmínek!
    if HAS_INCIDENT_ANALYSIS and not skip_analysis:
        if not quiet:
            print(f"\n🔍 Running Incident Analysis...")
        
        # Defaultní output_dir = scripts/reports/
        reports_dir = output_dir or (SCRIPT_DIR / 'reports')
        
        analysis_report = run_incident_analysis(
            collection, 
            window_start, 
            window_end, 
            output_dir=str(reports_dir),
            quiet=quiet
        )
        
        if analysis_report and not quiet:
            print(analysis_report)
    
    # Duration
    duration = (datetime.now() - start_time).total_seconds()
    
    if not quiet:
        print("\n" + "=" * 70)
        print(f"✅ REGULAR PHASE COMPLETE ({duration:.1f}s)")
        print("=" * 70)
    
    return {
        'status': 'success',
        'window': {'start': window_start_str, 'end': window_end_str},
        'error_count': len(errors),
        'incidents': collection.total_incidents,
        'saved': saved_incidents,
        'by_severity': collection.by_severity,
        'duration_sec': duration
    }


def main():
    parser = argparse.ArgumentParser(description='Regular Phase - 15-minute Pipeline')
    parser.add_argument('--from', dest='date_from', help='Start time (ISO format)')
    parser.add_argument('--to', dest='date_to', help='End time (ISO format)')
    parser.add_argument('--output', type=str, help='Output directory for reports')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no DB writes')
    parser.add_argument('--quiet', action='store_true', help='Minimal output (for cron)')
    parser.add_argument('--no-analysis', action='store_true', help='Skip incident analysis')
    
    args = parser.parse_args()
    
    result = run_regular_pipeline(
        date_from=args.date_from,
        date_to=args.date_to,
        output_dir=args.output,
        dry_run=args.dry_run,
        quiet=args.quiet,
        skip_analysis=args.no_analysis
    )
    
    # Exit code
    if result.get('status') == 'error':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
