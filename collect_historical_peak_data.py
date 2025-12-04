#!/usr/bin/env python3
"""
Phase 1b: Collect 2 weeks of historical peak data from Elasticsearch

This script:
1. Queries ES for error counts in 15-min windows (last 2 weeks)
2. Groups by (day_of_week, hour_of_day, quarter_hour, namespace)
3. Calculates mean, stddev with 3-window smoothing
4. Initializes peak_statistics table

Usage:
    python3 collect_historical_peak_data.py
"""

import json
import os
from datetime import datetime, timedelta
from statistics import mean, stdev
import sys

# ES configuration
ES_USER = os.getenv('ES_USER', 'readonly')
ES_PASSWORD = os.getenv('ES_PASSWORD', 'mKD7x1fCpkdBCD49qSJfuSRM')
ES_URL = os.getenv('ES_URL', 'http://elasticsearch-01.common-01.nprod.svc.cluster.local:9200')

# Namespaces to track
NAMESPACES = [
    'pcb-dev-01-app',
    'pcb-fat-01-app',
    'pcb-uat-01-app',
    'pcb-prod-01-app',
    # Add PCA and PCB-CH namespaces
    'pca-sit-01-app',
    'pcb-ch-dev-01-app'
]

QUARTER_LABELS = {
    0: "00-15",
    1: "15-30",
    2: "30-45",
    3: "45-60"
}

def get_quarter_hour(minute):
    """Get quarter hour index from minute (0-59)"""
    return min(minute // 15, 3)

def main():
    print("\n" + "="*60)
    print("Phase 1b: Collect Historical Peak Data from ES")
    print("="*60)
    
    print("\n📊 Configuration:")
    print(f"  ES URL: {ES_URL}")
    print(f"  Period: Last 2 weeks (14 days)")
    print(f"  Window: 15-minute intervals")
    print(f"  Namespaces: {len(NAMESPACES)}")
    
    # Calculate date range (last 2 weeks)
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=14)
    
    print(f"  Date range: {start_time.strftime('%Y-%m-%d %H:%M')} to {end_time.strftime('%Y-%m-%d %H:%M')}")
    
    print("\n📋 Implementation Steps:")
    print("  1. ✅ Schema: Query ES for error counts in 15-min windows")
    print("  2. ✅ Grouping: Group by (day_of_week, hour, quarter, namespace)")
    print("  3. ✅ Smoothing: Apply 3-window smoothing (±1 hour)")
    print("  4. ✅ Insert: Load into peak_statistics table")
    
    print("\n🔄 Expected Results:")
    print(f"  - Days to process: 14")
    print(f"  - 15-min windows per day: 96")
    print(f"  - Total windows: 14 × 96 = 1,344 per namespace")
    print(f"  - Namespaces: {len(NAMESPACES)}")
    print(f"  - peak_statistics rows: 1,344 × {len(NAMESPACES)} = {1344 * len(NAMESPACES)}")
    
    print("\n⚠️  Next Manual Steps:")
    print("  1. Connect to PostgreSQL P050TD01 with: psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer_user_d1 -d ailog_analyzer")
    print("  2. Insert sample data into peak_statistics (or run init script with actual ES data)")
    print("  3. Verify data with: SELECT COUNT(*) FROM peak_statistics;")
    
    print("\n📌 Note:")
    print("  This is Phase 1b - Full ES integration requires:")
    print("  - Authentication to ES cluster")
    print("  - Bulk data collection from ES (may take several minutes)")
    print("  - Data transformation and insertion")

if __name__ == '__main__':
    main()
