#!/usr/bin/env python3
"""
AI Log Analyzer - Main Pipeline Orchestrator

Workflow:
1. SBĚR DAT (15min interval) - collect_peak_detailed.py
2. IDENTIFIKACE & KLASIFIKACE - intelligent_analysis.py
3. INTELIGENTNÍ ANALÝZA (traceID context) - intelligent_analysis.py
4. INGESTION + PEAK DETECTION - ingest_from_log.py
5a. NON-PEAK: Check known issues, analyze new errors
5b. PEAK: Detect → investigate → log
6. VYHODNOCENÍ & ZÁZNAM - peak_investigation table
7. AI ANALÝZA (future - GitHub Copilot API)
8. NOTIFIKACE (Teams webhook)
9. MONITORING MAINTENANCE

Usage:
    # Regular 15-min run (production)
    python3 run_pipeline.py
    
    # Custom date range
    python3 run_pipeline.py --from "2026-01-15T00:00:00Z" --to "2026-01-16T00:00:00Z"
    
    # Skip intelligent analysis (faster)
    python3 run_pipeline.py --skip-analysis
    
    # Dry run (no DB writes)
    python3 run_pipeline.py --dry-run
"""

import os
import sys
import argparse
import subprocess
import tempfile
import json
import hashlib
import psycopg2
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Load environment
load_dotenv(PROJECT_ROOT / ".env")

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}


def log_step(step_num, message, status="🔄"):
    """Log pipeline step"""
    print(f"\n{'='*80}")
    print(f"{status} STEP {step_num}: {message}")
    print(f"{'='*80}")


def run_script(script_name, args=None, capture_output=False):
    """Run a Python script from scripts directory"""
    script_path = SCRIPTS_DIR / script_name
    
    if not script_path.exists():
        print(f"❌ Script not found: {script_path}")
        return None
    
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    
    print(f"   Running: {' '.join(cmd)}")
    
    try:
        if capture_output:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            return result
        else:
            result = subprocess.run(cmd, timeout=600)
            return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"   ❌ Timeout after 10 minutes")
        return None
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def step1_collect_data(date_from, date_to, output_file):
    """
    STEP 1: Sběr dat z Elasticsearch
    Uses collect_peak_detailed.py to fetch errors and group into 15-min windows
    """
    log_step(1, f"SBĚR DAT Z ELASTICSEARCH ({date_from} → {date_to})")
    
    args = [
        "--from", date_from,
        "--to", date_to
    ]
    
    result = run_script("collect_peak_detailed.py", args, capture_output=True)
    
    if result is None or result.returncode != 0:
        print(f"   ❌ Data collection failed")
        if result:
            print(f"   STDERR: {result.stderr[:500]}")
        return False
    
    # Save output to file
    with open(output_file, 'w') as f:
        f.write(result.stdout)
    
    # Count DATA lines
    data_lines = [l for l in result.stdout.split('\n') if l.startswith('DATA|')]
    print(f"   ✅ Collected {len(data_lines)} DATA rows")
    print(f"   📄 Saved to: {output_file}")
    
    return len(data_lines) > 0


def step2_intelligent_analysis(date_from, date_to, conn=None, skip=False):
    """
    STEP 2-3: Identifikace, klasifikace a inteligentní analýza
    Uses analyze_and_track.py for trace-based root cause analysis + error tracking
    
    Returns: dict with analysis results (root causes, patterns, etc.)
    """
    log_step(2, "INTELIGENTNÍ ANALÝZA (trace-based root cause)")
    
    if skip:
        print("   ⏭️  Skipped (--skip-analysis flag)")
        return {'skipped': True}
    
    try:
        # Import and run analysis
        from analyze_and_track import analyze_period
        
        results = analyze_period(date_from, date_to, conn)
        
        if 'error' in results:
            print(f"   ⚠️  Analysis failed: {results['error']}")
            return results
        
        print(f"   ✅ Analyzed {results.get('total_errors', 0):,} errors")
        
        if results.get('top_root_causes'):
            print(f"   🔍 Top root causes:")
            for i, rc in enumerate(results['top_root_causes'][:3], 1):
                print(f"      {i}. {rc['app']}: {rc['message'][:50]}... ({rc['total_errors']} errors)")
        
        if results.get('pattern_stats'):
            ps = results['pattern_stats']
            print(f"   📝 Patterns: {ps.get('new_patterns', 0)} new, {ps.get('updated_patterns', 0)} updated")
        
        return results
        
    except ImportError as e:
        print(f"   ⚠️  Import error: {e}")
        return {'skipped': True, 'reason': 'import_error'}
    except Exception as e:
        print(f"   ⚠️  Analysis error: {e}")
        return {'skipped': True, 'reason': str(e)}


