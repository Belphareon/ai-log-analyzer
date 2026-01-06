#!/usr/bin/env python3
"""
VERIFICATION CHECKLIST - Compare user-reported peaks vs DB actual values
Generated: 2025-12-17 16:50 UTC
"""

PEAKS_TO_VERIFY = {
    "4.12 Fri 07:00": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": 2884,
        "status": "TO VERIFY"
    },
    "4.12 Fri 20:30": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": 673,
        "status": "TO VERIFY"
    },
    "5.12 Sat 14:30": {
        "namespace": "pcb-dev-01-app",
        "expected_peak": 43000,
        "note": "extreme peak - lasted until 15:30 with multi-namespace spikes",
        "status": "TO VERIFY"
    },
    "5.12 Sat 20:00": {
        "namespace": "pcb-dev-01-app",
        "expected_peak": 1573,
        "status": "TO VERIFY - CURRENTLY BROKEN (998.0 in DB)"
    },
    "4.12 Fri 9:45": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": "NO peak - normal traffic",
        "status": "TO VERIFY"
    },
    "4.12 Fri 13:15": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": "NO peak - normal traffic",
        "status": "TO VERIFY"
    },
    "4.12 Fri 22:30": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": 687,
        "status": "TO VERIFY"
    },
    "4.12 Fri 23:15": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": "NO peak - normal traffic",
        "status": "TO VERIFY"
    },
    "5.12 Sat 07:00": {
        "namespace": "pcb-ch-sit-01-app",
        "expected_peak": 2885,
        "status": "TO VERIFY"
    },
}

print("=" * 80)
print("PEAK VERIFICATION CHECKLIST - USER REPORTED vs DB ACTUAL")
print("=" * 80)
print()

for time_label, details in PEAKS_TO_VERIFY.items():
    print(f"📅 {time_label}")
    print(f"   Namespace: {details['namespace']}")
    print(f"   Expected: {details['expected_peak']}")
    if 'note' in details:
        print(f"   Note: {details['note']}")
    print(f"   Status: {details['status']}")
    print()

print("=" * 80)
print("NEXT STEP: Run verification_after_fix.py to populate 'actual_value' field")
print("=" * 80)
