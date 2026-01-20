#!/usr/bin/env python3
"""
Verify Peak Detection Results
Analyzes detected peaks in a given time window with detailed statistics
"""

import os
import sys
import argparse
import psycopg2
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

def connect_db():
    """Connect to database"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SET search_path = ailog_peak;")
    return conn, cur

def format_datetime(dt):
    """Format datetime for display"""
    if dt is None:
        return "N/A"
    return dt.strftime('%a %H:%M')

def analyze_peaks(date_from, date_to, limit=50):
    """Analyze peaks in time window"""
    
    print("=" * 140)
    print(f"PEAK DETECTION ANALYSIS: {date_from} → {date_to}")
    print("=" * 140)
    
    conn, cur = connect_db()
    
    # Get peaks
    cur.execute("""
    SELECT 
        timestamp,
        namespace,
        original_value,
        baseline_mean,
        reference_value,
        ratio,
        replacement_value
    FROM peak_investigation
    WHERE timestamp >= %s AND timestamp < %s
    ORDER BY timestamp, namespace
    LIMIT %s;
    """, (date_from, date_to, limit))
    
    peaks = cur.fetchall()
    
    if not peaks:
        print(f"\n❌ Žádné peaky v daném čase: {date_from} → {date_to}")
        cur.close()
        conn.close()
        return
    
    print(f"\n📊 Detektováno {len(peaks)} peaky:\n")
    print(f"{'⏰':4s} {'Čas':12s} {'Aplikace':30s} {'Orig':>10s} {'Ref':>10s} {'Ratio':>8s} {'Baseline':>10s} {'Podmínka':40s}")
    print("-" * 140)
    
    ratio_count = 0
    absolute_count = 0
    
    for ts, ns, orig, baseline, ref, ratio, repl in peaks:
        abs_threshold = baseline * 4.0 if baseline else None
        
        cond1 = ratio >= 3.0 if ratio else False
        cond2 = orig >= abs_threshold if abs_threshold and orig else False
        
        # Determine which condition triggered
        if cond1 and cond2:
            cond_str = "ratio>=3.0 ✓ + val>=4.0×base ✓"
            absolute_count += 1
            ratio_count += 1
        elif cond1:
            cond_str = "ratio>=3.0 ✓"
            ratio_count += 1
        elif cond2:
            cond_str = f"val>={abs_threshold:.1f} ✓"
            absolute_count += 1
        else:
            cond_str = "??? (neměl by být peak)"
        
        time_str = format_datetime(ts)
        print(f"{'':4s} {time_str:12s} {ns:30s} {orig:>10.1f} {ref:>10.1f} {ratio:>8.2f}× {baseline:>10.1f} {cond_str:40s}")
    
    print("\n" + "=" * 140)
    print("STATISTIKA DETEKCE")
    print("=" * 140)
    
    # Detailed statistics
    cur.execute("""
    SELECT 
        COUNT(*) as total_peaks,
        COUNT(CASE WHEN ratio >= 3.0 THEN 1 END) as by_ratio_only,
        COUNT(CASE WHEN original_value >= baseline_mean * 4.0 THEN 1 END) as by_absolute_only,
        COUNT(CASE WHEN ratio >= 3.0 AND original_value >= baseline_mean * 4.0 THEN 1 END) as by_both,
        MIN(original_value) as min_val,
        AVG(original_value) as avg_val,
        MAX(original_value) as max_val,
        STDDEV(original_value) as stddev_val,
        AVG(baseline_mean) as avg_baseline,
        AVG(ratio) as avg_ratio,
        MIN(ratio) as min_ratio,
        MAX(ratio) as max_ratio
    FROM peak_investigation
    WHERE timestamp >= %s AND timestamp < %s
      AND reference_value > 0
      AND original_value > 0;
    """, (date_from, date_to))
    
    row = cur.fetchone()
    if row:
        (total, by_ratio_only, by_abs_only, by_both, 
         min_v, avg_v, max_v, stddev_v,
         avg_b, avg_r, min_r, max_r) = row
        
        print(f"\n✅ Detekční podmínky:")
        print(f"   - Pouze ratio (>= 3.0): {by_ratio_only}")
        print(f"   - Pouze absolute (>= 4.0×baseline): {by_abs_only}")
        print(f"   - Obojí: {by_both}")
        
        print(f"\n📈 Originální hodnoty:")
        print(f"   - Min: {min_v:.2f}")
        print(f"   - Avg: {avg_v:.2f}")
        print(f"   - Max: {max_v:.2f}")
        if stddev_v:
            print(f"   - StdDev: {stddev_v:.2f}")
        
        print(f"\n📊 Ratio statistika:")
        print(f"   - Avg: {avg_r:.2f}×")
        print(f"   - Min: {min_r:.2f}×")
        print(f"   - Max: {max_r:.2f}×")
        
        print(f"\n📍 Baseline (7-day average):")
        print(f"   - Avg: {avg_b:.2f}")
    
    # Peaks by namespace
    print("\n" + "=" * 140)
    print("PEAKY PO APLIKACI")
    print("=" * 140)
    
    cur.execute("""
    SELECT 
        namespace,
        COUNT(*) as count,
        AVG(original_value) as avg_val,
        MAX(original_value) as max_val,
        AVG(ratio) as avg_ratio
    FROM peak_investigation
    WHERE timestamp >= %s AND timestamp < %s
      AND reference_value > 0
      AND original_value > 0
    GROUP BY namespace
    ORDER BY count DESC;
    """, (date_from, date_to))
    
    ns_stats = cur.fetchall()
    for ns, count, avg_val, max_val, avg_ratio in ns_stats:
        print(f"   {ns:35s} | {count:3d} peaky | avg={avg_val:8.1f} | max={max_val:8.1f} | avg_ratio={avg_ratio:6.2f}×")
    
    # Validation: Check for suspicious peaks (ratio < 1 or replacement < baseline)
    print("\n" + "=" * 140)
    print("⚠️  VALIDACE (kontrola anomálií)")
    print("=" * 140)
    
    cur.execute("""
    SELECT 
        COUNT(*) as suspicious_count
    FROM peak_investigation
    WHERE timestamp >= %s AND timestamp < %s
      AND (ratio < 1.0 OR (baseline_mean > 0 AND replacement_value < baseline_mean * 0.9));
    """, (date_from, date_to))
    
    suspicious = cur.fetchone()[0]
    if suspicious > 0:
        print(f"❌ Nalezeno {suspicious} anomálních peaky (ratio < 1 nebo replacement < 0.9×baseline)")
        
        cur.execute("""
        SELECT 
            timestamp, namespace, original_value, baseline_mean, 
            reference_value, ratio, replacement_value
        FROM peak_investigation
        WHERE timestamp >= %s AND timestamp < %s
          AND (ratio < 1.0 OR (baseline_mean > 0 AND replacement_value < baseline_mean * 0.9))
        LIMIT 10;
        """, (date_from, date_to))
        
        for ts, ns, orig, baseline, ref, ratio, repl in cur.fetchall():
            print(f"   ⚠️  {format_datetime(ts)} {ns:30s} | orig={orig:.1f} | ratio={ratio:.2f}× | baseline={baseline:.1f} | repl={repl:.1f}")
    else:
        print("✅ Žádné anomálie - detekce funguje správně")
    
    cur.close()
    conn.close()
    
    print("\n" + "=" * 140)

def main():
    parser = argparse.ArgumentParser(description='Verify Peak Detection Results')
    parser.add_argument('--from', dest='date_from', required=True, 
                       help='Start date (ISO format: 2026-01-06 nebo 2026-01-06T00:00:00)')
    parser.add_argument('--to', dest='date_to', required=True,
                       help='End date (ISO format: 2026-01-07 nebo 2026-01-07T00:00:00)')
    parser.add_argument('--limit', dest='limit', type=int, default=50,
                       help='Maximum počet peaky k zobrazení (default: 50)')
    
    args = parser.parse_args()
    
    try:
        analyze_peaks(args.date_from, args.date_to, args.limit)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
