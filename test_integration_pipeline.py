#!/usr/bin/env python3
"""
Integration Test - Complete Error Analysis Pipeline
Tests: data loading → trace extraction → detailed reporting
"""
import json
import sys
import subprocess
from pathlib import Path
from collections import defaultdict
import tempfile
import time

def print_section(title):
    """Print formatted section title"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print('='*80)

def test_data_loading(batch_dir):
    """Test 1: Data loading"""
    print_section("TEST 1: Data Loading")
    
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"))
    total_errors = 0
    batch_errors = {}
    
    for batch_file in batch_files:
        if "summary" in str(batch_file):
            continue
        with open(batch_file) as f:
            data = json.load(f)
            errors = data.get('errors', [])
            batch_errors[batch_file.name] = len(errors)
            total_errors += len(errors)
            if len(errors) > 0:
                print(f"  ✓ {batch_file.name}: {len(errors):4d} errors")
    
    print(f"\n  ✅ Total loaded: {total_errors:,} errors")
    return batch_errors, total_errors

def test_trace_extraction(batch_dir, total_errors):
    """Test 2: Trace extraction"""
    print_section("TEST 2: Trace Extraction")
    
    # Load all errors from batches
    all_errors = []
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"))
    
    for batch_file in batch_files:
        if "summary" in str(batch_file):
            continue
        with open(batch_file) as f:
            data = json.load(f)
            all_errors.extend(data.get('errors', []))
    
    # Create temporary input file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp_input:
        input_data = {
            'period_start': '2025-11-12T08:30:00',
            'period_end': '2025-11-12T12:30:00',
            'errors': all_errors
        }
        json.dump(input_data, tmp_input)
        input_file = tmp_input.name
    
    # Run trace extractor
    output_file = tempfile.mktemp(suffix='.json')
    
    print(f"  Running trace_extractor.py...")
    start = time.time()
    result = subprocess.run(
        ['python3', 'trace_extractor.py', '--input', input_file, '--output', output_file],
        capture_output=True,
        text=True
    )
    elapsed = time.time() - start
    
    if result.returncode != 0:
        print(f"  ❌ FAILED: {result.stderr}")
        return None, None
    
    # Parse output
    with open(output_file) as f:
        trace_data = json.load(f)
    
    root_causes = trace_data['root_causes']
    stats = trace_data['stats']
    
    print(f"  ✅ Extraction completed in {elapsed:.2f}s")
    print(f"     - Unique traces: {stats['total_traces']:,}")
    print(f"     - Root causes found: {len(root_causes)}")
    
    # Show top root causes
    print(f"\n  Top 5 Root Causes:")
    for cause in root_causes[:5]:
        print(f"    {cause['rank']}. {cause['app']}: {cause['errors_count']} errors ({cause['errors_percent']:.1f}%)")
    
    return trace_data, output_file

def test_report_generation(trace_file):
    """Test 3: Detailed Report Generation"""
    print_section("TEST 3: Detailed Report Generation")
    
    # Run detailed report generator
    output_file = tempfile.mktemp(suffix='.md')
    
    print(f"  Running trace_report_detailed.py...")
    start = time.time()
    result = subprocess.run(
        ['python3', 'trace_report_detailed.py', '--input', trace_file, '--output', output_file],
        capture_output=True,
        text=True
    )
    elapsed = time.time() - start
    
    if result.returncode != 0:
        print(f"  ❌ FAILED: {result.stderr}")
        return None
    
    # Parse report
    with open(output_file) as f:
        report = f.read()
    
    print(f"  ✅ Report generated in {elapsed:.2f}s")
    
    # Verify content
    checks = {
        'Has Overview': '## 📊 Overview' in report,
        'Has App Distribution': '## 🎯 App Impact Distribution' in report,
        'Has Namespace Distribution': '## �� Namespace Distribution' in report,
        'Has Root Causes': '## 🔍 Concrete Root Causes' in report,
    }
    
    print(f"\n  Report structure validation:")
    for check, status in checks.items():
        print(f"    {'✓' if status else '✗'} {check}")
    
    return output_file

def main():
    """Run complete integration test"""
    print("\n" + "="*80)
    print("  🧪 INTEGRATION TEST - Error Analysis Pipeline")
    print("="*80)
    
    batch_dir = sys.argv[1] if len(sys.argv) > 1 else "data/batches/2025-11-12"
    
    # Test 1: Data loading
    try:
        batch_errors, total_errors = test_data_loading(batch_dir)
    except Exception as e:
        print(f"  ❌ Test 1 failed: {e}")
        return 1
    
    # Test 2: Trace extraction
    try:
        trace_data, trace_file = test_trace_extraction(batch_dir, total_errors)
        if not trace_data:
            return 1
    except Exception as e:
        print(f"  ❌ Test 2 failed: {e}")
        return 1
    
    # Test 3: Report generation
    try:
        report_file = test_report_generation(trace_file)
        if not report_file:
            return 1
    except Exception as e:
        print(f"  ❌ Test 3 failed: {e}")
        return 1
    
    # Summary
    print("\n" + "="*80)
    print("  🎉 INTEGRATION TEST COMPLETED")
    print("="*80)
    print(f"  Pipeline: Data → Extraction → Reporting")
    print(f"  Total errors: {total_errors:,}")
    print(f"  Root causes: {len(trace_data['root_causes'])}")
    print()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
