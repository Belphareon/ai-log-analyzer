#!/usr/bin/env python3
"""
AI Log Analyzer - Complete Pipeline Orchestrator
Runs: Fetch → Extract → Report → Single Output File
"""
import os, sys, json, argparse, subprocess, time, threading
from datetime import datetime
from collections import Counter

class Color:
    OK = '\033[92m'
    FAIL = '\033[91m'
    BOLD = '\033[1m'
    CYAN = '\033[96m'
    END = '\033[0m'

def log_step(msg): 
    print(f"\n{Color.CYAN}{'='*70}{Color.END}")
    print(f"{Color.BOLD}{msg}{Color.END}")
    print(f"{Color.CYAN}{'='*70}{Color.END}")

def log_ok(msg): 
    print(f"{Color.OK}✅ {msg}{Color.END}")

def log_err(msg): 
    print(f"{Color.FAIL}❌ {msg}{Color.END}")

def progress_bar(current, total, label=""):
    """Draw progress bar"""
    pct = current / total if total > 0 else 0
    bar_len = 40
    filled = int(bar_len * pct)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r{label:30s} [{bar}] {pct*100:5.1f}%", end="", flush=True)

def run_cmd(cmd, desc, show_progress=True):
    """Run command with optional progress tracking"""
    try:
        if show_progress:
            # Simulate progress during execution
            process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            start = time.time()
            timeout = 600
            
            while process.poll() is None:
                elapsed = time.time() - start
                pct = min(elapsed / timeout, 0.95)  # Show up to 95% while running
                progress_bar(pct, 1.0, desc)
                time.sleep(0.5)
            
            elapsed = time.time() - start
            progress_bar(1.0, 1.0, desc)
            print()  # New line after progress bar
            
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else ""
                log_err(f"{desc} failed: {stderr[:200]}")
                return None
            return process.stdout.read() if process.stdout else ""
        else:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                log_err(f"{desc} failed: {result.stderr[:200]}")
                return None
            return result.stdout
    except Exception as e:
        log_err(f"{desc} error: {e}")
        return None

