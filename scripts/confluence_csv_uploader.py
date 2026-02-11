#!/usr/bin/env python3
"""
Confluence CSV Uploader - Upload CSV files to Confluence as HTML tables
========================================================================

Uploads errors_table.csv and peaks_table.csv to Confluence pages.

Usage:
    python3 confluence_csv_uploader.py
"""

import os
import csv
import json
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from typing import Optional, List, Dict

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
CONFLUENCE_PASSWORD = os.getenv('CONFLUENCE_PASSWORD')  # OAuth token
CONFLUENCE_KNOWN_ERRORS_PAGE_ID = os.getenv('CONFLUENCE_KNOWN_ERRORS_PAGE_ID', '1334314208')
CONFLUENCE_KNOWN_PEAKS_PAGE_ID = os.getenv('CONFLUENCE_KNOWN_PEAKS_PAGE_ID', '1334314209')

SCRIPT_DIR = Path(__file__).parent
EXPORTS_DIR = SCRIPT_DIR / 'exports' / 'latest'


def csv_to_html_table(csv_file: Path, max_rows: int = 50) -> str:
    """Convert CSV file to HTML table (Confluence storage format)."""
    html_parts = []
    
    html_parts.append('<table>')
    html_parts.append('<colgroup>')
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        
        # Column widths
        for _ in headers:
            html_parts.append('<col/>')
        html_parts.append('</colgroup>')
        
        # Header row
        html_parts.append('<thead><tr>')
        for header in headers:
            html_parts.append(f'<th><p><strong>{header}</strong></p></th>')
        html_parts.append('</tr></thead>')
        
        # Data rows
        html_parts.append('<tbody>')
        row_count = 0
        for row in reader:
            if row_count >= max_rows:
                break
            html_parts.append('<tr>')
            for cell in row:
                # Escape HTML special chars
                escaped = cell.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                html_parts.append(f'<td><p>{escaped}</p></td>')
            html_parts.append('</tr>')
            row_count += 1
        html_parts.append('</tbody>')
    
    html_parts.append('</table>')
    
    return '\n'.join(html_parts)


def upload_to_confluence(page_id: str, title: str, html_content: str) -> bool:
    """Upload HTML content to Confluence page."""
    if not CONFLUENCE_PASSWORD:
        print("❌ Missing CONFLUENCE_PASSWORD (OAuth token)")
        return False
    
    headers = {
        'Authorization': f'Bearer {CONFLUENCE_PASSWORD}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    # Proxy support
    proxies = urllib.request.getproxies()
    confluence_proxy = os.getenv('CONFLUENCE_PROXY')
    if confluence_proxy:
        proxies['https'] = confluence_proxy
        proxies['http'] = confluence_proxy
    
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies),
        urllib.request.HTTPSHandler(context=ssl_context)
    )
    
    # Get current version
    try:
        url = f"{CONFLUENCE_URL}/rest/api/content/{page_id}?expand=version"
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req) as response:
            page_data = json.loads(response.read().decode())
        current_version = page_data['version']['number']
    except Exception as e:
        print(f"❌ Failed to get page version: {e}")
        return False
    
    # Update page
    update_data = {
        'version': {'number': current_version + 1},
        'title': title,
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
            response_data = json.loads(response.read().decode())
        print(f"✅ Successfully uploaded (version {response_data['version']['number']})")
        return True
    except urllib.error.HTTPError as e:
        print(f"❌ Failed to upload: {e.code} {e.reason}")
        try:
            error_body = e.read().decode()
            print(f"   Details: {error_body[:200]}")
        except:
            pass
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Main function."""
    print("📤 Confluence CSV Uploader")
    print("=" * 70)
    
    success_count = 0
    total_count = 0
    
    # Upload Known Errors
    errors_csv = EXPORTS_DIR / 'errors_table.csv'
    if errors_csv.exists():
        total_count += 1
        print(f"\n📊 Uploading Known Errors...")
        print(f"   File: {errors_csv}")
        print(f"   Page ID: {CONFLUENCE_KNOWN_ERRORS_PAGE_ID}")
        
        try:
            html = csv_to_html_table(errors_csv, max_rows=50)
            if upload_to_confluence(
                CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
                'Known Errors - Daily Update',
                html
            ):
                success_count += 1
        except Exception as e:
            print(f"❌ Error processing errors CSV: {e}")
    else:
        print(f"\n⚠️ Known Errors CSV not found: {errors_csv}")
    
    # Upload Known Peaks
    peaks_csv = EXPORTS_DIR / 'peaks_table.csv'
    if peaks_csv.exists():
        total_count += 1
        print(f"\n📊 Uploading Known Peaks...")
        print(f"   File: {peaks_csv}")
        print(f"   Page ID: {CONFLUENCE_KNOWN_PEAKS_PAGE_ID}")
        
        try:
            html = csv_to_html_table(peaks_csv, max_rows=50)
            if upload_to_confluence(
                CONFLUENCE_KNOWN_PEAKS_PAGE_ID,
                'Known Peaks - Daily Update',
                html
            ):
                success_count += 1
        except Exception as e:
            print(f"❌ Error processing peaks CSV: {e}")
    else:
        print(f"\n⚠️ Known Peaks CSV not found: {peaks_csv}")
    
    print("\n" + "=" * 70)
    print(f"📋 Summary: {success_count}/{total_count} tables uploaded successfully")
    
    return success_count == total_count


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
