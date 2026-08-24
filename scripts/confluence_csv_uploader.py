#!/usr/bin/env python3
"""
Confluence CSV Uploader - Upload CSV files to Confluence as HTML tables
========================================================================

Uploads errors_table.csv and peaks_table.csv to Confluence pages.

Usage:
    python3 confluence_csv_uploader.py
"""

import base64
import csv
import json
import os
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict

try:
    from core.delivery_persistence import (
        connect_from_env,
        persist_notification_deliveries,
    )
except ModuleNotFoundError:
    from scripts.core.delivery_persistence import (
        connect_from_env,
        persist_notification_deliveries,
    )

# Configuration
CONFLUENCE_URL = os.getenv('CONFLUENCE_URL', 'https://wiki.kb.cz')
CONFLUENCE_USERNAME = os.getenv('CONFLUENCE_USERNAME')
CONFLUENCE_TOKEN = os.getenv('CONFLUENCE_TOKEN')
CONFLUENCE_PASSWORD = os.getenv('CONFLUENCE_PASSWORD')
CONFLUENCE_KNOWN_ERRORS_PAGE_ID = os.getenv('CONFLUENCE_KNOWN_ERRORS_PAGE_ID', '1334314201')
CONFLUENCE_KNOWN_PEAKS_PAGE_ID = os.getenv('CONFLUENCE_KNOWN_PEAKS_PAGE_ID', '1334314203')

SCRIPT_DIR = Path(__file__).parent
EXPORTS_DIR = SCRIPT_DIR / 'exports' / 'latest'


def get_confluence_auth_header() -> str:
    if CONFLUENCE_TOKEN:
        return f'Bearer {CONFLUENCE_TOKEN}'
    if CONFLUENCE_USERNAME and CONFLUENCE_PASSWORD:
        credentials = base64.b64encode(
            f'{CONFLUENCE_USERNAME}:{CONFLUENCE_PASSWORD}'.encode()
        ).decode()
        return f'Basic {credentials}'
    return ''


