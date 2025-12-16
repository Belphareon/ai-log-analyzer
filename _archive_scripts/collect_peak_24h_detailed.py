#!/usr/bin/env python3
"""
Collect peak data for last 24 hours - DETAILED analysis
1. Fetch from ES WITHOUT aggregation limit
2. Parse into 15-min windows by namespace
3. Save to JSON for verification
4. Calculate statistics with smoothing
"""

import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from statistics import mean, stdev
import os
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

ES_CONFIG = {
    'url': os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500'),
    'user': os.getenv('ES_USER', 'XX_PCBS_ES_READ'),
    'password': os.getenv('ES_PASSWORD'),  # Required: Set in .env file
    'indices': os.getenv('ES_INDICES', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')
}

def fetch_errors_24h():
    """Fetch ALL errors for last 24h using aggregation (track_total_hits)"""
    
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=24)
    
    logger.info(f"Fetching errors from {start.isoformat()} to {now.isoformat()}")
    
    # Query with proper aggregation
    query = {
        "track_total_hits": True,
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": start.isoformat(), "lte": now.isoformat()}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "aggs": {
            "by_15min_window": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": "15m"
                },
                "aggs": {
                    "by_namespace": {
                        "terms": {
                            "field": "kubernetes.namespace",
                            "size": 100,  # Get up to 100 namespace per window
                            "order": {"_count": "desc"}
                        }
                    }
                }
            }
        },
        "size": 0
    }
    
    try:
        logger.info("🔄 Sending ES query...")
        resp = requests.post(
            f"{ES_CONFIG['url']}/{ES_CONFIG['indices']}/_search",
            json=query,
            auth=HTTPBasicAuth(ES_CONFIG['user'], ES_CONFIG['password']),
            verify=False,
            timeout=180
        )
        
        if resp.status_code != 200:
            logger.error(f"ES query failed: {resp.status_code}")
            logger.error(resp.text[:500])
            return None, None
        
        data = resp.json()
        total_errors = data['hits']['total']['value']
        
        logger.info(f"✅ Total ERROR logs: {total_errors:,}")
        
        # Extract window data
        windows_data = defaultdict(lambda: defaultdict(int))
        buckets = data['aggregations']['by_15min_window']['buckets']
        
        logger.info(f"📊 Processing {len(buckets)} 15-minute windows...")
        
        for bucket in buckets:
            ts_str = bucket['key_as_string']
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            
            # Window boundaries
            window_start = ts
            window_end = ts + timedelta(minutes=15)
            
            day_of_week = window_end.weekday()
            hour_of_day = window_end.hour
            quarter_hour = (window_end.minute // 15) % 4
            
            # Get all namespaces in this window
            ns_buckets = bucket['by_namespace']['buckets']
            
            for ns_bucket in ns_buckets:
                namespace = ns_bucket['key']
                error_count = ns_bucket['doc_count']
                
                key = (day_of_week, hour_of_day, quarter_hour, namespace)
                windows_data[key]['count'] = error_count
                windows_data[key]['window_start'] = window_start.isoformat()
                windows_data[key]['window_end'] = window_end.isoformat()
        
        logger.info(f"✅ Extracted {len(windows_data)} (window, namespace) combinations")
        
        return windows_data, total_errors
    
    except Exception as e:
        logger.error(f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def apply_3window_smoothing(values):
    """Apply 3-window smoothing"""
    if len(values) < 3:
        return values
    
    smoothed = []
    for i in range(len(values)):
        neighbors = []
        for j in range(max(0, i-1), min(len(values), i+2)):
            neighbors.append(values[j])
        smoothed.append(mean(neighbors))
    
    return smoothed


def calculate_statistics(windows_data):
    """Group into time patterns and calculate statistics with smoothing"""
    
    logger.info("📊 Grouping by time pattern (day, hour, quarter, namespace)...")
    
    pattern_data = defaultdict(list)
    
    for (day, hour, qtr, ns), window_info in windows_data.items():
        count = window_info['count']
        key = (day, hour, qtr, ns)
        pattern_data[key].append(count)
    
    statistics = {}
    
    for key, counts in pattern_data.items():
        # Apply 3-window smoothing
        if len(counts) >= 3:
            smoothed = apply_3window_smoothing(counts)
        else:
            smoothed = counts
        
        mean_errors = mean(smoothed) if smoothed else 0
        stddev_errors = stdev(smoothed) if len(smoothed) > 1 else 0
        
        statistics[key] = {
            'mean': mean_errors,
            'stddev': stddev_errors,
            'samples': len(counts),
            'raw': counts,
            'smoothed': smoothed
        }
    
    logger.info(f"✅ Calculated statistics for {len(statistics)} patterns")
    return statistics


def main():
    logger.info("="*80)
    logger.info("🚀 Peak Data Collection - Last 24 Hours (Detailed)")
    logger.info("="*80)
    logger.info("")
    
    # Fetch errors
    windows_data, total_errors = fetch_errors_24h()
    
    if windows_data is None:
        logger.error("Failed to fetch data")
        return 1
    
    logger.info("")
    logger.info("="*80)
    logger.info("📊 DETAILED ANALYSIS - LAST 24 HOURS")
    logger.info("="*80)
    logger.info("")
    
    # Get namespaces
    namespaces = sorted(set(key[3] for key in windows_data.keys()))
    logger.info(f"📦 Unique namespaces: {len(namespaces)}")
    for ns in namespaces:
        logger.info(f"   - {ns}")
    logger.info("")
    
    # Calculate statistics
    statistics = calculate_statistics(windows_data)
    
    # Breakdown by namespace
    logger.info("📈 Error distribution by namespace:")
    logger.info(f"   {'Namespace':<30} {'Patterns':<10} {'Avg Mean':<12} {'Total Samples'}")
    logger.info(f"   {'-'*75}")
    
    ns_stats = {}
    for ns in namespaces:
        ns_data = [s for k, s in statistics.items() if k[3] == ns]
        avg_mean = mean([s['mean'] for s in ns_data]) if ns_data else 0
        total_samples = sum([s['samples'] for s in ns_data])
        
        ns_stats[ns] = {
            'patterns': len(ns_data),
            'avg_mean': avg_mean,
            'total_samples': total_samples
        }
        
        logger.info(f"   {ns:<30} {len(ns_data):<10} {avg_mean:>11.2f}  {total_samples:>12}")
    
    logger.info("")
    logger.info("📋 Smoothing verification (first 3 patterns per namespace):")
    logger.info("")
    
    for ns in namespaces[:2]:  # Show first 2 namespaces
        ns_patterns = [(k, s) for k, s in statistics.items() if k[3] == ns][:3]
        
        logger.info(f"   Namespace: {ns}")
        for (day, hour, qtr, ns_key), stats in ns_patterns:
            day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            logger.info(f"      {day_names[day]} {hour:02d}:{qtr*15:02d}")
            logger.info(f"         Raw:      {stats['raw']}")
            logger.info(f"         Smoothed: {[f'{x:.1f}' for x in stats['smoothed']]}")
        logger.info("")
    
    logger.info("="*80)
    logger.info("✅ Analysis complete!")
    logger.info(f"   Total errors: {total_errors:,}")
    logger.info(f"   Unique namespaces: {len(namespaces)}")
    logger.info(f"   Statistics patterns: {len(statistics)}")
    logger.info("="*80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