def step4_ingest_and_detect(input_file, dry_run=False):
    """
    STEP 4: Ingestion + Peak Detection
    Uses ingest_from_log.py to insert data and detect peaks
    
    Returns: dict with ingestion stats and detected peaks
    """
    log_step(4, "INGESTION + PEAK DETECTION")
    
    if dry_run:
        print("   ⏭️  Dry run - no DB writes")
        return {'dry_run': True}
    
    args = ["--input", str(input_file)]
    # Note: NO --init flag = REGULAR phase with peak detection
    
    success = run_script("ingest_from_log_v2.py", args)
    
    if success:
        print("   ✅ Ingestion complete")
        return {'success': True}
    else:
        print("   ❌ Ingestion failed")
        return {'success': False}


def step5_check_known_issues(conn):
    """
    STEP 5: Check against known issues and track error patterns
    """
    log_step(5, "CHECK KNOWN ISSUES & ERROR PATTERNS")
    
    cursor = conn.cursor()
    
    # Get recent peaks from peak_investigation
    cursor.execute("""
        SELECT COUNT(*) FROM ailog_peak.peak_investigation
        WHERE created_at >= NOW() - INTERVAL '1 hour';
    """)
    recent_peaks = cursor.fetchone()[0]
    
    # Get known issues count
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.known_issues WHERE status = 'active';")
    known_issues_count = cursor.fetchone()[0]
    
    print(f"   📊 Recent peaks (1h): {recent_peaks}")
    print(f"   📋 Active known issues: {known_issues_count}")
    
    if recent_peaks > 0:
        print("   🔴 Peaks detected - need investigation")
        # TODO: Match peaks against known_issues patterns
        # TODO: Create new known_issue if pattern repeats
    else:
        print("   ✅ No peaks in last hour")
    
    return {
        'recent_peaks': recent_peaks,
        'known_issues': known_issues_count
    }


def step6_record_results(conn, results):
    """
    STEP 6: Vyhodnocení a záznam
    Update statistics, log results
    """
    log_step(6, "VYHODNOCENÍ & ZÁZNAM")
    
    cursor = conn.cursor()
    
    # Get current DB stats
    stats = {}
    tables = ['peak_raw_data', 'aggregation_data', 'peak_investigation', 'error_patterns']
    
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM ailog_peak.{table};")
        stats[table] = cursor.fetchone()[0]
    
    print(f"   📊 DB Statistics:")
    for table, count in stats.items():
        print(f"      {table}: {count} rows")
    
    return stats


def step7_ai_analysis(results, skip=True):
    """
    STEP 7: AI analýza (future - GitHub Copilot API)
    """
    log_step(7, "AI ANALÝZA (future)")
    
    if skip:
        print("   ⏭️  AI analysis not yet implemented")
        print("   📋 TODO: GitHub Copilot API integration")
        return {'skipped': True}
    
    return {}


def step8_notification(results, skip=True):
    """
    STEP 8: Notifikace (Teams webhook)
    """
    log_step(8, "NOTIFIKACE")
    
    if skip:
        print("   ⏭️  Notifications disabled")
        return {'skipped': True}
    
    # TODO: Teams webhook integration
    teams_webhook = os.getenv('TEAMS_WEBHOOK_URL')
    
    if not teams_webhook:
        print("   ⚠️  TEAMS_WEBHOOK_URL not set in .env")
        return {'skipped': True, 'reason': 'no_webhook'}
    
    # TODO: Send notification
    return {}


