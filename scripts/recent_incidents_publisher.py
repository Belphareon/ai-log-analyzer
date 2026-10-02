#!/usr/bin/env python3
"""
Publish Recent Incidents Report to Confluence
Extracts problem analysis report and uploads to Recent Incidents page
"""

import os
import re
from html import escape
from datetime import datetime
from pathlib import Path
from typing import Optional
import urllib.request

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
if 'confluence.kb.cz' in CONFLUENCE_URL:
    print(f"⚠️ CONFLUENCE_URL overridden: {CONFLUENCE_URL} -> https://wiki.kb.cz")
    CONFLUENCE_URL = 'https://wiki.kb.cz'
CONFLUENCE_TOKEN = os.getenv('CONFLUENCE_TOKEN') or os.getenv('CONFLUENCE_PASSWORD')
REPORTS_DIR = Path(__file__).parent / 'reports'


def get_confluence_page_id() -> str:
    return os.getenv('CONFLUENCE_RECENT_INCIDENTS_PAGE_ID', '').strip()


def get_confluence_auth_header() -> str:
    if CONFLUENCE_TOKEN:
        return f'Bearer {CONFLUENCE_TOKEN}'
    return ''


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

def _parse_summary(summary_text):
    sections = {'Classification': [], 'Impact and evidence coverage': []}
    current_section = 'Classification'
    notes = []
    for raw_line in summary_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == 'Impact and evidence coverage:':
            current_section = line[:-1]
            continue
        match = re.match(r'^(?:-\s*)?([^:]+):\s*(.+)$', line)
        if match:
            sections[current_section].append((match.group(1), match.group(2)))
        else:
            notes.append(line)
    return sections, notes


