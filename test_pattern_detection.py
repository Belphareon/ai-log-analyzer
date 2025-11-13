#!/usr/bin/env python3
"""Test pattern detection na reálných datech"""
import json
import sys
from collections import Counter
from app.services.pattern_detector import pattern_detector

def test_normalization():
    """Test normalizace zpráv"""
    print("=" * 80)
    print("TEST 1: Normalizace zpráv")
    print("=" * 80)
    
    test_cases = [
        ("Card 12345 not found", "Card 67890 not found"),
        ("Timeout after 30000ms", "Timeout after 45000ms"),
        ("Connection refused to 192.168.1.1:8080", "Connection refused to 10.0.0.1:8080"),
        ("UUID: 550e8400-e29b-41d4-a716-446655440000", "UUID: 123e4567-e89b-12d3-a456-426614174000"),
        ("Error at 2025-11-13T10:45:32Z", "Error at 2025-11-12T14:23:11Z"),
    ]
    
    for msg1, msg2 in test_cases:
        norm1 = pattern_detector.normalize_message(msg1)
        norm2 = pattern_detector.normalize_message(msg2)
        match = "✅ MATCH" if norm1 == norm2 else "❌ MISMATCH"
        print(f"\n{match}")
        print(f"  Original 1: {msg1}")
        print(f"  Original 2: {msg2}")
        print(f"  Normalized: {norm1}")
        if norm1 != norm2:
            print(f"  Norm2:      {norm2}")
    
    print()

def test_clustering_on_real_data(data_file):
    """Test clustering na reálných datech"""
    print("=" * 80)
    print(f"TEST 2: Clustering na reálných datech ({data_file})")
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
    
    # Cluster errors
    print(f"\n🔄 Clustering...")
    clusters = pattern_detector.cluster_errors(errors)
    
    print(f"\n📈 Clustering Results:")
    print(f"  Unique patterns: {len(clusters)}")
    print(f"  Compression ratio: {total}/{len(clusters)} = {total/len(clusters):.1f}x")
    
    # Top 10 patterns
    print(f"\n🔝 Top 10 patterns:")
    sorted_patterns = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
    
    for i, (pattern, errors_in_cluster) in enumerate(sorted_patterns[:10], 1):
        count = len(errors_in_cluster)
        pct = (count / total) * 100
        
        # Get sample error details
        sample = errors_in_cluster[0]
        app_name = sample.get('app_name', 'unknown')
        
        print(f"\n  {i}. [{count:4d} errors, {pct:5.1f}%] {app_name}")
        print(f"     Pattern: {pattern[:100]}...")
        
        # Show original message sample
        orig_msg = sample.get('message', '')[:150]
        print(f"     Sample:  {orig_msg}...")
        
        # Namespace breakdown
        namespaces = Counter(e.get('namespace', 'unknown') for e in errors_in_cluster)
        ns_str = ", ".join(f"{ns}: {cnt}" for ns, cnt in namespaces.most_common(3))
        print(f"     Namespaces: {ns_str}")
    
    print()

def test_pattern_quality(data_file):
    """Test kvality pattern matching - ukázat false positives/negatives"""
    print("=" * 80)
    print("TEST 3: Kvalita pattern matching")
    print("=" * 80)
    
    try:
        with open(data_file) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Soubor {data_file} nenalezen")
        return
    
    errors = data.get('errors', [])
    clusters = pattern_detector.cluster_errors(errors)
    
    # Find cluster with most variety
    print("\n🔍 Kontrola variety v top clusterech:")
    sorted_patterns = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
    
    for pattern, errors_in_cluster in sorted_patterns[:3]:
        if len(errors_in_cluster) < 5:
            continue
            
        print(f"\n  Pattern: {pattern[:80]}...")
        print(f"  Count: {len(errors_in_cluster)}")
        
        # Show 5 random original messages
        import random
        samples = random.sample(errors_in_cluster, min(5, len(errors_in_cluster)))
        print("  Samples:")
        for s in samples:
            msg = s.get('message', '')[:120]
            print(f"    - {msg}...")
        
        # Check if they really match
        unique_msgs = set(e.get('message', '') for e in errors_in_cluster)
        if len(unique_msgs) > len(errors_in_cluster) * 0.5:
            print("  ⚠️  Vysoká variabilita - možná příliš obecný pattern")
        else:
            print("  ✅ Nízká variabilita - pattern je dobrý")
    
    print()

def main():
    # Test normalization
    test_normalization()
    
    # Test clustering on real data
    # Zkusíme nejnovější dostupná data
    test_files = [
        'data/last_hour_v2.json',
        'data/batches/2025-11-12/batch_09.json',
        'data/batches/2025-11-12/batch_08.json',
    ]
    
    for test_file in test_files:
        try:
            test_clustering_on_real_data(test_file)
            test_pattern_quality(test_file)
            break  # Success, stop trying
        except FileNotFoundError:
            continue
    
    print("\n" + "=" * 80)
    print("✅ Pattern Detection Testing Complete")
    print("=" * 80)

if __name__ == '__main__':
    main()
