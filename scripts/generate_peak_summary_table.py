#!/usr/bin/env python3
"""
Peak Summary Table Generator - Přehledná tabulka peaků za posledních 24h

Tento skript generuje přehlednou tabulku všech detekovaných peaků s důležitými informacemi:
1. Časové ohraničení peaku (od-do, trvání)
2. Počet výskytů během peaku  
3. Namespace a aplikace/komponenta
4. Status (známý/nový peak)
5. Root cause a detaily

Použití:
    python generate_peak_summary_table.py                    # Poslední 24h
    python generate_peak_summary_table.py --hours 48         # Poslední 48h
    python generate_peak_summary_table.py --output table.md  # Vlastní výstup
"""

import os
import sys
import argparse
import psycopg2
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import yaml

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')


@dataclass
class PeakSummary:
    """Sumarizace peaku pro tabulku"""
    # Časové ohraničení
    first_seen: datetime
    last_seen: datetime
    duration_minutes: int
    
    # Lokace
    namespace: str
    app_name: str
    error_type: str
    
    # Velikost peaku
    total_events: int  # Součet všech original_value
    peak_value: int    # Max original_value
    baseline_value: float  # Průměr reference_value
    max_ratio: float   # Max poměr original/reference
    
    # Detekce
    spike_count: int   # Kolik záznamů je_spike
    burst_count: int   # Kolik záznamů je_burst
    max_score: float
    severity: str
    detection_method: str
    
    # Known status
    is_known: bool
    known_peak_ids: List[int]
    
    # Root cause
    root_causes: List[str]
    sample_messages: List[str]
    
    def format_duration(self) -> str:
        """Formátuje trvání peaku"""
        if self.duration_minutes < 60:
            return f"{self.duration_minutes}m"
        elif self.duration_minutes < 24 * 60:
            hours = self.duration_minutes // 60
            mins = self.duration_minutes % 60
            return f"{hours}h {mins}m" if mins else f"{hours}h"
        else:
            days = self.duration_minutes // (24 * 60)
            hours = (self.duration_minutes % (24 * 60)) // 60
            return f"{days}d {hours}h"
    
    def format_time_range(self) -> str:
        """Formátuje časový rozsah peaku"""
        fmt = "%m-%d %H:%M"
        return f"{self.first_seen.strftime(fmt)} → {self.last_seen.strftime(fmt)}"
    
    def get_detection_type(self) -> str:
        """Určí typ detekce"""
        if self.spike_count > 0 and self.burst_count > 0:
            return "spike+burst"
        elif self.spike_count > 0:
            return "spike"
        elif self.burst_count > 0:
            return "burst"
        else:
            return "score-based"
    
    def get_known_status(self) -> str:
        """Vrátí status známosti"""
        if self.is_known:
            return f"KNOWN ({len(self.known_peak_ids)})"
        return "NEW"


