#!/usr/bin/env python3
"""
Fetch today's logs in 30-minute batches starting from 8:00
Each batch represents a separate analysis run (production simulation)
"""
import sys
import os
import asyncio
from datetime import datetime, timedelta
import json

sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
from fetch_errors_smart import fetch_with_target_coverage

async def fetch_today_batches():
    """Fetch today's logs in 30-minute increments from 8:00"""
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Start at 8:00 today
    start_time = today.replace(hour=8, minute=0)
    
    # End at current time (or 23:30 if testing for full day)
    current_time = datetime.now()
    
    # Create output directory
    output_dir = f"data/batches/{today.strftime('%Y-%m-%d')}"
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"📅 Fetching logs for {today.strftime('%Y-%m-%d')}")
    print(f"⏰ Starting from 08:00, 30-minute batches")
    print(f"📁 Output directory: {output_dir}")
    print("=" * 80)
    print()
    
    batch_num = 1
    batch_time = start_time
    
    results_summary = []
    
    while batch_time < current_time:
        batch_end = batch_time + timedelta(minutes=30)
        
        # Don't fetch future data
        if batch_end > current_time:
            batch_end = current_time
        
        print(f"🔄 Batch #{batch_num}: {batch_time.strftime('%H:%M')} - {batch_end.strftime('%H:%M')}")
        
        output_file = f"{output_dir}/batch_{batch_num:02d}_{batch_time.strftime('%H%M')}-{batch_end.strftime('%H%M')}.json"
        
        try:
            result = await fetch_with_target_coverage(
                date_from=batch_time.isoformat(),
                date_to=batch_end.isoformat(),
                target_coverage=75,
                max_sample=50000  # Max 50k per batch
            )
            
            # Save batch result
            with open(output_file, 'w') as f:
                json.dump(result, f, default=str, indent=2)
            
            # Summary
            summary = {
                'batch': batch_num,
                'time_range': f"{batch_time.strftime('%H:%M')}-{batch_end.strftime('%H:%M')}",
                'total_errors': result['total_errors'],
                'sample_size': result['sample_size'],
                'coverage': result['coverage_percent'],
                'file': output_file
            }
            results_summary.append(summary)
            
            print(f"   ✅ Total: {result['total_errors']:,} | Sample: {result['sample_size']:,} | Coverage: {result['coverage_percent']:.1f}%")
            print(f"   💾 Saved: {output_file}")
            print()
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            print()
        
        # Next batch
        batch_time = batch_end
        batch_num += 1
        
        # Safety break - max 32 batches (16 hours)
        if batch_num > 32:
            print("⚠️  Reached maximum batch limit (32)")
            break
    
    # Save summary
    summary_file = f"{output_dir}/batches_summary.json"
    with open(summary_file, 'w') as f:
        json.dump({
            'date': today.strftime('%Y-%m-%d'),
            'batches_count': len(results_summary),
            'batches': results_summary,
            'total_errors_all_batches': sum(b['total_errors'] for b in results_summary),
            'total_samples_all_batches': sum(b['sample_size'] for b in results_summary)
        }, f, indent=2)
    
    print("=" * 80)
    print(f"✅ Completed {len(results_summary)} batches")
    print(f"📊 Total errors across all batches: {sum(b['total_errors'] for b in results_summary):,}")
    print(f"📊 Total samples collected: {sum(b['sample_size'] for b in results_summary):,}")
    print(f"💾 Summary saved: {summary_file}")
    print()
    
    # Print summary table
    print("📋 Batch Summary:")
    print(f"{'Batch':<8} {'Time Range':<15} {'Errors':<10} {'Sample':<10} {'Coverage':<10}")
    print("-" * 80)
    for b in results_summary:
        print(f"{b['batch']:<8} {b['time_range']:<15} {b['total_errors']:<10,} {b['sample_size']:<10,} {b['coverage']:<10.1f}%")

if __name__ == "__main__":
    asyncio.run(fetch_today_batches())