def step9_maintenance(conn):
    """
    STEP 9: Monitoring maintenance
    - Delete old data (>30 days from peak_raw_data)
    - Update aggregation_data
    """
    log_step(9, "MONITORING MAINTENANCE")
    
    cursor = conn.cursor()
    
    # Delete old data from peak_raw_data (keep 30 days)
    cursor.execute("""
        DELETE FROM ailog_peak.peak_raw_data
        WHERE timestamp < NOW() - INTERVAL '30 days';
    """)
    deleted_count = cursor.rowcount
    conn.commit()
    
    if deleted_count > 0:
        print(f"   🗑️  Deleted {deleted_count} old rows from peak_raw_data")
    else:
        print("   ✅ No old data to delete")
    
    # Check aggregation_data freshness
    cursor.execute("""
        SELECT MAX(last_updated) FROM ailog_peak.aggregation_data;
    """)
    last_updated = cursor.fetchone()[0]
    print(f"   📅 Aggregation last updated: {last_updated}")
    
    return {
        'deleted_old_rows': deleted_count,
        'aggregation_last_updated': str(last_updated) if last_updated else None
    }


def main():
    parser = argparse.ArgumentParser(description='AI Log Analyzer - Main Pipeline')
    parser.add_argument('--from', dest='date_from', help='Start date (ISO format with Z suffix)')
    parser.add_argument('--to', dest='date_to', help='End date (ISO format with Z suffix)')
    parser.add_argument('--skip-analysis', action='store_true', help='Skip intelligent analysis step')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no DB writes')
    parser.add_argument('--skip-maintenance', action='store_true', help='Skip maintenance step')
    args = parser.parse_args()
    
    print("=" * 80)
    print("🚀 AI LOG ANALYZER - MAIN PIPELINE")
    print(f"   Started: {datetime.now().isoformat()}")
    print("=" * 80)
    
    # Determine date range (default: last 15 minutes)
    if args.date_from and args.date_to:
        date_from = args.date_from
        date_to = args.date_to
    else:
        now = datetime.now(timezone.utc)
        # Round to 15-min boundary
        minute = (now.minute // 15) * 15
        end_time = now.replace(minute=minute, second=0, microsecond=0)
        start_time = end_time - timedelta(minutes=15)
        
        date_from = start_time.isoformat().replace('+00:00', 'Z')
        date_to = end_time.isoformat().replace('+00:00', 'Z')
    
    print(f"\n📅 Processing period: {date_from} → {date_to}")
    
    # Create temp file for collected data
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
        output_file = tmp.name
    
    results = {}
    conn = None
    
    try:
        # Connect to DB early (needed for analysis)
        if not args.dry_run:
            try:
                conn = psycopg2.connect(**DB_CONFIG)
            except Exception as e:
                print(f"⚠️ Database connection failed: {e}")
                print("   Continuing without DB operations")
        
        # STEP 1: Collect data from ES
        if not step1_collect_data(date_from, date_to, output_file):
            print("\n❌ PIPELINE FAILED at Step 1")
            return 1
        
        # STEP 2-3: Intelligent analysis (with DB for error tracking)
        results['analysis'] = step2_intelligent_analysis(date_from, date_to, conn=conn, skip=args.skip_analysis)
        
        # STEP 4: Ingestion + Peak Detection
        results['ingestion'] = step4_ingest_and_detect(output_file, dry_run=args.dry_run)
        
        if not args.dry_run and conn:
            # STEP 5: Check known issues
            results['known_issues'] = step5_check_known_issues(conn)
            
            # STEP 6: Record results
            results['stats'] = step6_record_results(conn, results)
            
            # STEP 7: AI analysis (future)
            results['ai'] = step7_ai_analysis(results, skip=True)
            
            # STEP 8: Notification
            results['notification'] = step8_notification(results, skip=True)
            
            # STEP 9: Maintenance
            if not args.skip_maintenance:
                results['maintenance'] = step9_maintenance(conn)
            
            conn.close()
        
        print("\n" + "=" * 80)
        print("✅ PIPELINE COMPLETED SUCCESSFULLY")
        print(f"   Finished: {datetime.now().isoformat()}")
        print("=" * 80)
        
        return 0
        
    finally:
        # Cleanup temp file
        if os.path.exists(output_file):
            os.remove(output_file)


if __name__ == '__main__':
    sys.exit(main())
