#!/usr/bin/env python3
"""
Recent Incidents Exporter - Extract TOP incidents from daily report
====================================================================

Vezme nejnovější incident_analysis_daily report a extrahuje:
- TOP operational incidents (ordered by severity + raw incident count)
- Struktura: aplikace, severity, root cause, affected apps, actions

Exportuje jako CSV vhodný pro Confluence.

Použití:
    python recent_incidents_exporter.py --output ./exports/latest
"""

import os
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

@dataclass
class IncidentRow:
    severity: str
    application: str
    root_cause: str
    affected_apps_count: int
    affected_apps: str
    raw_incidents: int
    action: str
    notes: str = ""

def parse_daily_report(report_file: str) -> Dict[str, any]:
    """Parsuje incident_analysis_daily.txt report."""
    
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    result = {
        'date': None,
        'raw_incidents': 0,
        'operational_incidents': 0,
        'severity_breakdown': {},
        'top_incidents': []
    }
    
    # Extrahuj datum
    date_match = re.search(r'Date:\s*(\d{4}-\d{2}-\d{2})', content)
    if date_match:
        result['date'] = date_match.group(1)
    
    # Extrahuj raw incidents
    raw_match = re.search(r'Raw incidents processed:\s*(\d+)', content)
    if raw_match:
        result['raw_incidents'] = int(raw_match.group(1))
    
    # Extrahuj operational incidents
    op_match = re.search(r'Operational incidents identified:\s*(\d+)', content)
    if op_match:
        result['operational_incidents'] = int(op_match.group(1))
    
    # Extrahuj severity breakdown
    severity_section = re.search(r'OPERATIONAL SEVERITY:(.*?)TOP OPERATIONAL', content, re.DOTALL)
    if severity_section:
        lines = severity_section.group(1).strip().split('\n')
        for line in lines:
            match = re.search(r'([🔴🟠🟡🟢])\s*(\w+):\s*(\d+)', line)
            if match:
                emoji, severity, count = match.groups()
                result['severity_breakdown'][severity] = int(count)
    
    # Extrahuj top operational incidents
    incidents_section = re.search(r'TOP OPERATIONAL INCIDENTS:(.*?)(?:AFFECTED APPLICATIONS:|$)', content, re.DOTALL)
    if incidents_section:
        # Rozděl na jednotlivé incidenty (oddělené prázdným řádkem)
        incident_texts = re.split(r'\n\n+', incidents_section.group(1).strip())
        
        for idx, inc_text in enumerate(incident_texts):
            if not inc_text.strip() or inc_text.startswith('---'):
                continue
            
            incident = parse_incident_block(inc_text)
            if incident:
                result['top_incidents'].append(incident)
            
            # Limit: top 30 incidentů
            if idx >= 30:
                break
    
    return result

def parse_incident_block(block: str) -> Optional[Dict]:
    """Parsuje jeden incident blok."""
    
    lines = block.strip().split('\n')
    if not lines:
        return None
    
    # První řádek: severity + aplikace
    first_line = lines[0]
    severity_match = re.search(r'([🔴🟠🟡🟢])\s*(\w+)\s+issue in\s+(.+?)$', first_line)
    if not severity_match:
        return None
    
    emoji, sev_text, app = severity_match.groups()
    
    severity_map = {'🔴': 'Critical', '🟠': 'High', '🟡': 'Medium', '🟢': 'Low'}
    severity = severity_map.get(emoji, sev_text)
    
    incident = {
        'severity': severity,
        'application': app.strip(),
        'root_cause': '',
        'affected_apps': [],
        'raw_incidents': 0,
        'action': ''
    }
    
    # Parsuj zbytek řádků
    for line in lines[1:]:
        if line.startswith('   Root cause:'):
            incident['root_cause'] = line.replace('   Root cause:', '').strip()
        elif line.startswith('   Affected:'):
            apps_str = line.replace('   Affected:', '').strip()
            incident['affected_apps'] = [a.strip() for a in apps_str.split(',')]
        elif line.startswith('   Raw incidents:'):
            match = re.search(r'(\d+)', line)
            if match:
                incident['raw_incidents'] = int(match.group(1))
        elif line.startswith('   → '):
            incident['action'] = line.replace('   → ', '').strip()
    
    return incident if incident['application'] else None

def export_recent_incidents_csv(report_file: str, output_dir: str = None) -> str:
    """Exportuje recent incidents jako CSV."""
    
    if output_dir is None:
        output_dir = SCRIPT_DIR / 'exports' / 'latest'
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Parsuj report
    report_data = parse_daily_report(report_file)
    
    # Seřaď incidenty: critical > high > medium > low, pak by raw_incidents DESC
    severity_order = {'Critical': 0, 'High': 1, 'Medium': 2, 'Low': 3}
    sorted_incidents = sorted(
        report_data['top_incidents'],
        key=lambda x: (
            severity_order.get(x['severity'], 4),
            -x['raw_incidents']
        )
    )
    
    # Vytvoř řádky
    rows = []
    for inc in sorted_incidents:
        row = IncidentRow(
            severity=inc['severity'],
            application=inc['application'],
            root_cause=inc['root_cause'],
            affected_apps_count=len(inc['affected_apps']),
            affected_apps=', '.join(inc['affected_apps'][:5]),  # Top 5
            raw_incidents=inc['raw_incidents'],
            action=inc['action'],
        )
        rows.append(row)
    
    # Exportuj CSV
    csv_path = output_dir / 'recent_incidents.csv'
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'severity', 'application', 'root_cause', 'affected_apps_count',
            'affected_apps', 'raw_incidents', 'action'
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                'severity': row.severity,
                'application': row.application,
                'root_cause': row.root_cause,
                'affected_apps_count': row.affected_apps_count,
                'affected_apps': row.affected_apps,
                'raw_incidents': row.raw_incidents,
                'action': row.action,
            })
    
    print(f"✅ Exported {len(rows)} incidents to {csv_path}")
    return str(csv_path)

def main():
    # Najdi nejnovější daily report
    reports_dir = SCRIPT_DIR / 'reports'
    daily_reports = list(reports_dir.glob('incident_analysis_daily_*.txt'))
    
    if not daily_reports:
        print("❌ No daily reports found")
        return 1
    
    latest_report = sorted(daily_reports)[-1]
    print(f"📋 Using report: {latest_report.name}")
    
    # Exportuj
    csv_path = export_recent_incidents_csv(str(latest_report))
    print(f"📊 CSV file: {csv_path}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