def csv_to_html_table(csv_file: Path, max_rows: Optional[int] = None) -> str:
    """Convert CSV file to HTML table (Confluence storage format).

        Column widths are derived from observed name lengths in real registries:
            - affected_apps: compact enough to stop dominating the table → 290px
            - affected_namespaces: reduced from the old wide value, but +10px for wrapping → 198px
      - behavior / root_cause: multi-line free text → 580/370px
      - timing: '2026-04-30 10:30' → 130px
      - numeric/scalar: 70-90px
    Multi-line cells use <br/> with vertical-align:top so wide columns
    (affected_apps, behavior) stay aligned.
    """
    # Per-column explicit widths (in pixels). Values not listed get DEFAULT_WIDTH.
    COLUMN_WIDTHS: Dict[str, int] = {
        # peaks
        'first_seen': 130,
        'last_seen': 130,
        'total_errors': 80,
        'occurrence_count': 70,
        'avg_errors_per_peak': 70,
        'trend_7d': 110,
        'periodicity': 130,
        'root_cause': 370,
        'behavior': 580,
        'affected_namespaces': 198,
        'affected_apps': 290,
        'test': 60,
        'activity': 100,
        'peak_id': 90,
        # errors
        'occurrence_total': 90,
        'occurrence_24h': 90,
        'occurrence_2h': 90,
        'severity': 80,
        'trend_2h': 100,
        'trend_24h': 100,
        'scope': 100,
        'category': 110,
        'status': 80,
        'jira': 100,
        'notes': 140,
        'problem_id': 100,
        'problem_key': 270,
        'flow': 130,
        'error_class': 200,
        'detail': 320,
        'score': 70,
        'ratio': 70,
    }
    HEADER_LABELS: Dict[str, str] = {
        'occurrence_total': 'Total Count',
        'occurrence_24h': '24h Count',
        'occurrence_2h': '2h Count',
    }
    HIDDEN_COLUMNS = {
        'jira',
        'notes',
    }
    DEFAULT_WIDTH = 110

    # Cells that should preserve newlines (multi-line content)
    MULTILINE_COLUMNS = {
        'affected_apps', 'affected_namespaces',
        'root_cause', 'behavior',
        'detail',
    }

    def format_header_label(header_key: str, original_header: str) -> str:
        if header_key in HEADER_LABELS:
            return HEADER_LABELS[header_key]
        parts = [part for part in header_key.split('_') if part]
        if not parts:
            return original_header
        formatted = []
        for part in parts:
            formatted.append(part.lower() if any(ch.isdigit() for ch in part) else part.capitalize())
        return ' '.join(formatted)

    html_parts = []

    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        header_keys = [h.strip().lower() for h in headers]
        visible_indices = [
            index for index, header_key in enumerate(header_keys)
            if header_key not in HIDDEN_COLUMNS
        ]
        visible_headers = [headers[index] for index in visible_indices]
        visible_header_keys = [header_keys[index] for index in visible_indices]
        widths = [COLUMN_WIDTHS.get(h_lower, DEFAULT_WIDTH) for h_lower in visible_header_keys]
        total_width = sum(widths)

        html_parts.append('<div style="overflow-x: auto; max-width: 100%;">')
        html_parts.append(
            f'<table style="table-layout: fixed; width: {total_width}px; border-collapse: collapse;">'
        )
        html_parts.append('<colgroup>')

        # Column widths
        for width in widths:
            html_parts.append(f'<col style="width: {width}px"/>')
        html_parts.append('</colgroup>')

        # Header row
        html_parts.append('<thead><tr>')
        for col_idx, header in enumerate(visible_headers):
            header_key = visible_header_keys[col_idx] if col_idx < len(visible_header_keys) else header.strip().lower()
            header_label = format_header_label(header_key, header)
            width = widths[col_idx] if col_idx < len(widths) else DEFAULT_WIDTH
            html_parts.append(
                '<th style="'
                f'width: {width}px; min-width: {width}px; max-width: {width}px; '
                'vertical-align: top; white-space: normal; overflow-wrap: anywhere; word-break: break-word;'
                '"><p><strong>'
                f'{header_label}'
                '</strong></p></th>'
            )
        html_parts.append('</tr></thead>')

        # Data rows
        html_parts.append('<tbody>')
        row_count = 0
        for row in reader:
            if max_rows is not None and row_count >= max_rows:
                break
            html_parts.append('<tr>')
            for col_idx, source_index in enumerate(visible_indices):
                cell = row[source_index] if source_index < len(row) else ''
                col_key = visible_header_keys[col_idx] if col_idx < len(visible_header_keys) else ''
                width = widths[col_idx] if col_idx < len(widths) else DEFAULT_WIDTH
                if col_key == 'problem_key':
                    cell = cell.replace(':', ': ')
                # Escape HTML special chars
                escaped = cell.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                cell_style = (
                    f'width: {width}px; min-width: {width}px; max-width: {width}px; '
                    'vertical-align: top; white-space: normal; overflow-wrap: anywhere; word-break: break-word;'
                )
                # Multi-line columns: convert newlines to <br/>; align to top
                if col_key in MULTILINE_COLUMNS:
                    escaped = escaped.replace('\n', '<br/>')
                    html_parts.append(
                        f'<td style="{cell_style}"><p>{escaped}</p></td>'
                    )
                else:
                    # Single-line columns: collapse newlines to spaces (defensive)
                    escaped = escaped.replace('\n', ' ')
                    html_parts.append(
                        f'<td style="{cell_style}"><p>{escaped}</p></td>'
                    )
            html_parts.append('</tr>')
            row_count += 1
        html_parts.append('</tbody>')

    html_parts.append('</table>')
    html_parts.append('</div>')

    return '\n'.join(html_parts)