def _parse_cause_families(details_text):
    block_pattern = re.compile(
        r'^─{20,}\n#(?P<index>\d+) \[(?P<label>[^\]]+)\] '
        r'(?P<title>.*?)\n─{20,}\n(?P<body>.*?)(?=^─{20,}\n#\d+|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    families = []
    for match in block_pattern.finditer(details_text):
        fields = {}
        section = 'overview'
        next_action_lines = []
        for raw_line in match.group('body').splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.endswith(':') and line in {
                'Impact (current period):', 'Evidence:', 'Next action:'
            }:
                section = line[:-1].lower().replace(' ', '_')
                continue
            field_match = re.match(r'^([^:]+):\s*(.*)$', line)
            if field_match:
                fields[field_match.group(1).strip()] = field_match.group(2).strip()
            elif section == 'next_action':
                next_action_lines.append(line)
        if next_action_lines:
            fields['Next action'] = ' '.join(next_action_lines)
        families.append({
            'index': match.group('index'),
            'label': match.group('label'),
            'title': match.group('title').strip(),
            'fields': fields,
        })
    return families


def _metric_table(title, rows):
    if not rows:
        return ''
    body = ''.join(
        '<tr>'
        f'<td style="padding:6px 10px;border:1px solid #dfe1e6;">{escape(label)}</td>'
        f'<td style="padding:6px 10px;border:1px solid #dfe1e6;text-align:right;">'
        f'<strong>{escape(value)}</strong></td>'
        '</tr>'
        for label, value in rows
    )
    return (
        f'<h3>{escape(title)}</h3>'
        '<table style="border-collapse:collapse;width:100%;max-width:760px;">'
        f'<tbody>{body}</tbody></table>'
    )


def _render_family_table(families):
    if not families:
        return ''
    rows = []
    for family in families:
        fields = family['fields']
        rows.append(
            '<tr>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;">{escape(family["label"])}</td>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;"><strong>{escape(family["title"])}</strong></td>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;">{escape(fields.get("Root application", "N/A"))}</td>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;text-align:right;">{escape(fields.get("Unique operations", "N/A"))}</td>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;text-align:right;">{escape(fields.get("Raw ERROR lines", "N/A"))}</td>'
            f'<td style="padding:7px;border:1px solid #dfe1e6;">{escape(fields.get("Outward status", "N/A"))}</td>'
            '</tr>'
        )
    return (
        '<h2>Current Cause Families</h2>'
        '<table style="border-collapse:collapse;width:100%;">'
        '<thead><tr style="background:#f4f5f7;">'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:left;">Assessment</th>'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:left;">Cause</th>'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:left;">Root application</th>'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:right;">Operations</th>'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:right;">ERROR lines</th>'
        '<th style="padding:7px;border:1px solid #dfe1e6;text-align:left;">Status</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _render_family_details(families):
    blocks = []
    for family in families:
        fields = family['fields']
        facts = [
            ('Root application', fields.get('Root application', 'N/A')),
            ('Operation', fields.get('Operation', 'N/A')),
            ('Outward status', fields.get('Outward status', 'N/A')),
            ('Unique operations', fields.get('Unique operations', 'N/A')),
            ('Operation count evidence', fields.get('Operation count evidence', 'N/A')),
            ('Raw ERROR lines', fields.get('Raw ERROR lines', 'N/A')),
            ('Logging amplification', fields.get('Logging amplification', 'N/A')),
            ('Representative trace', fields.get('Representative trace', 'N/A')),
        ]
        fact_rows = ''.join(
            f'<tr><td style="padding:5px 8px;border:1px solid #dfe1e6;">{escape(label)}</td>'
            f'<td style="padding:5px 8px;border:1px solid #dfe1e6;">{escape(value)}</td></tr>'
            for label, value in facts
        )
        blocks.append(
            '<div style="margin-top:22px;padding-top:12px;border-top:2px solid #42526e;">'
            f'<h3>#{escape(family["index"])} [{escape(family["label"])}] '
            f'{escape(family["title"])}</h3>'
            f'<p><strong>Assessment:</strong> {escape(fields.get("Assessment", family["label"]))}</p>'
            '<table style="border-collapse:collapse;width:100%;max-width:860px;">'
            f'<tbody>{fact_rows}</tbody></table>'
            f'<p><strong>Current scope:</strong> {escape(fields.get("Applications", "N/A"))}; '
            f'{escape(fields.get("Namespaces", "N/A"))}</p>'
            f'<p><strong>Next action:</strong> {escape(fields.get("Next action", "Needs owner classification."))}</p>'
            '</div>'
        )
    return ''.join(blocks)


def _legacy_text_html(text):
    paragraphs = [escape(part.strip()).replace('\n', '<br/>') for part in text.split('\n\n') if part.strip()]
    return ''.join(f'<p>{paragraph}</p>' for paragraph in paragraphs)


def convert_to_html(report_data):
    """Convert report data to structured Confluence storage HTML."""
    if not report_data:
        return None
    
    html_parts = []
    
    # Wrap in div
    html_parts.append('<div>')
    
    # Header with metadata
    if report_data.get('header'):
        period, generated, run_id = report_data['header']
        html_parts.append('<h2>Problem Analysis Report</h2>')
        html_parts.append(f'<p><strong>Period:</strong> {escape(period)}<br/>')
        html_parts.append(f'<strong>Generated:</strong> {escape(generated)}<br/>')
        html_parts.append(f'<strong>Run ID:</strong> {escape(run_id)}</p>')
    
    # Executive Summary
    if report_data['has_summary']:
        summary_sections, notes = _parse_summary(report_data['executive_summary'])
        html_parts.append('<h2>Executive Summary</h2>')
        html_parts.append(_metric_table('Classification', summary_sections['Classification']))
        html_parts.append(_metric_table(
            'Impact and Evidence Coverage',
            summary_sections['Impact and evidence coverage'],
        ))
        html_parts.extend(f'<p>{escape(note)}</p>' for note in notes)
    
    # Problem Details
    if report_data['has_details']:
        families = _parse_cause_families(report_data['problem_details'])
        if families:
            html_parts.append(_render_family_table(families))
            html_parts.append('<h2>Cause Family Details</h2>')
            html_parts.append(_render_family_details(families))
        else:
            html_parts.append('<h2>Problem Details (Top 20)</h2>')
            html_parts.append(_legacy_text_html(report_data['problem_details']))
    
    html_parts.append('</div>')
    html_parts.append(f'<p><small><em>Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</em></small></p>')
    
    return '\n'.join(html_parts)

def upload_via_confluence_api(html_content):
    """Upload HTML content directly to Confluence via API"""
    auth_header = get_confluence_auth_header()
    if not auth_header:
        print("❌ Missing CONFLUENCE_TOKEN or CONFLUENCE_PASSWORD")
        return False
    page_id = get_confluence_page_id()
    if not page_id:
        print("❌ Missing CONFLUENCE_RECENT_INCIDENTS_PAGE_ID")
        return False
    
    import json
    import urllib.error
    import ssl
    
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
        current_title = page_data['title']
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
