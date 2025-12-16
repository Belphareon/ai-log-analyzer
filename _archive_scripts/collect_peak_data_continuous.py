#!/usr/bin/env python3
"""
Phase 2: Continuous Peak Data Collection
Runs every 15 minutes via Kubernetes CronJob

This script:
1. Queries ES for ERROR logs in last 15 minutes
2. Groups by namespace and counts errors
3. Inserts into peak_raw_data table
4. Updates rolling average in peak_statistics (only when NO peak detected)
5. Logs execution time and row count

Usage:
    python3 collect_peak_data_continuous.py

Environment Variables (from K8s ConfigMap/Secrets):
    DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    ES_URL, ES_USER, ES_PASSWORD
    ES_INDICES (optional: "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*")
"""

import psycopg2
from psycopg2 import sql
import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime, timedelta, timezone
import os
import sys
import time
import urllib3
import logging

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
    'password': os.getenv('DB_PASSWORD', 'y01d40Mmdys/lbDE')
}

ES_CONFIG = {
    'url': os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500'),
    'user': os.getenv('ES_USER', 'XX_PCBS_ES_READ'),
    'password': os.getenv('ES_PASSWORD', 'ta@@swLT69EX.6164'),
    'indices': os.getenv('ES_INDICES', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')
}

# Threshold for peak detection (mean + 1.5*mean = 50% spike)
PEAK_THRESHOLD_MULTIPLIER = 1.5


def get_current_window_boundaries():
    """
    Get the 15-minute window that should be collected NOW.
    
    Windows are synchronized to clock:
    - 00:00-00:15, 00:15-00:30, 00:30-00:45, 00:45-01:00, etc.
    
    Collection timing (with 1 minute buffer for ES delay):
    - At 10:16: collect window 10:00-10:15
    - At 10:31: collect window 10:15-10:30
    - At 10:46: collect window 10:30-10:45
    - At 11:01: collect window 10:45-11:00
    
    Returns: (window_start, window_end) as datetime objects in UTC
    """
    now = datetime.now(timezone.utc)
    
    # Calculate which 15-min window we're currently in
    minute = now.minute
    quarter = minute // 15  # 0, 1, 2, or 3
    
    # Window END is the boundary we just passed (or about to pass)
    window_end_minute = (quarter + 1) * 15
    
    if window_end_minute == 60:
        # Wrap to next hour
        window_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        window_end = now.replace(minute=window_end_minute, second=0, microsecond=0)
    
    # Window START is 15 minutes before window_end
    window_start = window_end - timedelta(minutes=15)
    
    return window_start, window_end


def connect_db():
    """Connect to PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        logger.info("✅ Connected to PostgreSQL")
        return conn
    except psycopg2.Error as e:
        logger.error(f"❌ DB Connection failed: {e}")
        sys.exit(1)


def fetch_error_count_last_15min():
    """Fetch error count from ES for last 15 minutes, grouped by namespace"""
    
    window_start, window_end = get_current_window_boundaries()
    
    date_from = window_start.isoformat()
    date_to = window_end.isoformat()
    
    logger.info(f"📥 Fetching errors from {window_start.strftime('%H:%M')} to {window_end.strftime('%H:%M')} UTC")
    logger.info(f"   Window: {window_start.isoformat()} to {window_end.isoformat()}")
    
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "aggs": {
            "by_namespace": {
                "terms": {
                    "field": "kubernetes.namespace",
                    "size": 100
                }
            }
        },
        "size": 0  # We only want aggregations, not raw hits
    }
    
    try:
        resp = requests.post(
            f"{ES_CONFIG['url']}/{ES_CONFIG['indices']}/_search",
            json=query,
            auth=HTTPBasicAuth(ES_CONFIG['user'], ES_CONFIG['password']),
            verify=False,
            timeout=30
        )
        
        if resp.status_code != 200:
            logger.error(f"❌ ES query failed: {resp.status_code} - {resp.text[:200]}")
            return None
        
        data = resp.json()
        total_errors = data['hits']['total']['value']
        buckets = data['aggregations']['by_namespace']['buckets']
        
        # Parse namespace data
        namespace_counts = {}
        for bucket in buckets:
            namespace = bucket['key']
            count = bucket['doc_count']
            namespace_counts[namespace] = count
        
        logger.info(f"📊 Total errors: {total_errors}, Namespaces: {len(namespace_counts)}")
        
        return {
            'total': total_errors,
            'timestamp_start': fifteen_min_ago,
            'timestamp_end': now,
            'namespaces': namespace_counts
        }
    
    except Exception as e:
        logger.error(f"❌ Exception fetching ES data: {e}")
        return None


def insert_raw_data(conn, error_data):
    """Insert 15-min window data into peak_raw_data table"""
    
    if not error_data or not error_data['namespaces']:
        logger.warning("⚠️  No error data to insert")
        return 0
    
    cursor = conn.cursor()
    inserted = 0
    
    # Use window_end time for indexing (consistent with baseline)
    window_end = error_data['timestamp_end']
    day_of_week = window_end.weekday()  # 0=Monday, 6=Sunday
    hour_of_day = window_end.hour
    quarter_hour = (window_end.minute // 15) % 4
    
    try:
        for namespace, error_count in error_data['namespaces'].items():
            cursor.execute("""
                INSERT INTO peak_raw_data 
                (collection_timestamp, window_start, window_end, error_count, 
                 day_of_week, hour_of_day, quarter_hour, namespace)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                window_end,
                error_data['timestamp_start'],
                error_data['timestamp_end'],
                error_count,
                day_of_week,
                hour_of_day,
                quarter_hour,
                namespace
            ))
            inserted += 1
        
        conn.commit()
        logger.info(f"✅ Inserted {inserted} rows into peak_raw_data")
        return inserted
    
    except psycopg2.Error as e:
        logger.error(f"❌ Insert failed: {e}")
        conn.rollback()
        return 0
    finally:
        cursor.close()


