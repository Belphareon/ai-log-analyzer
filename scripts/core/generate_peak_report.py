#!/usr/bin/env python3
"""
Peak Detection Report Generator
================================
Generuje pravidelné reporty o peak detection pro regular fázi.
Čte thresholds z databáze (dynamicky, žádné hardcoded hodnoty).

Použití:
    python generate_peak_report.py --from-db           # Report z DB dat
    python generate_peak_report.py --from-file FILE    # Report z log souboru
    python generate_peak_report.py --daily             # Denní report (posledních 24h)
    python generate_peak_report.py --weekly            # Týdenní report (posledních 7 dní)
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

# Optional imports
try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from peak_detection import PeakDetector
except ImportError:
    PeakDetector = None

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', os.getenv('DB_USER', 'ailog_analyzer_user_d1')),
    'password': os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD'))
}


def get_db_connection():
    """Get database connection with SET ROLE for schema access"""
    if not HAS_PSYCOPG2:
        raise ImportError("psycopg2 not installed. Use --from-file instead of --from-db")
    conn = psycopg2.connect(**DB_CONFIG)
    ddl_role = os.getenv('DB_DDL_ROLE', 'role_ailog_analyzer_ddl')
    cur = conn.cursor()
    cur.execute(f"SET ROLE {ddl_role}")
    conn.commit()
    cur.close()
    return conn


def fetch_raw_data(conn, start_date: datetime = None, end_date: datetime = None) -> list:
    """
    Fetch raw data from peak_raw_data table
    
    Args:
        conn: database connection
        start_date: optional start date filter
        end_date: optional end date filter
    
    Returns:
        list of dicts with namespace, day_of_week, value, timestamp
    """
    query = """
        SELECT 
            namespace,
            day_of_week,
            hour,
            quarter,
            original_value,
            timestamp,
            is_peak
        FROM ailog_peak.peak_raw_data
        WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND timestamp >= %s"
        params.append(start_date)
    
    if end_date:
        query += " AND timestamp <= %s"
        params.append(end_date)
    
    query += " ORDER BY timestamp"
    
    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    
    return [
        {
            'namespace': row[0],
            'day_of_week': row[1],
            'hour': row[2],
            'quarter': row[3],
            'value': float(row[4]) if row[4] else 0,
            'timestamp': row[5],
            'db_is_peak': row[6],
        }
        for row in rows
    ]


def fetch_from_log_file(file_path: str) -> list:
    """
    Parse data from log file (DATA| format)
    
    Format: DATA|TIMESTAMP|day_of_week|hour|quarter|namespace|mean|stddev|samples
    """
    data = []
    
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('DATA|'):
                continue
            
            parts = line.split('|')
            if len(parts) >= 7:
                try:
                    data.append({
                        'timestamp': parts[1],
                        'day_of_week': int(parts[2]),
                        'hour': int(parts[3]),
                        'quarter': int(parts[4]),
                        'namespace': parts[5],
                        'value': float(parts[6]),
                    })
                except (ValueError, IndexError) as e:
                    continue
    
    return data


