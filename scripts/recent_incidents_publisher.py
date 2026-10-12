#!/usr/bin/env python3
"""
Publish Recent Incidents Report to Confluence
Extracts problem analysis report and uploads to Recent Incidents page
"""

import os
import re
import html
import json
import ssl
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional
import urllib.request

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
if 'confluence.kb.cz' in CONFLUENCE_URL:
    print(f"⚠️ CONFLUENCE_URL overridden: {CONFLUENCE_URL} -> https://wiki.kb.cz")
    CONFLUENCE_URL = 'https://wiki.kb.cz'
CONFLUENCE_USERNAME = os.getenv('CONFLUENCE_USERNAME')
CONFLUENCE_PASSWORD = os.getenv('CONFLUENCE_PASSWORD')
CONFLUENCE_TOKEN = os.getenv('CONFLUENCE_TOKEN') or CONFLUENCE_PASSWORD
REPORTS_DIR = Path(__file__).parent / 'reports'


def get_confluence_page_id() -> str:
    return os.getenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', '').strip()


def get_confluence_auth_header() -> str:
    return f'Bearer {CONFLUENCE_TOKEN}' if CONFLUENCE_TOKEN else ''


def get_latest_problem_report(reports_dir: Path = REPORTS_DIR):
    """Get the most recent problem analysis report"""
    reports = sorted(reports_dir.glob('problem_report_*.txt'), reverse=True)
    if not reports:
        print("❌ No problem analysis reports found")
        return None
    return reports[0]

def extract_report_content(report_path):
    """Extract EXECUTIVE SUMMARY and PROBLEM DETAILS from report"""
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        result = {}
        
        # Extract header info
        header_match = re.search(
            r'Period: (.+?)\nGenerated: (.+?)\nRun ID: (.+?)(?:\n|$)',
            content
        )
        result['header'] = header_match.groups() if header_match else ()
        
        # Extract EXECUTIVE SUMMARY section (between dashes with exact header)
        exec_match = re.search(
            r'^-{70}\nEXECUTIVE SUMMARY\n-{70}\n(.*?)\n-{70}',
            content,
            re.MULTILINE | re.DOTALL
        )
        result['executive_summary'] = exec_match.group(1).strip() if exec_match else ""
        result['has_summary'] = bool(exec_match)
        
        # Extract PROBLEM DETAILS section
        details_match = re.search(
            r'^-{70}\nPROBLEM DETAILS\n-{70}\n(.*?)(?:\n-{70}\nSTATISTICS|\Z)',
            content,
            re.MULTILINE | re.DOTALL
        )
        
        if details_match:
            details_text = details_match.group(1).strip()
            # Split by problem headers (─ unicode dash or -- ascii dashes, followed by # number)
            # problem_report.py uses '─' * 50 (unicode thick dash)
            problems = re.split(r'(?=\n(?:─{20,}|──|--){20,}\n#\d+)', details_text)
            # Keep only top 20 problems
            result['problem_details'] = '\n'.join(problems[:20])
            result['has_details'] = True
        else:
            result['problem_details'] = ""
            result['has_details'] = False
        
        return result
        
    except Exception as e:
        print(f"❌ Error extracting report: {e}")
        return None

def convert_to_html(report_data):
    """Convert report sections into escaped Confluence tables."""
    if not report_data:
        return None
    
    def render_table(title: str, text: str) -> str:
        rows = ''.join(
            f'<tr><td>{html.escape(line)}</td></tr>'
            for line in text.splitlines()
            if line.strip()
        )
        return f'<h3>{html.escape(title)}</h3><table><tbody>{rows}</tbody></table>'

    html_parts = []
    html_parts.append('<div>')

    if report_data.get('header'):
        period, generated, run_id = report_data['header']
        html_parts.append('<h2>Problem Analysis Report</h2>')
        html_parts.append(f'<p><strong>Period:</strong> {html.escape(str(period))}<br/>')
        html_parts.append(f'<strong>Generated:</strong> {html.escape(str(generated))}<br/>')
        html_parts.append(f'<strong>Run ID:</strong> {html.escape(str(run_id))}</p>')

    if report_data['has_summary']:
        html_parts.append(render_table('Current Cause Families', report_data['executive_summary']))

    if report_data['has_details']:
        html_parts.append(render_table('Problem Details (Top 20)', report_data['problem_details']))

    html_parts.append('</div>')
    html_parts.append(f'<p><small><em>Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</em></small></p>')
    
    return '\n'.join(html_parts)

