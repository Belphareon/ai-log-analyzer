#!/usr/bin/env python3
"""
Daily Report Generator - Generates daily summary from backfill logs
===================================================================

Generuje daily report ze včerejší backfill analýzy.
Obsah: Top 5-10 problémů z "Top issues (actionable)" sekce

Použití:
    python daily_report_generator.py                    # Automatické parsování
    python daily_report_generator.py --log-file /path/to/log.txt  # Manuální log
    python daily_report_generator.py --output ./reports  # Specifikuj výstupní dir
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

# Teams
try:
    from core.teams_notifier import TeamsNotifier
    HAS_TEAMS = True
except ImportError:
    HAS_TEAMS = False


@dataclass
class ProblemSummary:
    """Problem z daily reportu"""
    rank: int
    icon: str
    category: str
    error_type: str
    occurrence_count: int
    severity: str  # low, medium, high, critical
    scope: str  # LOCAL, CROSS_NS, SYSTEMIC
    trend: Optional[str] = None  # "🔴 UP", "🟢 DOWN", "🟡 STABLE"


def parse_problem_analysis_report(log_content: str) -> List[ProblemSummary]:
    """
    Parsuje PROBLEM ANALYSIS REPORT a extrahuje top problémy.
    
    Hledá vzor:
    Top issues (actionable):
      1. 🟡 [category] error_type (count occ) [severity]
      2. 🟡 [category] error_type (count occ) [severity]
    """
    problems = []
    
    # Patterns
    issue_pattern = r'^\s*(\d+)\.\s+(\S+)\s+\[(\w+)\]\s+(\w+)\s+\((\d+(?:,\d+)*)\s+occ\)\s+\[(\w+)\]'
    
    lines = log_content.split('\n')
    in_top_issues = False
    
    for i, line in enumerate(lines):
        if 'Top issues (actionable):' in line:
            in_top_issues = True
            continue
        
        if in_top_issues:
            # Konec sekce když narazíme na nový nadpis
            if line.strip().startswith('---') or line.strip().startswith('=='):
                break
            
            match = re.match(issue_pattern, line)
            if match:
                rank, icon, category, error_type, occ, severity = match.groups()
                # Odstraň čárky z occurencí
                occurrence_count = int(occ.replace(',', ''))
                
                problem = ProblemSummary(
                    rank=int(rank),
                    icon=icon,
                    category=category,
                    error_type=error_type,
                    occurrence_count=occurrence_count,
                    severity=severity.lower(),
                )
                problems.append(problem)
    
    return problems


def get_yesterday_backfill_date() -> datetime:
    """Vrátí včerejší datum pro backfill (včera byla den kdy se spustil backfill)"""
    return (datetime.now(timezone.utc) - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def format_for_teams(problems: List[ProblemSummary], confluence_link: Optional[str] = None) -> Dict[str, Any]:
    """Formatuje problémy pro Teams MessageCard"""
    
    if not problems:
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": "✅ Daily Report - No critical issues",
            "themeColor": "28a745",
            "sections": [
                {
                    "activityTitle": "✅ Daily Report",
                    "activitySubtitle": f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    "text": "No critical issues detected in the last 24 hours."
                }
            ]
        }
    
    # Determine color based on severity
    max_severity = max((p.severity for p in problems), default='info')
    color_map = {
        'critical': 'ff3333',
        'high': 'ff9933',
        'medium': 'ffcc00',
        'low': '3399ff',
        'info': '999999',
    }
    color = color_map.get(max_severity, '999999')
    
    # Format problems
    facts = []
    for p in problems[:5]:  # Top 5
        facts.append({
            "name": f"{p.rank}. {p.category.upper()} - {p.error_type}",
            "value": f"{p.occurrence_count:,} occurrences [{p.severity.upper()}]"
        })
    
    message = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"📊 Daily Report - {len(problems)} issues detected",
        "themeColor": color,
        "sections": [
            {
                "activityTitle": "📊 Daily Report",
                "activitySubtitle": f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "facts": facts
            }
        ]
    }
    
    if confluence_link:
        message["sections"][0]["markdown"] = True
        message["sections"][0]["text"] = f"\n**[View detailed report in Confluence]({confluence_link})**"
    
    return message


def save_daily_report(
    problems: List[ProblemSummary],
    output_dir: str,
    date: datetime
) -> Dict[str, str]:
    """Uloží daily report do JSON"""
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    date_str = date.strftime('%Y-%m-%d')
    
    # JSON format
    json_file = output_path / f"daily_report_{date_str}.json"
    
    data = {
        'report_date': date_str,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'total_problems': len(problems),
        'problems': [
            {
                'rank': p.rank,
                'category': p.category,
                'error_type': p.error_type,
                'occurrences': p.occurrence_count,
                'severity': p.severity,
                'scope': p.scope,
            }
            for p in problems
        ]
    }
    
    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    return {
        'json': str(json_file)
    }


def main():
    parser = argparse.ArgumentParser(description='Daily Report Generator')
    parser.add_argument('--log-file', type=str, help='Path to backfill log file')
    parser.add_argument('--output', type=str, default='./reports', help='Output directory')
    parser.add_argument('--confluence-link', type=str, help='Link to Confluence daily report page')
    parser.add_argument('--send-teams', action='store_true', help='Send to Teams (requires TEAMS_WEBHOOK_URL)')
    
    args = parser.parse_args()
    
    # Pokud neni log-file, podíváme se na nejnovější backfill log
    log_file = args.log_file
    
    if not log_file:
        # Najdi nejnovější backfill report
        reports_dir = SCRIPT_DIR / 'reports'
        if reports_dir.exists():
            # Hledej JSON reports
            json_files = sorted(reports_dir.glob('problem_report_*.json'), reverse=True)
            if json_files:
                # Pokud máme JSON report, parsuj ho
                # TODO: Implement JSON report parsing
                print("⚠️ JSON report parsing not yet implemented")
                return 1
        
        print("⚠️ No log file found. Specify with --log-file or ensure backfill generated reports.")
        return 1
    
    # Přečti log
    try:
        with open(log_file, 'r') as f:
            log_content = f.read()
    except Exception as e:
        print(f"❌ Failed to read log file: {e}")
        return 1
    
    # Parsuj problémy
    problems = parse_problem_analysis_report(log_content)
    
    if not problems:
        print("⚠️ No problems found in log")
        return 1
    
    print(f"📊 Found {len(problems)} problems from report")
    for p in problems[:5]:
        print(f"  {p.rank}. [{p.category}] {p.error_type} - {p.occurrence_count:,} occ")
    
    # Save report
    yesterday = get_yesterday_backfill_date()
    report_files = save_daily_report(problems, args.output, yesterday)
    print(f"\n✅ Daily report saved: {report_files['json']}")
    
    # Send to Teams
    if args.send_teams and HAS_TEAMS:
        try:
            notifier = TeamsNotifier()
            if notifier.is_enabled():
                message = format_for_teams(problems, args.confluence_link)
                notifier._send_message(message)
                print("✅ Daily report sent to Teams")
        except Exception as e:
            print(f"⚠️ Failed to send to Teams: {e}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