def generate_report(data: list, detector: 'PeakDetector', output_path: str, title: str = "Peak Detection Report"):
    """
    Generate markdown report
    
    Args:
        data: list of dicts with namespace, day_of_week, value, etc.
        detector: PeakDetector instance (reads thresholds from DB)
        output_path: where to save report
        title: report title
    """
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Collect statistics
    stats_by_ns = {}
    total_peaks_detected = 0
    total_peaks_db = 0
    
    for row in data:
        ns = row.get('namespace', 'unknown')
        dow = row.get('day_of_week', 0)
        value = row.get('value', 0)
        db_is_peak = row.get('db_is_peak', None)
        
        if ns not in stats_by_ns:
            stats_by_ns[ns] = {
                'total': 0,
                'peaks_detected': 0,
                'peaks_db': 0,
                'max_non_peak': 0,
                'max_value': 0,
                'by_dow': {d: {'total': 0, 'peaks_detected': 0, 'peaks_db': 0} for d in range(7)}
            }
        
        result = detector.is_peak(value, ns, dow)
        
        stats_by_ns[ns]['total'] += 1
        stats_by_ns[ns]['max_value'] = max(stats_by_ns[ns]['max_value'], value)
        stats_by_ns[ns]['by_dow'][dow]['total'] += 1
        
        if result['is_peak']:
            stats_by_ns[ns]['peaks_detected'] += 1
            stats_by_ns[ns]['by_dow'][dow]['peaks_detected'] += 1
            total_peaks_detected += 1
        else:
            stats_by_ns[ns]['max_non_peak'] = max(stats_by_ns[ns]['max_non_peak'], value)
        
        if db_is_peak:
            stats_by_ns[ns]['peaks_db'] += 1
            stats_by_ns[ns]['by_dow'][dow]['peaks_db'] += 1
            total_peaks_db += 1
    
    # Get threshold info
    all_thresholds = detector.get_all_thresholds()
    
    # Generate report
    with open(output_path, 'w') as f:
        f.write(f"# {title}\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Method:** P{int(all_thresholds['percentile_level'] * 100)} OR CAP (DB thresholds)\n")
        f.write(f"**Data points:** {len(data)}\n\n")
        
        # Summary table
        f.write("## Summary\n\n")
        f.write("| NS | N | Peaks | % | Max non-peak | Max value |\n")
        f.write("|----|---|------------|---|--------------|----------|\n")
        
        total_n = 0
        
        for ns in sorted(stats_by_ns.keys()):
            s = stats_by_ns[ns]
            pct = (s['peaks_detected'] / s['total'] * 100) if s['total'] > 0 else 0
            f.write(f"| {ns} | {s['total']} | {s['peaks_detected']} | {pct:.1f}% | {s['max_non_peak']:.0f} | {s['max_value']:.0f} |\n")
            total_n += s['total']
        
        total_pct = (total_peaks_detected / total_n * 100) if total_n > 0 else 0
        f.write(f"| **TOTAL** | **{total_n}** | **{total_peaks_detected}** | **{total_pct:.1f}%** | | |\n")
        
        # Thresholds used (from DB)
        f.write("\n## Thresholds (from Database)\n\n")
        f.write("| NS | CAP | Mon | Tue | Wed | Thu | Fri | Sat | Sun |\n")
        f.write("|----|-----|-----|-----|-----|-----|-----|-----|-----|\n")
        
        thresholds = all_thresholds['thresholds']
        caps = all_thresholds['caps']
        namespaces = sorted(set(ns for (ns, dow) in thresholds.keys()))
        
        for ns in namespaces:
            cap = caps.get(ns, {}).get('value', all_thresholds['default_threshold'])
            row = f"| {ns} | **{cap:.0f}** |"
            for dow in range(7):
                data_thr = thresholds.get((ns, dow))
                if data_thr:
                    row += f" {data_thr['value']:.0f} |"
                else:
                    row += f" -- |"
            f.write(row + "\n")
        
        # Per-NS breakdown
        f.write("\n## Per-Namespace Breakdown\n\n")
        
        for ns in sorted(stats_by_ns.keys()):
            s = stats_by_ns[ns]
            ns_pct = (s['peaks_detected'] / s['total'] * 100) if s['total'] > 0 else 0
            
            f.write(f"\n### {ns}\n\n")
            f.write(f"**Total:** {s['total']} | **Peaks:** {s['peaks_detected']} ({ns_pct:.1f}%) | ")
            f.write(f"**Max non-peak:** {s['max_non_peak']:.0f} | **Max:** {s['max_value']:.0f}\n\n")
            
            f.write("| Day | N | Peaks | % |\n")
            f.write("|-----|---|-------|---|\n")
            
            for dow in range(7):
                d = s['by_dow'][dow]
                pct = (d['peaks_detected'] / d['total'] * 100) if d['total'] > 0 else 0
                f.write(f"| {days[dow]} | {d['total']} | {d['peaks_detected']} | {pct:.1f}% |\n")
    
    print(f"✅ Report saved: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description='Peak Detection Report Generator')
    parser.add_argument('--from-db', action='store_true', help='Generate report from database')
    parser.add_argument('--from-file', type=str, help='Generate report from log file')
    parser.add_argument('--daily', action='store_true', help='Daily report (last 24h)')
    parser.add_argument('--weekly', action='store_true', help='Weekly report (last 7 days)')
    parser.add_argument('--output', type=str, default='/tmp/peak_reports', help='Output directory')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    
    args = parser.parse_args()
    
    os.makedirs(args.output, exist_ok=True)
    
    # Need DB connection for PeakDetector (to read thresholds)
    if not HAS_PSYCOPG2:
        print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    
    if PeakDetector is None:
        print("❌ Could not import PeakDetector from peak_detection.py")
        sys.exit(1)
    
    print("🔌 Connecting to database...")
    try:
        conn = get_db_connection()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)
    
    # Create detector (reads thresholds from DB)
    detector = PeakDetector(conn=conn)
    
    if args.from_file:
        print(f"📂 Reading from file: {args.from_file}")
        data = fetch_from_log_file(args.from_file)
        title = f"Peak Detection Report - File: {os.path.basename(args.from_file)}"
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(args.output, f'peak_report_file_{timestamp}.md')
        
    elif args.from_db or args.daily or args.weekly:
        start_date = None
        end_date = None
        title = "Peak Detection Report"
        
        if args.daily:
            start_date = datetime.now() - timedelta(days=1)
            title = f"Daily Peak Report - {start_date.strftime('%Y-%m-%d')}"
        elif args.weekly:
            start_date = datetime.now() - timedelta(days=7)
            title = f"Weekly Peak Report - {start_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}"
        
        if args.start_date:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        if args.end_date:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
        
        print(f"📊 Fetching data from database...")
        data = fetch_raw_data(conn, start_date, end_date)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_type = 'daily' if args.daily else ('weekly' if args.weekly else 'full')
        output_path = os.path.join(args.output, f'peak_report_{report_type}_{timestamp}.md')
        
    else:
        parser.print_help()
        conn.close()
        sys.exit(1)
    
    print(f"📈 Processing {len(data)} data points...")
    generate_report(data, detector, output_path, title)
    
    conn.close()
    print(f"\n✅ Done! Report: {output_path}")


if __name__ == '__main__':
    main()