def upload_to_confluence(page_id: str, html_content: str) -> bool:
    """Upload HTML content to Confluence page."""
    auth_header = get_confluence_auth_header()
    if not auth_header:
        print("❌ Missing Confluence token or username/password credentials")
        return False
    
    headers = {
        'Authorization': auth_header,
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
        current_title = page_data['title']
    except Exception as e:
        print(f"❌ Failed to get page version: {e}")
        return False
    
    # Update page
    update_data = {
        'version': {'number': current_version + 1},
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
    publication_outcomes = []
    attempted_at = datetime.now(timezone.utc)
    publication_date = attempted_at.date().isoformat()
    
    # Upload Known Errors
    errors_csv = EXPORTS_DIR / 'errors_table.csv'
    if errors_csv.exists():
        total_count += 1
        print(f"\n📊 Uploading Known Errors...")
        print(f"   File: {errors_csv}")
        print(f"   Page ID: {CONFLUENCE_KNOWN_ERRORS_PAGE_ID}")
        
        try:
            html = csv_to_html_table(errors_csv)
            success = upload_to_confluence(
                CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
                html
            )
            publication_outcomes.append({
                'dedup_key': f'known-errors:{publication_date}',
                'destination': 'confluence_known_errors',
                'status': 'delivered' if success else 'failed',
                'provider_message': (
                    'Confluence page updated'
                    if success
                    else 'Uploader returned unsuccessful status'
                ),
                'metadata': {
                    'page_id': CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
                    'csv_file': str(errors_csv),
                },
                'attempted_at': attempted_at,
            })
            if success:
                success_count += 1
        except Exception as e:
            publication_outcomes.append({
                'dedup_key': f'known-errors:{publication_date}',
                'destination': 'confluence_known_errors',
                'status': 'failed',
                'provider_message': str(e),
                'metadata': {
                    'page_id': CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
                    'csv_file': str(errors_csv),
                },
                'attempted_at': attempted_at,
            })
            print(f"❌ Error processing errors CSV: {e}")
    else:
        total_count += 1
        publication_outcomes.append({
            'dedup_key': f'known-errors:{publication_date}',
            'destination': 'confluence_known_errors',
            'status': 'failed',
            'provider_message': 'Expected CSV file is missing',
            'metadata': {
                'page_id': CONFLUENCE_KNOWN_ERRORS_PAGE_ID,
                'csv_file': str(errors_csv),
            },
            'attempted_at': attempted_at,
        })
        print(f"\n⚠️ Known Errors CSV not found: {errors_csv}")
    
    # Upload Known Peaks
    peaks_csv = EXPORTS_DIR / 'peaks_table.csv'
    if peaks_csv.exists():
        total_count += 1
        print(f"\n📊 Uploading Known Peaks...")
        print(f"   File: {peaks_csv}")
        print(f"   Page ID: {CONFLUENCE_KNOWN_PEAKS_PAGE_ID}")
        
        try:
            html = csv_to_html_table(peaks_csv)
            success = upload_to_confluence(
                CONFLUENCE_KNOWN_PEAKS_PAGE_ID,
                html
            )
            publication_outcomes.append({
                'dedup_key': f'known-peaks:{publication_date}',
                'destination': 'confluence_known_peaks',
                'status': 'delivered' if success else 'failed',
                'provider_message': (
                    'Confluence page updated'
                    if success
                    else 'Uploader returned unsuccessful status'
                ),
                'metadata': {
                    'page_id': CONFLUENCE_KNOWN_PEAKS_PAGE_ID,
                    'csv_file': str(peaks_csv),
                },
                'attempted_at': attempted_at,
            })
            if success:
                success_count += 1
        except Exception as e:
            publication_outcomes.append({
                'dedup_key': f'known-peaks:{publication_date}',
                'destination': 'confluence_known_peaks',
                'status': 'failed',
                'provider_message': str(e),
                'metadata': {
                    'page_id': CONFLUENCE_KNOWN_PEAKS_PAGE_ID,
                    'csv_file': str(peaks_csv),
                },
                'attempted_at': attempted_at,
            })
            print(f"❌ Error processing peaks CSV: {e}")
    else:
        total_count += 1
        publication_outcomes.append({
            'dedup_key': f'known-peaks:{publication_date}',
            'destination': 'confluence_known_peaks',
            'status': 'failed',
            'provider_message': 'Expected CSV file is missing',
            'metadata': {
                'page_id': CONFLUENCE_KNOWN_PEAKS_PAGE_ID,
                'csv_file': str(peaks_csv),
            },
            'attempted_at': attempted_at,
        })
        print(f"\n⚠️ Known Peaks CSV not found: {peaks_csv}")
    
    print("\n" + "=" * 70)
    print(f"📋 Summary: {success_count}/{total_count} tables uploaded successfully")

    try:
        persist_notification_deliveries(
            connect_from_env,
            publication_outcomes,
            notification_type='backfill_registry_publication',
            window_start=attempted_at.replace(hour=0, minute=0, second=0, microsecond=0),
        )
    except Exception as e:
        print(f"❌ Failed to persist publication outcomes: {e}")
        return False

    return total_count == 2 and success_count == total_count


if __name__ == '__main__':
    import sys
    success = main()
    sys.exit(0 if success else 1)
