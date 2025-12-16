#!/usr/bin/env python3
"""
Phase 1b: Collect 2 weeks of historical peak data from Elasticsearch

This script:
1. Queries ES for error counts in 15-min windows (last 2 weeks)
2. Aligns to synchronized 15-minute boundaries (00:00-00:15, 00:15-00:30, etc.)
3. Groups by (day_of_week, hour_of_day, quarter_hour, namespace)
4. Calculates mean, stddev with 3-window smoothing
5. Initializes peak_statistics table

Usage:
    python3 collect_historical_peak_data.py

Database: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
"""

import psycopg2
import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime, timedelta, timezone
import os
import sys
import time
import urllib3
import logging
from statistics import mean, stdev

urllib3.disable_warnings()

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')  # Required: Set in .env file
}

ES_CONFIG = {
    'url': os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500'),
    'user': os.getenv('ES_USER', 'XX_PCBS_ES_READ'),
    'password': os.getenv('ES_PASSWORD'),  # Required: Set in .env file
    'indices': os.getenv('ES_INDICES', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')
}


def connect_db():
    """Connect to PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logger.info("✅ Connected to PostgreSQL")
        return conn
    except psycopg2.Error as e:
        logger.error(f"❌ DB Connection failed: {e}")
        sys.exit(1)


def generate_15min_windows(num_days=14):
    """
    Generate all synchronized 15-minute window boundaries for last N days.
    
    Windows are: 00:00-00:15, 00:15-00:30, 00:30-00:45, 00:45-01:00, etc.
    
    Returns: list of (window_start, window_end) tuples
    """
    now = datetime.now(timezone.utc)
    
    # Start from 14 days ago, aligned to the last 15-min boundary
    start_time = now - timedelta(days=num_days)
    
    # Align start_time to a 15-min boundary
    minute = start_time.minute
    aligned_minute = (minute // 15) * 15
    start_time = start_time.replace(minute=aligned_minute, second=0, microsecond=0)
    
    windows = []
    current_start = start_time
    
    while current_start < now:
        current_end = current_start + timedelta(minutes=15)
        if current_end <= now:
            windows.append((current_start, current_end))
        current_start = current_end
    
    logger.info(f"📊 Generated {len(windows)} 15-minute windows")
    return windows


def fetch_errors_for_windows(windows):
    """
    Fetch error counts for all windows from ES.
    
    Groups errors by: (day_of_week, hour_of_day, quarter_hour, namespace)
    Uses same approach as fetch_unlimited.py - fetches raw data then parses namespace from kubernetes.namespace field.
    
    Returns: dict with key=(day, hour, quarter, ns), value=[error_counts...]
    """
    
    logger.info(f"📥 Fetching error data for {len(windows)} windows...")
    
    # Query to fetch raw error data (like fetch_unlimited.py does)
    # This ensures we get namespace from kubernetes.namespace field for all data
    query = {
        "track_total_hits": True,
        "_source": ["@timestamp", "kubernetes.namespace"],  # Only fetch fields we need
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": windows[0][0].isoformat(), "lte": windows[-1][1].isoformat()}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "asc"}}],
        "size": 5000  # Fetch in batches
    }
    
    try:
        logger.info("🔄 Sending ES query (fetching raw data in batches)...")
        
        all_errors = []
        search_after = None
        batch_num = 0
        
        # Fetch all errors in batches (like fetch_unlimited.py)
        while True:
            batch_num += 1
            
            if search_after:
                query["search_after"] = search_after
            
            resp = requests.post(
                f"{ES_CONFIG['url']}/{ES_CONFIG['indices']}/_search",
                json=query,
                auth=HTTPBasicAuth(ES_CONFIG['user'], ES_CONFIG['password']),
                verify=False,
                timeout=180
            )
            
            if resp.status_code != 200:
                logger.error(f"❌ ES query failed: {resp.status_code}")
                logger.error(resp.text[:500])
                return None
            
            data = resp.json()
            hits = data['hits']['hits']
            
            if not hits:
                logger.info(f"📊 Fetched {len(all_errors)} errors total from {batch_num-1} batches")
                break
            
            # Process hits and extract errors
            for hit in hits:
                source = hit.get('_source', {})
                ts_str = source.get('@timestamp', '')
                if ts_str:
                    all_errors.append({
                        'timestamp': ts_str,
                        'namespace': source.get('kubernetes', {}).get('namespace', 'unknown')
                    })
            
            logger.info(f"🔄 Batch {batch_num}... {len(hits)} hits | Total: {len(all_errors)}")
            
            # Set search_after for next batch
            if len(hits) < 5000:
                break
            
            search_after = hit['sort']
        
        # Now group errors by window and namespace
        windows_data = {}  # key: (day_of_week, hour, quarter, namespace), value: count
        
        for error in all_errors:
            ts_str = error['timestamp']
            namespace = error['namespace']
            
            # Parse timestamp
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            
            # Align to 15-min boundary (round up to next 15-min)
            minutes = ts.minute
            quarter = minutes // 15  # 0, 1, 2, 3
            aligned_minute = (quarter + 1) * 15  # Next 15-min boundary
            
            if aligned_minute >= 60:
                window_end = ts.replace(hour=(ts.hour + 1) % 24, minute=0, second=0, microsecond=0)
                if ts.hour == 23:  # Wrap to next day
                    window_end = window_end + timedelta(days=1)
            else:
                window_end = ts.replace(minute=aligned_minute, second=0, microsecond=0)
            
            day_of_week = window_end.weekday()  # 0=Monday
            hour_of_day = window_end.hour
            quarter_hour = (window_end.minute // 15) % 4
            
            key = (day_of_week, hour_of_day, quarter_hour, namespace)
            if key not in windows_data:
                windows_data[key] = 0
            windows_data[key] += 1
        
        logger.info(f"✅ Parsed {len(windows_data)} (day, hour, quarter, namespace) combinations from {len(all_errors)} errors")
        
        # Convert to format expected by rest of code
        windows_data_formatted = {}
        for (day, hour, quarter, ns), count in windows_data.items():
            key = (day, hour, quarter, ns)
            windows_data_formatted[key] = [count]  # Wrap in list for compatibility
        
        return windows_data_formatted
    
    except Exception as e:
        logger.error(f"❌ Exception fetching ES data: {e}")
        return None


def apply_3window_smoothing(values):
    """
    Apply 3-window smoothing to reduce outliers.
    
    Takes each value and averages with neighbors (±1 window).
    """
    if len(values) < 3:
        return values  # No smoothing for small datasets
    
    smoothed = []
    for i in range(len(values)):
        # Get surrounding values (±1 window)
        neighbors = []
        for j in range(max(0, i-1), min(len(values), i+2)):
            neighbors.append(values[j])
        smoothed.append(mean(neighbors))
    
    return smoothed


def calculate_statistics_and_insert(conn, windows_data):
    """Calculate mean/stddev with 3-window smoothing and insert into peak_statistics"""
    
    cursor = conn.cursor()
    inserted = 0
    
    logger.info("📊 Calculating statistics with 3-window smoothing...")
    
    try:
        for key, error_counts in windows_data.items():
            day_of_week, hour_of_day, quarter_hour, namespace = key
            
            # Apply 3-window smoothing
            smoothed_counts = apply_3window_smoothing(error_counts)
            
            # Calculate mean and stddev
            mean_errors = mean(smoothed_counts) if smoothed_counts else 0
            
            if len(smoothed_counts) > 1:
                stddev_errors = stdev(smoothed_counts)
            else:
                stddev_errors = 0
            
            samples_count = len(error_counts)
            
            # UPSERT into ailog_peak.peak_statistics
            cursor.execute("""
                INSERT INTO ailog_peak.peak_statistics 
                (day_of_week, hour_of_day, quarter_hour, namespace, 
                 mean_errors, stddev_errors, samples_count, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
                DO UPDATE SET
                    mean_errors = EXCLUDED.mean_errors,
                    stddev_errors = EXCLUDED.stddev_errors,
                    samples_count = EXCLUDED.samples_count,
                    last_updated = EXCLUDED.last_updated
            """, (
                day_of_week,
                hour_of_day,
                quarter_hour,
                namespace,
                mean_errors,
                stddev_errors,
                samples_count,
                datetime.now(timezone.utc)
            ))
            inserted += 1
        
        conn.commit()
        logger.info(f"✅ Inserted/updated {inserted} statistics rows")
        
        # Log some sample statistics
        cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        total_rows = cursor.fetchone()[0]
        logger.info(f"📊 ailog_peak.peak_statistics table now has {total_rows} total rows")
    
    except psycopg2.Error as e:
        logger.error(f"❌ Insert failed: {e}")
        conn.rollback()
    finally:
        cursor.close()


def main():
    """Main initialization"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Collect historical peak data from Elasticsearch')
    parser.add_argument('--days', type=int, default=1, help='Number of days to collect (default: 1)')
    args = parser.parse_args()
    
    start_time = time.time()
    
    logger.info("="*60)
    logger.info(f"Phase 1b: Collect Historical Peak Data (last {args.days} days)")
    logger.info("="*60)
    
    # Connect to DB
    conn = connect_db()
    
    # Generate synchronized 15-min windows for last N days
    windows = generate_15min_windows(num_days=args.days)
    
    # Fetch error data from ES
    windows_data = fetch_errors_for_windows(windows)
    
    if windows_data:
        # Calculate and insert statistics
        calculate_statistics_and_insert(conn, windows_data)
    
    conn.close()
    
    elapsed = time.time() - start_time
    logger.info(f"✅ Collection complete ({elapsed/60:.1f} minutes)")
    logger.info("="*60)


if __name__ == '__main__':
    main()

