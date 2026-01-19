"""Vysvětlí jak weekly trends funguje"""
import json

with open('/tmp/trends_result.json', 'r') as f:
    data = json.load(f)

print("=" * 80)
print("WEEKLY TRENDS - DETAILNÍ ANALÝZA")
print("=" * 80)
print(f"\nPeriod: {data['period_start']} → {data['period_end']}")
print(f"Total errors: {data['total_errors']:,}")
print(f"Sample analyzed: 1000 errors (10% sample)")
print()

print("=" * 80)
print("JAK TO FUNGUJE:")
print("=" * 80)
print("1. Fetchuje 1000 sample errorů z ES za dané období")
print("2. Pro každý error:")
print("   - Extrahuje message, app, timestamp, traceId")
print("   - Normalizuje message (odstraní čísla 3+ digits → {ID})")
print("   - Extrahuje error_code (err.XXX)")
print("   - Extrahuje Card ID pokud existuje")
print("3. Clusteruje errory podle normalized message")
print("4. Pro každý cluster:")
print("   - Count = počet errorů v clusteru")
print("   - First/last seen = časové rozmezí")
print("   - Status = 'recurring' pokud >1 den, jinak 'new'")
print("   - Known issue pokud count >10")
print()

print("=" * 80)
print("TOP 5 PATTERNS (NEW ISSUES):")
print("=" * 80)

for i, issue in enumerate(data['new_issues'][:5], 1):
    print(f"\n{i}. PATTERN: {issue['fingerprint']}")
    print(f"   Original sample: {issue['message_sample'][:100]}")
    print(f"   Count: {issue['count']}")
    print(f"   Apps: {', '.join(issue['affected_apps'])}")
    print(f"   First seen: {issue['first_seen']}")
    print(f"   Last seen: {issue['last_seen']}")
    print(f"   Status: {issue['status']}")
    print(f"   Error code: {issue['error_code']}")

print("\n" + "=" * 80)
print("PROČ JSOU VŠE 'NEW' A NE 'RECURRING'?")
print("=" * 80)
print("Protože data jsou jen z posledních 24 hodin (days=1)")
print("Status = 'recurring' pouze pokud (last_seen - first_seen) > 1 den")
print("\nZkus zavolat: GET /api/v1/trends/weekly?days=7")
print("Tam uvidíš 'recurring' patterns které se opakují přes více dní")
print("=" * 80)

