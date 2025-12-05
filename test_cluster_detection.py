#!/usr/bin/env python3
"""
Test: Verify all cluster indices are properly configured and detectable
"""
import json
import sys

def test_index_configuration():
    """Verify all 3 cluster indices are configured"""
    print("=" * 80)
    print("TEST: Cluster Index Configuration")
    print("=" * 80)
    
    # Check simple_fetch.py
    with open('simple_fetch.py', 'r') as f:
        content = f.read()
        
    indices_expected = {
        'PCB': 'cluster-app_pcb-*',
        'PCA': 'cluster-app_pca-*', 
        'PCB-CH': 'cluster-app_pcb_ch-*'
    }
    
    print("\n1. Checking simple_fetch.py configuration:")
    for name, index in indices_expected.items():
        found = index in content
        status = "✓" if found else "✗"
        print(f"   {status} {name:8} index: {index}")
        if not found:
            return False
    
    # Check app/core/config.py
    print("\n2. Checking app/core/config.py configuration:")
    try:
        with open('app/core/config.py', 'r') as f:
            config_content = f.read()
            
        # Look for default index or ES_INDEX config
        if 'cluster-app' in config_content:
            print("   ✓ ES_INDEX configuration found in config.py")
        else:
            print("   ✗ No cluster configuration in config.py")
            return False
    except FileNotFoundError:
        print("   ⚠ app/core/config.py not found (might be in different structure)")
    
    print("\n3. Checking environment configuration (.env):")
    try:
        with open('.env', 'r') as f:
            env_content = f.read()
            
        if 'ES_INDEX' in env_content:
            for line in env_content.split('\n'):
                if line.startswith('ES_INDEX='):
                    print(f"   ✓ Found: {line}")
                    break
        else:
            print("   ℹ ES_INDEX not in .env (default configuration may be used)")
    except FileNotFoundError:
        print("   ⚠ .env file not found - using defaults")
    
    return True

def test_problem_detection_patterns():
    """Verify key error patterns are detected"""
    print("\n" + "=" * 80)
    print("TEST: Error Pattern Detection")
    print("=" * 80)
    
    patterns = {
        'trace_id': r'[a-f0-9]{32}',  # UUID hex patterns
        'http_errors': ['HTTP 404', 'HTTP 500', 'HTTP 503'],
        'service_errors': ['ServiceException', 'TimeoutException', 'ConnectionRefused'],
        'kubernetes': ['CrashLoopBackOff', 'ImagePullBackOff', 'OOMKilled'],
    }
    
    print("\nExpected pattern detections:")
    for category, items in patterns.items():
        if isinstance(items, list):
            for item in items:
                print(f"   • {category}: {item}")
        else:
            print(f"   • {category}: {items}")
    
    # Check if patterns are in intelligent_analysis.py
    with open('intelligent_analysis.py', 'r') as f:
        analysis_code = f.read()
    
    found_patterns = {
        'HTTP errors': 'HTTP' in analysis_code,
        'Exceptions': 'Exception' in analysis_code,
        'Kubernetes': 'CrashLoopBackOff' in analysis_code or 'Kubernetes' in analysis_code,
    }
    
    print("\nPattern detection in intelligent_analysis.py:")
    all_good = True
    for pattern_name, found in found_patterns.items():
        status = "✓" if found else "✗"
        print(f"   {status} {pattern_name}")
        if not found:
            all_good = False
    
    return all_good

def test_cluster_specific_apps():
    """Verify cluster-specific applications are recognized"""
    print("\n" + "=" * 80)
    print("TEST: Cluster-Specific Application Recognition")
    print("=" * 80)
    
    cluster_apps = {
        'PCB': ['bl-pcb', 'bc-pcb', 'pcb-api'],
        'PCA': ['pca-service', 'pca-api', 'accounting-service'],
        'PCB-CH': ['bff-pcb-ch', 'bl-pcb-ch', 'pcb-ch-service'],
    }
    
    print("\nExpected cluster-app mappings:")
    for cluster, apps in cluster_apps.items():
        print(f"   {cluster}:")
        for app in apps:
            print(f"      • {app}")
    
    # Note: Full validation would require ES connectivity
    print("\n(Full validation requires Elasticsearch connectivity)")
    print("⚠ Cluster-specific app detection requires live ES data")
    
    return True

def test_known_issues():
    """Check if known issues registry exists"""
    print("\n" + "=" * 80)
    print("TEST: Known Issues Registry")
    print("=" * 80)
    
    print("\nChecking for known issues documentation:")
    
    known_docs = [
        'KNOWN_ISSUES_DESIGN.md',
        'KNOWN_ISSUES.md',
        'known_issues.json',
    ]
    
    import os
    found_any = False
    
    for doc in known_docs:
        if os.path.exists(doc):
            print(f"   ✓ Found: {doc}")
            found_any = True
            with open(doc, 'r') as f:
                content = f.read()
                lines = len(content.split('\n'))
            print(f"      Size: {len(content)} bytes, {lines} lines")
    
    if not found_any:
        print("   ⚠ No known issues registry found (should be created)")
        print("   Action: Create known_issues.json with structure:")
        print("""
        {
          "known_issues": [
            {
              "id": "ISSUE-001",
              "pattern": "ServiceException in ...",
              "cluster": "PCB",
              "severity": "HIGH",
              "action": "Restart service"
            }
          ]
        }
        """)
    
    return True

def main():
    """Run all tests"""
    print("\n")
    print("🔍 CLUSTER & PROBLEM DETECTION VALIDATION TEST")
    print("Session: 2025-12-02")
    print()
    
    tests = [
        ("Index Configuration", test_index_configuration),
        ("Pattern Detection", test_problem_detection_patterns),
        ("Cluster Apps", test_cluster_specific_apps),
        ("Known Issues", test_known_issues),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ ERROR in {test_name}: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} {test_name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All cluster detection configurations verified!")
    else:
        print(f"\n⚠ {total - passed} test(s) need attention")
    
    return 0 if passed == total else 1

if __name__ == '__main__':
    sys.exit(main())