def check_peak_and_update_stats(conn, error_data):
    """Check if current window is a peak, and update rolling average if not"""
    
    if not error_data or not error_data['namespaces']:
        logger.warning("⚠️  No data to check for peak")
        return
    
    cursor = conn.cursor()
    window_end = error_data['timestamp_end']
    day_of_week = window_end.weekday()
    hour_of_day = window_end.hour
    quarter_hour = (window_end.minute // 15) % 4
    
    peaks_detected = 0
    updates_made = 0
    
    try:
        for namespace, error_count in error_data['namespaces'].items():
            # Get baseline stats for this time window
            cursor.execute("""
                SELECT mean_errors, stddev_errors 
                FROM peak_statistics
                WHERE day_of_week = %s AND hour_of_day = %s 
                      AND quarter_hour = %s AND namespace = %s
            """, (day_of_week, hour_of_day, quarter_hour, namespace))
            
            row = cursor.fetchone()
            
            if not row:
                # No baseline yet - skip peak check, just log
                logger.debug(f"⚠️  No baseline for {namespace} at {hour_of_day}:{quarter_hour*15:02d}")
                continue
            
            mean_errors, stddev_errors = row
            
            # Check if this is a peak: error_count > mean + 1.5*mean
            threshold = mean_errors * (1 + PEAK_THRESHOLD_MULTIPLIER) if mean_errors else error_count + 1
            
            if error_count > threshold:
                logger.warning(f"🔴 PEAK DETECTED: {namespace} has {error_count} errors (threshold: {threshold:.0f})")
                peaks_detected += 1
                # During peak: DO NOT update peak_statistics to preserve baseline
            else:
                # Normal operation: update rolling average
                # Simple weighted average: (old_mean * samples + new_count) / (samples + 1)
                new_samples = (row[2] if len(row) > 2 else 1) + 1 if row[2] else 2
                
                cursor.execute("""
                    UPDATE peak_statistics
                    SET mean_errors = ((mean_errors * samples_count) + %s) / %s,
                        samples_count = %s,
                        last_updated = %s
                    WHERE day_of_week = %s AND hour_of_day = %s 
                          AND quarter_hour = %s AND namespace = %s
                """, (
                    error_count,
                    new_samples,
                    new_samples,
                    window_end,
                    day_of_week, hour_of_day, quarter_hour, namespace
                ))
                updates_made += 1
        
        conn.commit()
        
        if peaks_detected > 0:
            logger.warning(f"⚠️  {peaks_detected} peaks detected - baseline NOT updated to preserve statistics")
        if updates_made > 0:
            logger.info(f"✅ Updated rolling average for {updates_made} namespaces")
    
    except psycopg2.Error as e:
        logger.error(f"❌ Peak check/update failed: {e}")
        conn.rollback()
    finally:
        cursor.close()


def main():
    """Main collection cycle"""
    start_time = time.time()
    
    logger.info("="*60)
    logger.info("Continuous Peak Data Collection")
    logger.info("="*60)
    
    # Connect to DB
    conn = connect_db()
    
    # Fetch current error data
    error_data = fetch_error_count_last_15min()
    
    if error_data:
        # Insert raw data
        insert_raw_data(conn, error_data)
        
        # Check for peaks and update rolling average
        check_peak_and_update_stats(conn, error_data)
    
    conn.close()
    
    elapsed = time.time() - start_time
    logger.info(f"✅ Collection complete ({elapsed:.1f}s)")
    logger.info("="*60)


if __name__ == '__main__':
    main()
