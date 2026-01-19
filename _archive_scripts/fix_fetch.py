# Fix the pcbs_master field mapping
import sys

with open('fetch_all_errors_paginated.py', 'r') as f:
    content = f.read()

# Nahraď řádek
old_line = "                    'pcbs_master': source.get('kubernetes.labels.eamApplication', 'unknown'),"
new_line = "                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),"

if old_line in content:
    content = content.replace(old_line, new_line)
    with open('fetch_all_errors_paginated.py', 'w') as f:
        f.write(content)
    print("✅ Fixed pcbs_master mapping in fetch_all_errors_paginated.py")
else:
    print("❌ Old line not found")
    sys.exit(1)
