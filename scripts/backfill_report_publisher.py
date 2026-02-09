#!/usr/bin/env python3
"""
Backfill Report Publisher - Upload backfill analysis to Confluence
===================================================================

Vezme nejnovější backfill report a uploadne do Confluence jako HTML.
Zahrnuje: EXECUTIVE SUMMARY + TOP PROBLEM DETAILS

Konfigurace (env vars):
    CONFLUENCE_URL          Base URL
    CONFLUENCE_USERNAME     Username
    CONFLUENCE_API_TOKEN    Token/password
    CONFLUENCE_RECENT_INCIDENTS_PAGE_ID

Použití:
    python backfill_report_publisher.py
    python backfill_report_publisher.py --report /path/to/report.txt
"""

import os
import sys
import re
import argparse
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
    script_dir = Path(__file__).parent
    load_dotenv(script_dir.parent / '.env')
    load_dotenv(script_dir.parent / 'config' / '.env')
except ImportError:
    pass


def find_latest_backfill_report() -> Optional[str]:
    """Najdi nejnovější backfill report."""
    script_dir = Path(__file__).parent
    reports_dir = script_dir / 'reports'
    
    daily_reports = list(reports_dir.glob('incident_analysis_daily_*.txt'))
    if daily_reports:
        return str(sorted(daily_reports)[-1])
    
    return None


def extract_report_sections(report_file: str) -> Tuple[str, str]:
    """Extrahuj EXECUTIVE SUMMARY a PROBLEM DETAILS z backfill reportu."""
    
    with open(report_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extrahuj EXECUTIVE SUMMARY
    summary_match = re.search(
        r'------+\nEXECUTIVE SUMMARY\n------+(.*?)(?:------+\nPROBLEM DETAILS|-{20,}|$)',
        content,
        re.DOTALL
    )
    summary = summary_match.group(1).strip() if summary_match else ""
    
    # Extrahuj PROBLEM DETAILS (limit na top 15 problémů)
    details_match = re.search(
        r'------+\nPROBLEM DETAILS\n------+(.*?)(?:STATISTICS|$)',
        content,
        re.DOTALL
    )
    
    if details_match:
        details = details_match.group(1).strip()
        # Limit: vezmi jen prvních ~15 problémů (oddělené řádky "──")
        problem_blocks = details.split('\n──')
        details = '\n──'.join(problem_blocks[:16])  # 0 + prvních 15
    else:
        details = ""
    
    return summary, details


def escape_html(text: str) -> str:
    """Escapuj HTML znaky."""
    replacements = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }
    for char, escaped in replacements.items():
        text = text.replace(char, escaped)
    return text


def convert_report_to_html(summary: str, details: str) -> str:
    """Konvertuj report text na HTML."""
    
    html_parts = []
    
    # Header
    html_parts.append('<h2>Recent Incidents - Backfill Analysis</h2>')
    html_parts.append(f'<p><em>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</em></p>')
    
    # EXECUTIVE SUMMARY
    html_parts.append('<h3>Executive Summary</h3>')
    html_parts.append('<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow: auto;">')
    html_parts.append(escape_html(summary))
    html_parts.append('</pre>')
    
    # PROBLEM DETAILS
    html_parts.append('<h3>Problem Details (Top 15)</h3>')
    html_parts.append('<pre style="background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow: auto;">')
    html_parts.append(escape_html(details))
    html_parts.append('</pre>')
    
    return '\n'.join(html_parts)


def get_confluence_page(base_url: str, page_id: str, username: str, api_token: str) -> dict:
    """Načti metadata stránky z Confluence."""
    print(f"   🔍 Fetching page metadata...")
    
    url = f"{base_url}/rest/api/content/{page_id}?expand=body.storage,version"
    
    try:
        resp = requests.get(
            url,
            auth=(username, api_token),
            timeout=10,
            verify=False
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"   ✓ Page found, current version: {data['version']['number']}")
        return data
    except Exception as e:
        raise RuntimeError(f"Failed to fetch page {page_id}: {e}")


def update_confluence_page(
    base_url: str,
    page_id: str,
    title: str,
    html_content: str,
    username: str,
    api_token: str
) -> bool:
    """Update Confluence page s novým HTML contentem."""
    
    print(f"   📝 Fetching current page version...")
    
    try:
        page = get_confluence_page(base_url, page_id, username, api_token)
    except Exception as e:
        print(f"   ❌ Failed to fetch page: {e}")
        return False
    
    url = f"{base_url}/rest/api/content/{page_id}"
    print(f"   🔗 API URL: {url}")
    
    payload = {
        "type": "page",
        "id": page_id,
        "title": title,
        "body": {
            "storage": {
                "value": html_content,
                "representation": "storage"
            }
        },
        "version": {
            "number": page['version']['number'] + 1
        }
    }
    
    print(f"   📤 Uploading new version ({page['version']['number'] + 1})...")
    
    resp = None
    try:
        resp = requests.put(
            url,
            json=payload,
            auth=(username, api_token),
            headers={"Content-Type": "application/json"},
            timeout=10,
            verify=False
        )
        resp.raise_for_status()
        print(f"   ✅ Successfully updated page")
        return True
    except Exception as e:
        print(f"   ❌ Failed to update page: {e}")
        if resp:
            print(f"   📋 HTTP Status: {resp.status_code}")
            print(f"   📋 Response: {resp.text[:500]}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Publish backfill analysis report to Confluence',
    )
    parser.add_argument('--report', type=str, help='Path to backfill report file')
    parser.add_argument('--page-id', type=str, help='Confluence page ID (overrides env)')
    
    args = parser.parse_args()
    
    # Najdi report
    report_file = args.report
    if not report_file:
        report_file = find_latest_backfill_report()
    
    if not report_file:
        print("❌ No backfill report found")
        return 1
    
    if not Path(report_file).exists():
        print(f"❌ Report file not found: {report_file}")
        return 1
    
    print(f"📋 Using report: {Path(report_file).name}")
    
    # Načti config
    base_url = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
    username = os.getenv('CONFLUENCE_USERNAME')
    api_token = os.getenv('CONFLUENCE_API_TOKEN')
    page_id = args.page_id or os.getenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID')
    
    if not username or not api_token:
        print("❌ Missing CONFLUENCE_USERNAME or CONFLUENCE_API_TOKEN")
        return 1
    
    if not page_id:
        print("❌ Missing CONFLUENCE_RECENT_INCIDENTS_PAGE_ID")
        return 1
    
    print(f"📤 Publishing to Confluence")
    print(f"   Page ID: {page_id}")
    print(f"   Base URL: {base_url}")
    
    # Extrahuj sekce z reportu
    print(f"📋 Extracting report sections...")
    summary, details = extract_report_sections(report_file)
    
    if not summary and not details:
        print("❌ Could not extract report sections")
        return 1
    
    print(f"   ✓ Summary: {len(summary)} chars")
    print(f"   ✓ Details: {len(details)} chars")
    
    # Konvertuj na HTML
    print(f"📋 Converting to HTML...")
    html_content = convert_report_to_html(summary, details)
    print(f"   ✓ HTML: {len(html_content)} chars")
    
    # Uploaduj
    print(f"📤 Uploading to Confluence...")
    if update_confluence_page(
        base_url,
        page_id,
        "Recent Incidents - Backfill Analysis",
        html_content,
        username,
        api_token
    ):
        print(f"\n✅ Successfully published backfill report")
        return 0
    else:
        print(f"\n❌ Failed to publish backfill report")
        return 1


if __name__ == '__main__':
    sys.exit(main())
