#!/usr/bin/env python3
"""Test temporal clustering - detekce error bursts"""
import json
from datetime import datetime
from collections import Counter

def find_temporal_clusters(errors, window_minutes=15):
    """Find error clusters within time window"""
    if not errors:
        return []
    
    # Sort by timestamp
    sorted_errors = sorted(errors, key=lambda x: x.get('timestamp', ''))
    
    clusters = []
    current_cluster = []
    cluster_start = None
    
    for e in sorted_errors:
        ts_str = e.get('timestamp', '')
        if not ts_str:
            continue
        
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except:
            continue
        
        if not current_cluster:
            current_cluster = [e]
            cluster_start = ts
            continue
        
        # Check if within window
        time_diff = (ts - cluster_start).total_seconds() / 60
        
        if time_diff <= window_minutes:
            current_cluster.append(e)
        else:
            # Save cluster if significant (>5 errors)
            if len(current_cluster) >= 5:
                clusters.append({
                    'start': cluster_start,
                    'count': len(current_cluster),
                    'errors': current_cluster,
                    'window_minutes': window_minutes
                })
            
            # Start new cluster
            current_cluster = [e]
            cluster_start = ts
    
    # Don't forget last cluster
    if len(current_cluster) >= 5:
        clusters.append({
            'start': cluster_start,
            'count': len(current_cluster),
            'errors': current_cluster,
            'window_minutes': window_minutes
        })
    
    return clusters

def test_temporal_clustering(data_file):
    """Test temporal clustering na reálných datech"""
    print("=" * 80)
    print(f"TEST: Temporal Clustering ({data_file})")
    print("=" * 80)
    
    # Load data
    try:
        with open(data_file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Soubor {data_file} nenalezen")
        return
    
    errors = data.get('errors', [])
    total = len(errors)
    
    print(f"\n📊 Data Stats:")
    print(f"  Total errors: {total}")
    print(f"  Period: {data.get('period_start')} → {data.get('period_end')}")
    
    # Test with different window sizes
    for window_minutes in [5, 10, 15, 30]:
        print(f"\n{'='*80}")
        print(f"Window: {window_minutes} minutes")
        print(f"{'='*80}")
        
        clusters = find_temporal_clusters(errors, window_minutes)
        
        print(f"\n📈 Results:")
        print(f"  Clusters found: {len(clusters)}")
        
        if not clusters:
            print("  No significant clusters (need >5 errors per cluster)")
            continue
        
        # Stats
        total_in_clusters = sum(c['count'] for c in clusters)
        pct_in_clusters = (total_in_clusters / total * 100) if total > 0 else 0
        
        print(f"  Errors in clusters: {total_in_clusters}/{total} ({pct_in_clusters:.1f}%)")
        print(f"  Avg cluster size: {total_in_clusters/len(clusters):.1f}")
        
        # Top 5 clusters
        sorted_clusters = sorted(clusters, key=lambda x: x['count'], reverse=True)
        
        print(f"\n🔝 Top clusters:")
        for i, cluster in enumerate(sorted_clusters[:5], 1):
            start_time = cluster['start'].strftime('%H:%M:%S')
            count = cluster['count']
            
            # Get affected apps
            apps = Counter(e.get('app', 'unknown') for e in cluster['errors'])
            top_apps = ", ".join(f"{app}({cnt})" for app, cnt in apps.most_common(3))
            
            # Get affected namespaces
            namespaces = Counter(e.get('namespace', 'unknown') for e in cluster['errors'])
            top_ns = ", ".join(f"{ns}({cnt})" for ns, cnt in namespaces.most_common(3))
            
            print(f"\n  {i}. {start_time} - {count} errors in {window_minutes}min")
            print(f"     Apps: {top_apps}")
            print(f"     Namespaces: {top_ns}")
            
            # Show pattern diversity
            from app.services.pattern_detector import pattern_detector
            patterns = set(pattern_detector.normalize_message(e.get('message', '')) 
                          for e in cluster['errors'])
            print(f"     Unique patterns: {len(patterns)}")
            
            if len(patterns) <= 3:
                print(f"     ⚠️  SINGLE ISSUE - stejný typ chyby opakovaně")
            elif len(patterns) > count * 0.7:
                print(f"     🔥 CASCADE FAILURE - různé typy chyb najednou")
            else:
                print(f"     📊 MIXED - kombinace několika problémů")

def main():
    # Test on available data
    test_files = [
        'data/last_hour_v2.json',
        'data/batches/2025-11-12/batch_09.json',
        'data/batches/2025-11-12/batch_08.json',
    ]
    
    for test_file in test_files:
        try:
            test_temporal_clustering(test_file)
            break  # Success, stop trying
        except FileNotFoundError:
            continue
    
    print("\n" + "=" * 80)
    print("✅ Temporal Clustering Testing Complete")
    print("=" * 80)

if __name__ == '__main__':
    main()
