#!/usr/bin/env python3
import os
import base64
import urllib.request
import ssl
import json

# Test connection to Confluence
CONFLUENCE_URL = "https://wiki.kb.cz"
CONFLUENCE_USERNAME = "XX_CONFLUENCE_USER"
CONFLUENCE_PASSWORD = "PP_@9532bb-xmHV26"
CONFLUENCE_PAGE_ID = "1334314207"
CONFLUENCE_PROXY = "http://cntlm.speed-default:3128"

auth_header = base64.b64encode(
    f"{CONFLUENCE_USERNAME}:{CONFLUENCE_PASSWORD}".encode()
).decode()

headers = {
    'Authorization': f'Basic {auth_header}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
}

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

proxies = {'https': CONFLUENCE_PROXY, 'http': CONFLUENCE_PROXY}

opener = urllib.request.build_opener(
    urllib.request.ProxyHandler(proxies),
    urllib.request.HTTPSHandler(context=ssl_context)
)

url = f"{CONFLUENCE_URL}/rest/api/content/{CONFLUENCE_PAGE_ID}?expand=version"

print(f"Testing: {url}")
print(f"Using proxy: {CONFLUENCE_PROXY}")
print(f"Username: {CONFLUENCE_USERNAME}")

try:
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=30) as response:
        print(f"✅ SUCCESS: {response.code}")
        data = json.loads(response.read().decode())
        print(f"   Page: {data.get('title')}")
        print(f"   Version: {data.get('version', {}).get('number')}")
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error: {e.code} {e.reason}")
    try:
        error_body = e.read().decode()
        print(f"   Response: {error_body[:500]}")
    except:
        pass
except Exception as e:
    print(f"❌ Error: {e}")
