#!/usr/bin/env python3
"""
Publish Recent Incidents Report to Confluence
Extracts problem analysis report and uploads to Recent Incidents page
"""

import os
import re
from datetime import datetime
from pathlib import Path

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
CONFLUENCE_USERNAME = os.getenv('CONFLUENCE_USERNAME')
CONFLUENCE_PASSWORD = os.getenv('CONFLUENCE_PASSWORD')
CONFLUENCE_PAGE_ID = '1334314207'  # Recent Incidents page
REPORTS_DIR = Path(__file__).parent / 'reports'

def get_latest_problem_report():
    """Get the most recent problem analysis report"""
    reports = sorted(REPORTS_DIR.glob('problem_report_*.txt'), reverse=True)
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
            # Split by problem headers (dashes + # number)
            problems = re.split(r'(?=\n(?:──|--){20,}\n#\d+)', details_text)
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
    """Convert report data to HTML suitable for Confluence (dark mode friendly)"""
    if not report_data:
        return None
    
    html_parts = []
    
    # Wrap in div
    html_parts.append('<div>')
    
    # Header with metadata
    if report_data.get('header'):
        period, generated, run_id = report_data['header']
        html_parts.append('<h2>Problem Analysis Report</h2>')
        html_parts.append(f'<p><strong>Period:</strong> {period}<br/>')
        html_parts.append(f'<strong>Generated:</strong> {generated}<br/>')
        html_parts.append(f'<strong>Run ID:</strong> {run_id}</p>')
    
    # Executive Summary
    if report_data['has_summary']:
        html_parts.append('<h3>Executive Summary</h3>')
        html_parts.append('<pre style="font-family: monospace; white-space: pre-wrap; word-wrap: break-word; padding: 10px; border-left: 3px solid #4a90e2; margin: 10px 0;">')
        
        summary_text = report_data['executive_summary']
        escaped_summary = summary_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html_parts.append(escaped_summary)
        
        html_parts.append('</pre>')
    
    # Problem Details
    if report_data['has_details']:
        html_parts.append('<h3>Problem Details (Top 20)</h3>')
        html_parts.append('<pre style="font-family: monospace; white-space: pre-wrap; word-wrap: break-word; padding: 10px; border-left: 3px solid #f39c12; margin: 10px 0; overflow-x: auto;">')
        
        details_text = report_data['problem_details']
        escaped_details = details_text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html_parts.append(escaped_details)
        
        html_parts.append('</pre>')
    
    html_parts.append('</div>')
    html_parts.append(f'<p><small><em>Last updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}</em></small></p>')
    
    return '\n'.join(html_parts)

def upload_via_confluence_api(html_content):
    """Upload HTML content directly to Confluence via API"""
    if not CONFLUENCE_USERNAME or not CONFLUENCE_PASSWORD:
        print("❌ Missing CONFLUENCE_USERNAME or CONFLUENCE_PASSWORD")
        return False
    
    import base64
    import json
    import urllib.request
    import urllib.error
    import ssl
    
    auth_header = base64.b64encode(
        f"{CONFLUENCE_USERNAME}:{CONFLUENCE_PASSWORD}".encode()
    ).decode()
    
    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    # Ignore SSL certificate verification
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    # Step 1: Get current page version
    try:
        url = f"{CONFLUENCE_URL}/rest/api/content/{CONFLUENCE_PAGE_ID}?expand=version,body.storage"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, context=ssl_context) as response:
            page_data = json.loads(response.read().decode())
        current_version = page_data['version']['number']
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to get page version: {e.code} {e.reason}")
        return False
    except Exception as e:
        print(f"❌ Error getting page: {e}")
        return False
    
    # Step 2: Update page with new content
    update_data = {
        'version': {
            'number': current_version + 1
        },
        'title': 'Recent Incidents - Daily Problem Analysis',
        'type': 'page',
        'body': {
            'storage': {
                'value': html_content,
                'representation': 'storage'
            }
        }
    }
    
    try:
        url = f"{CONFLUENCE_URL}/rest/api/content/{CONFLUENCE_PAGE_ID}"
        req = urllib.request.Request(
            url,
            data=json.dumps(update_data).encode(),
            headers=headers,
            method='PUT'
        )
        with urllib.request.urlopen(req, context=ssl_context) as response:
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

def main():
    """Main workflow"""
    print("📋 Publishing Recent Incidents Report to Confluence...")
    
    # Get latest report
    report_path = get_latest_problem_report()
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
        print("✅ Recent Incidents published successfully!")
        return True
    else:
        print("❌ Failed to publish Recent Incidents")
        return False

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)
