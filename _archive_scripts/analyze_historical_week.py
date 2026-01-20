#!/usr/bin/env python3
"""Analyze Oct 27 - Nov 2, 2024 - daily reports"""
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.services.trend_analyzer import trend_analyzer
from app.services.pattern_detector import pattern_detector

REPORT_DIR = Path("/tmp/weekly_analysis_oct27_nov2")
REPORT_DIR.mkdir(exist_ok=True)

async def analyze_day(date_str: str, year: int, month: int, day: int):
    """Analyze single day"""
    print(f"�� Analyzing {date_str}...")
    
    time_from = datetime(year, month, day, 0, 0, 0)
    time_to = datetime(year, month, day, 23, 59, 59)
    
    try:
        # Fetch errors
        errors, total = await trend_analyzer.fetch_errors_batch(
            time_from=time_from,
            time_to=time_to,
            batch_size=10000,
            max_total=50000
        )
        
        coverage = trend_analyzer.calculate_coverage(len(errors), total)
        
        # Cluster
        clusters = pattern_detector.cluster_errors(errors)
        
        # Build report
        patterns = []
        for normalized, error_list in clusters.items():
            if len(error_list) < 3:
                continue
            
            # Namespace breakdown
            namespaces = {}
            for e in error_list:
                ns = e.get('namespace', 'unknown')
                namespaces[ns] = namespaces.get(ns, 0) + 1
            
            ns_extrapolated = {}
            for ns, count in namespaces.items():
                ns_extrapolated[ns] = int((count / len(errors)) * total) if len(errors) > 0 else count
            
            sample_count = len(error_list)
            extrapolated_count = int((sample_count / len(errors)) * total) if len(errors) > 0 else sample_count
            
            error_code = pattern_detector.extract_error_code(error_list[0]['message'])
            
            patterns.append({
                'fingerprint': normalized[:50],
                'error_code': error_code,
                'message_sample': error_list[0]['message'][:150],
                'count': extrapolated_count,
                'sample_count': sample_count,
                'affected_apps': list(set(e['app'] for e in error_list))[:5],
                'affected_namespaces': ns_extrapolated,
                'first_seen': min(e['timestamp'] for e in error_list).isoformat(),
                'last_seen': max(e['timestamp'] for e in error_list).isoformat(),
            })
        
        # Sort by count
        patterns.sort(key=lambda x: x['count'], reverse=True)
        
        report = {
            'date': date_str,
            'period_start': time_from.isoformat(),
            'period_end': time_to.isoformat(),
            'total_errors': total,
            'sample_size': len(errors),
            'coverage_percent': coverage,
            'patterns_found': len(patterns),
            'top_30_patterns': patterns[:30]
        }
        
        # Save
        output_file = REPORT_DIR / f"daily_{date_str}.json"
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"  ✅ {date_str}: {total:,} errors, {len(patterns)} patterns, {coverage:.1f}% coverage")
        
        return report
        
    except Exception as e:
        print(f"  ❌ {date_str}: Error - {e}")
        return None

async def main():
    print("=" * 80)
    print("WEEKLY ANALYSIS: Oct 27 - Nov 2, 2024")
    print("=" * 80)
    print()
    
    days = [
        ("2024-10-27", 2024, 10, 27),
        ("2024-10-28", 2024, 10, 28),
        ("2024-10-29", 2024, 10, 29),
        ("2024-10-30", 2024, 10, 30),
        ("2024-10-31", 2024, 10, 31),
        ("2024-11-01", 2024, 11, 1),
        ("2024-11-02", 2024, 11, 2),
    ]
    
    reports = []
    for date_str, year, month, day in days:
        report = await analyze_day(date_str, year, month, day)
        if report:
            reports.append(report)
    
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in reports:
        print(f"{r['date']}: {r['total_errors']:>8,} errors, {r['patterns_found']:>4} patterns ({r['coverage_percent']:>5.1f}% coverage)")
    
    print(f"\nReports saved to: {REPORT_DIR}")

if __name__ == "__main__":
    asyncio.run(main())