def upload_via_confluence_api(html_content):
    """Upload HTML content directly to Confluence via API"""
    page_id = get_confluence_page_id()
    auth_header = get_confluence_auth_header()
    if not page_id or not auth_header:
        print("❌ Missing CONFLUENCE_RECENT_INCIDENTS_PAGE_ID or Confluence token")
        return False
    
    headers = {
        'Authorization': auth_header,
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Ignore SSL certificate verification
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Proxy support (CONFLUENCE_PROXY overrides HTTPS_PROXY/HTTP_PROXY)
    proxies = urllib.request.getproxies()
    confluence_proxy = os.getenv('CONFLUENCE_PROXY')
    if confluence_proxy:
        proxies['https'] = confluence_proxy
        proxies['http'] = confluence_proxy

    print(f"🔧 Confluence URL: {CONFLUENCE_URL}")
    print(f"🔧 Confluence page: {page_id}")
    print(f"🔧 Proxy (https): {proxies.get('https')}")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ssl_context)
    )
    
    # Step 1: Get current page version
    try:
        url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=version,body.storage"
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req) as response:
            page_data = json.loads(response.read().decode())
        current_version = page_data['version']['number']
        current_title = page_data.get('title', 'Recent Incidents - Daily Problem Analysis')
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to get page version: {e.code} {e.reason}")
        try:
            error_body = e.read().decode()
            print(f"   Details: {error_body}")
        except Exception:
            pass
        return False
    except urllib.error.URLError as e:
        print(f"❌ Failed to get page version: {e}")
        return False
    except Exception as e:
        print(f"❌ Error getting page: {e}")
        return False
    
    # Step 2: Update page with new content
    update_data = {
        'version': {
            'number': current_version + 1
        },
        'title': current_title,
        'type': 'page',
        'body': {
            'storage': {
                'value': html_content,
                'representation': 'storage'
            }
        }
    }
    
    try:
        url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}"
        req = urllib.request.Request(
            url,
            data=json.dumps(update_data).encode(),
            headers=headers,
            method='PUT'
        )
        with opener.open(req) as response:
            result = json.loads(response.read().decode())
        print(f"✅ Successfully uploaded Recent Incidents (version {result['version']['number']})")
        return True
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"❌ Failed to update page: {e.code} {e.reason}")
        print(f"   Details: {error_body}")
        return False
    except Exception as e:
        print(f"❌ Error uploading to Confluence: {e}")
        return False

def main(report_path: Optional[str] = None, reports_dir: Optional[str] = None):
    """Main workflow"""
    print("📋 Publishing Recent Incidents Report to Confluence...")

    # Get report
    if report_path:
        report_path = Path(report_path)
        if not report_path.exists():
            print(f"❌ Report file not found: {report_path}")
            return False
    else:
        reports_root = Path(reports_dir) if reports_dir else REPORTS_DIR
        report_path = get_latest_problem_report(reports_root)
    if not report_path:
        return False
    
    print(f"📄 Using report: {report_path.name}")
    
    # Extract content
    report_data = extract_report_content(report_path)
    if not report_data:
        print("❌ Failed to extract report content")
        return False
    
    if not report_data['has_summary']:
        print("❌ No EXECUTIVE SUMMARY section found")
        return False
    
    if not report_data['has_details']:
        print("❌ No PROBLEM DETAILS section found")
        return False
    
    print(f"   ✅ EXECUTIVE SUMMARY extracted")
    print(f"   ✅ PROBLEM DETAILS extracted (top 20)")
    
    # Convert to HTML
    html_content = convert_to_html(report_data)
    if not html_content:
        print("❌ Failed to convert to HTML")
        return False
    
    # Upload to Confluence
    if upload_via_confluence_api(html_content):
        print("✅ Confluence upload confirmed")
        print("✅ Recent Incidents published successfully!")
        return True
    else:
        print("❌ Failed to publish Recent Incidents")
        return False

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Publish Recent Incidents report to Confluence')
    parser.add_argument('--report', type=str, help='Path to problem report file')
    parser.add_argument('--reports-dir', type=str, help='Directory with problem_report_*.txt files')
    args = parser.parse_args()

    success = main(report_path=args.report, reports_dir=args.reports_dir)
    exit(0 if success else 1)