def analyze_period(date_from, date_to, output_file, batch_size=5000):
    start_time = time.time()
    
    print(f"\n{Color.BOLD}🎯 AI Log Analyzer - Complete Pipeline{Color.END}")
    print(f"Period: {date_from} → {date_to}")
    print(f"Output: {output_file}\n")
    
    # STEP 1: Fetch
    log_step("STEP 1/4: Fetching errors from Elasticsearch")
    batch_file = "/tmp/fetch_batch.json"
    if not run_cmd(f"python3 fetch_unlimited.py --from '{date_from}' --to '{date_to}' --batch-size {batch_size} --output {batch_file}", "Fetching"):
        return False
    
    with open(batch_file) as f:
        batch_data = json.load(f)
        error_count = batch_data.get('fetched_errors', 0)
    log_ok(f"Fetched {error_count:,} ERROR logs")
    
    # STEP 2: Extract
    log_step("STEP 2/4: Extracting root causes from traces")
    causes_file = "/tmp/root_causes.json"
    if not run_cmd(f"python3 trace_extractor.py --input {batch_file} --output {causes_file}", "Extracting"):
        return False
    
    with open(causes_file) as f:
        causes_data = json.load(f)
        cause_count = len(causes_data.get('root_causes', []))
        unique_traces = causes_data.get('stats', {}).get('unique_traces', 0)
    log_ok(f"Extracted {cause_count} root causes from {unique_traces:,} unique traces")
    
    # STEP 3: Report
    log_step("STEP 3/4: Generating detailed analysis report")
    report_file = "/tmp/analysis_report.md"
    if not run_cmd(f"python3 trace_report_detailed.py --input {causes_file} --output {report_file}", "Generating"):
        return False
    
    with open(report_file) as f:
        report_content = f.read()
    log_ok("Detailed report generated")
    
    # STEP 4: Consolidate & Analyze
    log_step("STEP 4/4: Creating comprehensive analysis file")
    
    # Calculate statistics from batch data
    errors = batch_data.get('errors', [])
    
    # App distribution
    app_counts = Counter()
    cluster_counts = Counter()
    trace_id_count = 0
    
    for error in errors:
        app = error.get('application', 'unknown')
        cluster = error.get('cluster', 'unknown')
        trace_id = error.get('trace_id', '')
        
        app_counts[app] += 1
        cluster_counts[cluster] += 1
        if trace_id and trace_id.strip():
            trace_id_count += 1
    
    # Top causes stats
    top_causes = causes_data.get('root_causes', [])[:10]
    new_patterns = sum(1 for cause in causes_data.get('root_causes', []) if cause.get('errors_count', 0) < 5)
    
    analysis_output = {
        "metadata": {
            "analysis_type": "Complete Trace-Based Root Cause Analysis",
            "period_start": date_from,
            "period_end": date_to,
            "generated_at": datetime.utcnow().isoformat(),
            "version": "1.0"
        },
        "statistics": {
            "total_errors_fetched": error_count,
            "errors_with_trace_id": trace_id_count,
            "trace_id_coverage_percent": round(100 * trace_id_count / error_count, 1) if error_count > 0 else 0,
            "unique_traces": unique_traces,
            "root_causes_identified": cause_count,
            "new_unique_patterns": new_patterns,
            "avg_errors_per_trace": round(error_count / unique_traces, 1) if unique_traces > 0 else 0,
            "execution_time_seconds": int(time.time() - start_time),
            "app_distribution": dict(app_counts.most_common(10)),
            "cluster_distribution": dict(cluster_counts.most_common()),
        },
        "batch_data": batch_data,
        "root_causes_analysis": causes_data,
        "markdown_report": report_content
    }
    
    with open(output_file, 'w') as f:
        json.dump(analysis_output, f, indent=2, default=str)
    
    file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
    log_ok(f"Comprehensive analysis saved: {output_file} ({file_size_mb:.1f}MB)")
    
    # Print detailed summary
    stats = analysis_output['statistics']
    print(f"\n{Color.BOLD}{'='*70}")
    print(f"📊 DETAILED ANALYSIS SUMMARY")
    print(f"{'='*70}{Color.END}")
    
    print(f"\n{Color.BOLD}📥 Data Collection:{Color.END}")
    print(f"  Total errors fetched:        {stats['total_errors_fetched']:>10,d}")
    print(f"  Errors with trace ID:        {stats['errors_with_trace_id']:>10,d} ({stats['trace_id_coverage_percent']}%)")
    print(f"  Unique traces identified:    {stats['unique_traces']:>10,d}")
    print(f"  Avg errors per trace:        {stats['avg_errors_per_trace']:>10.1f}")
    
    print(f"\n{Color.BOLD}🔍 Root Cause Analysis:{Color.END}")
    print(f"  Root causes extracted:       {stats['root_causes_identified']:>10,d}")
    print(f"  New unique patterns found:   {stats['new_unique_patterns']:>10,d}")
    
    print(f"\n{Color.BOLD}📱 App Distribution (Top 5):{Color.END}")
    app_dist = stats['app_distribution']
    for i, (app, count) in enumerate(list(app_dist.items())[:5], 1):
        pct = 100 * count / stats['total_errors_fetched']
        bar = "█" * int(pct / 2)
        print(f"  {i}. {app:30s} {count:>7,d} ({pct:5.1f}%) {bar}")
    
    print(f"\n{Color.BOLD}🏢 Cluster Distribution:{Color.END}")
    cluster_dist = stats['cluster_distribution']
    for cluster, count in list(cluster_dist.items())[:5]:
        pct = 100 * count / stats['total_errors_fetched']
        bar = "█" * int(pct / 2)
        print(f"  {cluster:40s} {count:>7,d} ({pct:5.1f}%) {bar}")
    
    print(f"\n{Color.BOLD}⏱️  Performance:{Color.END}")
    print(f"  Execution time:              {stats['execution_time_seconds']:>10,d}s")
    print(f"  Output file:                 {output_file}")
    print(f"  File size:                   {file_size_mb:>10.1f}MB")
    
    print(f"\n{Color.BOLD}{'='*70}")
    print(f"✅ Pipeline completed successfully!{Color.END}")
    print(f"{'='*70}\n")
    
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Complete AI Log Analysis Pipeline')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format)')
    parser.add_argument('--output', required=True, help='Output JSON file')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size (default: 5000)')
    
    args = parser.parse_args()
    success = analyze_period(args.date_from, args.date_to, args.output, args.batch_size)
    sys.exit(0 if success else 1)