def get_db_connection():
    """Vytvoří DB připojení"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME', 'postgres'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
    )


def load_known_peaks_registry(registry_path: Path = None) -> List[Dict]:
    """Načte známé peaky z known_peaks.yaml (formát: seznam PeakEntry dict)."""
    if registry_path is None:
        registry_path = SCRIPT_DIR.parent / 'registry' / 'known_peaks.yaml'

    if not registry_path.exists():
        return []

    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        entries = []
        if data and isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                entries.append({
                    'id': item.get('id', ''),
                    'problem_key': item.get('problem_key', ''),
                    'peak_type': (item.get('peak_type') or '').upper(),
                    'affected_namespaces': set(item.get('affected_namespaces') or []),
                    'affected_apps': set(item.get('affected_apps') or []),
                })
        return entries
    except Exception as e:
        print(f"⚠️ Failed to load known peaks registry: {e}")
        return []


def match_known_peak(namespace: str, peak_type: str, app_name: str,
                     registry_entries: List[Dict]) -> Optional[str]:
    """Vrátí ID záznamu z known_peaks.yaml pokud namespace+peak_type matchuje."""
    pt = peak_type.upper()
    candidates = []
    for entry in registry_entries:
        if entry['peak_type'] != pt:
            continue
        if namespace not in entry['affected_namespaces']:
            continue
        score = 1
        if app_name and app_name != 'unknown' and app_name in entry['affected_apps']:
            score += 2
        candidates.append((score, entry))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]['id']


def fetch_peak_data(conn, since: datetime) -> List[Dict[str, Any]]:
    """Načte peak data z DB"""
    cursor = conn.cursor()
    
    query = """
    SELECT
        timestamp,
        namespace,
        app_name,
        error_type,
        original_value,
        reference_value,
        ratio,
        score,
        severity,
        is_spike,
        is_burst,
        detection_method,
        error_message,
        suspected_root_cause,
        known_peak_id
    FROM ailog_peak.peak_investigation
    WHERE timestamp >= %s
      AND (is_spike = TRUE OR is_burst = TRUE OR score >= 30)
      AND original_value > 0
    ORDER BY timestamp ASC
    """
    
    cursor.execute(query, (since,))
    rows = cursor.fetchall()
    cursor.close()
    
    # Convert to dict
    results = []
    for row in rows:
        results.append({
            'timestamp': row[0],
            'namespace': row[1] or 'unknown',
            'app_name': row[2] or 'unknown',
            'error_type': row[3] or 'UnknownError',
            'original_value': row[4] or 0,
            'reference_value': row[5] or 0,
            'ratio': row[6],
            'score': row[7] or 0,
            'severity': row[8] or 'low',
            'is_spike': row[9] or False,
            'is_burst': row[10] or False,
            'detection_method': row[11] or 'unknown',
            'error_message': row[12] or '',
            'root_cause': row[13] or '',
            'known_peak_id': row[14],
        })
    
    return results


def group_peaks(rows: List[Dict[str, Any]], registry_entries: List[Dict] = None) -> List[PeakSummary]:
    """Seskupí záznamy do peaků podle (namespace, error_type)"""
    
    # Group by (namespace, error_type)
    groups = defaultdict(list)
    for row in rows:
        key = (row['namespace'], row['error_type'])
        groups[key].append(row)
    
    # Create summaries
    summaries = []
    for (namespace, error_type), group_rows in groups.items():
        # Sort by timestamp
        group_rows.sort(key=lambda x: x['timestamp'])
        
        # Extract info
        first_seen = group_rows[0]['timestamp']
        last_seen = group_rows[-1]['timestamp']
        duration_minutes = int((last_seen - first_seen).total_seconds() / 60)
        
        # App name (vezmi nejčastější)
        app_names = [r['app_name'] for r in group_rows if r['app_name'] != 'unknown']
        app_name = max(set(app_names), key=app_names.count) if app_names else 'unknown'
        
        # Metrics
        total_events = sum(r['original_value'] for r in group_rows)
        peak_value = max(r['original_value'] for r in group_rows)
        # Baseline: average of non-zero reference values only
        non_zero_refs = [r['reference_value'] for r in group_rows
                         if r['reference_value'] and r['reference_value'] > 0]
        baseline_value = sum(non_zero_refs) / len(non_zero_refs) if non_zero_refs else 0

        # Ratio: prefer calculated from peak/baseline, fall back to DB ratio column
        if baseline_value > 0 and peak_value > baseline_value:
            max_ratio = peak_value / baseline_value
        else:
            db_ratios = [r['ratio'] for r in group_rows if r['ratio'] and r['ratio'] > 1.0]
            max_ratio = max(db_ratios) if db_ratios else 0
        
        # Detection
        spike_count = sum(1 for r in group_rows if r['is_spike'])
        burst_count = sum(1 for r in group_rows if r['is_burst'])
        max_score = max(r['score'] for r in group_rows)
        
        # Severity (vezmi nejvyšší)
        severity_order = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
        severities = [r['severity'] for r in group_rows]
        severity = max(severities, key=lambda s: severity_order.get(s, 0))
        
        # Detection method (vezmi poslední)
        detection_method = group_rows[-1]['detection_method']
        
        # Known status - primárně z DB, fallback z YAML registry
        known_peak_ids = [r['known_peak_id'] for r in group_rows if r['known_peak_id']]
        if not known_peak_ids and registry_entries:
            peak_type_str = 'SPIKE' if spike_count > 0 else ('BURST' if burst_count > 0 else '')
            if peak_type_str:
                reg_id = match_known_peak(namespace, peak_type_str, app_name, registry_entries)
                if reg_id:
                    known_peak_ids = [reg_id]
        is_known = len(known_peak_ids) > 0
        
        # Root causes
        root_causes = [r['root_cause'] for r in group_rows if r['root_cause']]
        root_causes = list(set(root_causes))  # Deduplicate
        
        # Sample messages (vezmi až 3 různé)
        messages = []
        seen_msgs = set()
        for r in group_rows:
            msg = r['error_message']
            if msg and msg not in seen_msgs:
                messages.append(msg)
                seen_msgs.add(msg)
            if len(messages) >= 3:
                break
        
        summary = PeakSummary(
            first_seen=first_seen,
            last_seen=last_seen,
            duration_minutes=duration_minutes,
            namespace=namespace,
            app_name=app_name,
            error_type=error_type,
            total_events=total_events,
            peak_value=peak_value,
            baseline_value=baseline_value,
            max_ratio=max_ratio,
            spike_count=spike_count,
            burst_count=burst_count,
            max_score=max_score,
            severity=severity,
            detection_method=detection_method,
            is_known=is_known,
            known_peak_ids=known_peak_ids,
            root_causes=root_causes,
            sample_messages=messages,
        )
        
        summaries.append(summary)
    
    # Sort by first_seen (chronologically)
    summaries.sort(key=lambda s: s.first_seen)
    
    return summaries


def generate_markdown_table(summaries: List[PeakSummary], hours: int) -> str:
    """Generuje Markdown tabulku"""
    
    lines = []
    lines.append(f"# Peak Detection Summary - Last {hours}h")
    lines.append(f"\n**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"**Total peaks detected:** {len(summaries)}")
    lines.append(f"**Time range:** Last {hours} hours\n")
    
    # Statistics
    total_events = sum(s.total_events for s in summaries)
    known_count = sum(1 for s in summaries if s.is_known)
    new_count = len(summaries) - known_count
    spike_count = sum(1 for s in summaries if s.spike_count > 0)
    burst_count = sum(1 for s in summaries if s.burst_count > 0)
    
    lines.append("## Statistics\n")
    lines.append(f"- **Total events in peaks:** {total_events:,}")
    lines.append(f"- **Known peaks:** {known_count}")
    lines.append(f"- **New peaks:** {new_count}")
    lines.append(f"- **Spikes:** {spike_count}")
    lines.append(f"- **Bursts:** {burst_count}")
    lines.append("")
    
    # Main table
    lines.append("## Peak Details\n")
    lines.append("| # | Time Range | Duration | NS | App/Component | Error Type | Events | Peak/Baseline | Ratio | Type | Known | Severity | Root Cause |")
    lines.append("|---|------------|----------|----|--------------|-----------:|-------:|--------------:|------:|------|------:|----------|------------|")
    
    for idx, peak in enumerate(summaries, 1):
        time_range = peak.format_time_range()
        duration = peak.format_duration()
        ns = peak.namespace[:20]  # Truncate long namespaces
        app = peak.app_name[:25]  # Truncate long app names
        error_type = peak.error_type[:20]
        events = f"{peak.total_events:,}"
        peak_baseline = f"{peak.peak_value} / {peak.baseline_value:.1f}"
        ratio = f"{peak.max_ratio:.1f}x" if peak.max_ratio > 0 else "N/A"
        det_type = peak.get_detection_type()
        known = peak.get_known_status()
        severity = peak.severity
        
        # Root cause (zkrať na 50 znaků)
        root_cause = ", ".join(peak.root_causes) if peak.root_causes else "-"
        if len(root_cause) > 50:
            root_cause = root_cause[:47] + "..."
        
        lines.append(f"| {idx} | {time_range} | {duration} | {ns} | {app} | {error_type} | {events} | {peak_baseline} | {ratio} | {det_type} | {known} | {severity} | {root_cause} |")
    
    # Detailed section
    lines.append("\n## Detailed Information\n")
    for idx, peak in enumerate(summaries, 1):
        lines.append(f"### {idx}. {peak.error_type} @ {peak.namespace}")
        lines.append(f"- **Time:** {peak.first_seen.strftime('%Y-%m-%d %H:%M:%S')} → {peak.last_seen.strftime('%Y-%m-%d %H:%M:%S')} ({peak.format_duration()})")
        lines.append(f"- **Location:** {peak.app_name} @ {peak.namespace}")
        lines.append(f"- **Events:** {peak.total_events:,} total, peak value: {peak.peak_value}, baseline: {peak.baseline_value:.1f}")
        lines.append(f"- **Detection:** {peak.get_detection_type()} (spikes: {peak.spike_count}, bursts: {peak.burst_count})")
        lines.append(f"- **Score:** {peak.max_score:.1f} | **Severity:** {peak.severity} | **Ratio:** {peak.max_ratio:.1f}x")
        lines.append(f"- **Known:** {peak.get_known_status()}")
        lines.append(f"- **Method:** {peak.detection_method}")
        
        if peak.root_causes:
            lines.append(f"- **Root Causes:**")
            for rc in peak.root_causes:
                lines.append(f"  - {rc}")
        else:
            lines.append(f"- **Root Causes:** None identified")
        
        if peak.sample_messages:
            lines.append(f"- **Sample Messages:**")
            for msg in peak.sample_messages[:3]:
                # Truncate long messages
                if len(msg) > 150:
                    msg = msg[:147] + "..."
                lines.append(f"  - `{msg}`")
        
        lines.append("")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate peak summary table")
    parser.add_argument('--hours', type=int, default=24, help='Hours to look back (default: 24)')
    parser.add_argument('--output', type=str, help='Output file path (default: ai-data/peak_summary_<timestamp>.md)')
    parser.add_argument('--format', choices=['markdown', 'json'], default='markdown', help='Output format')
    args = parser.parse_args()
    
    # Calculate time range
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=args.hours)
    
    print(f"📊 Generating peak summary for last {args.hours}h...")
    print(f"   Time range: {since.strftime('%Y-%m-%d %H:%M:%S')} → {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Connect to DB
    try:
        conn = get_db_connection()
        print(f"✅ Connected to database")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return 1
    
    # Fetch data
    print(f"📥 Fetching peak data...")
    rows = fetch_peak_data(conn, since)
    print(f"   Found {len(rows)} peak records")
    
    if not rows:
        print(f"⚠️ No peaks found in the last {args.hours}h")
        conn.close()
        return 0
    
    # Load known peaks registry for fallback matching
    registry_entries = load_known_peaks_registry()
    print(f"   Loaded {len(registry_entries)} known peak entries from registry")

    # Group into peaks
    print(f"🔍 Grouping records into peaks...")
    summaries = group_peaks(rows, registry_entries)
    print(f"   Identified {len(summaries)} distinct peaks")
    
    # Generate output
    if args.format == 'markdown':
        output = generate_markdown_table(summaries, args.hours)
        
        # Determine output path
        if args.output:
            output_path = Path(args.output)
        else:
            output_dir = SCRIPT_DIR.parent / 'ai-data'
            output_dir.mkdir(exist_ok=True)
            timestamp = now.strftime('%Y%m%d_%H%M%S')
            output_path = output_dir / f'peak_summary_{args.hours}h_{timestamp}.md'
        
        # Write file
        output_path.write_text(output, encoding='utf-8')
        print(f"✅ Markdown table saved to: {output_path}")
        
        # Also print to console
        print("\n" + "="*80)
        print(output)
        print("="*80 + "\n")
    
    else:  # JSON
        # TODO: Implement JSON export
        print(f"⚠️ JSON format not yet implemented")
    
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
