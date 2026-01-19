#!/usr/bin/env python3
"""
Test peak detection logic: can we fix Fri 08:15?

Problem:
  Fri 08:00 = 13154 (PEAK - should be skipped)
  Fri 08:15 = 40856 (uses 08:00 as reference, so ratio = 40856/13154 = 3.1, no peak detected)

Solution:
  Ignore peaks in reference windows (2-pass approach)
"""

# Simulated data from peak_fixed file
data = {
    (4, 6, 0, "pcb-dev-01-app"): {"mean": 7.0},    # Fri 06:00
    (4, 6, 1, "pcb-dev-01-app"): {"mean": 19.0},   # Fri 06:15
    (4, 6, 2, "pcb-dev-01-app"): {"mean": 21.0},   # Fri 06:30
    (4, 6, 3, "pcb-dev-01-app"): {"mean": 1.0},    # Fri 06:45
    (4, 7, 0, "pcb-dev-01-app"): {"mean": 33.0},   # Fri 07:00
    (4, 7, 1, "pcb-dev-01-app"): {"mean": 7.0},    # Fri 07:15
    (4, 7, 2, "pcb-dev-01-app"): {"mean": 19.0},   # Fri 07:30
    (4, 7, 3, "pcb-dev-01-app"): {"mean": 21.0},   # Fri 07:45
    (4, 8, 0, "pcb-dev-01-app"): {"mean": 13154.0},  # Fri 08:00 <- PEAK!
    (4, 8, 1, "pcb-dev-01-app"): {"mean": 40856.0},  # Fri 08:15 <- should this be peak?
}

PEAK_THRESHOLD = 35.0
WINDOW_MINUTES = [15, 30, 45, 60, 75, 90]

def detect_peak(day, hour, qtr, ns, mean_val, all_data, peaks_to_skip=None):
    """Detect if value is peak"""
    if peaks_to_skip is None:
        peaks_to_skip = set()
    
    refs = []
    for min_back in WINDOW_MINUTES:
        total_min = hour * 60 + qtr * 15 - min_back
        if total_min >= 0:
            ref_hour = total_min // 60
            ref_qtr = (total_min % 60) // 15
            key = (day, ref_hour, ref_qtr, ns)
            
            # IGNORE peaks
            if key in all_data and key not in peaks_to_skip:
                refs.append(all_data[key]['mean'])
    
    if not refs:
        return False
    
    ref = sum(refs) / len(refs)
    if ref < 5:
        ref = 5
    
    ratio = mean_val / ref
    return ratio >= PEAK_THRESHOLD

print("="*60)
print("SCENARIO 1: WITHOUT 2-PASS (current buggy behavior)")
print("="*60)

peaks_s1 = {}
for key, stats in sorted(data.items()):
    is_peak = detect_peak(*key, stats['mean'], data)
    peaks_s1[key] = is_peak
    day, hour, qtr, ns = key
    marker = "PEAK" if is_peak else "OK"
    print(f"{['Mon','Tue','Wed','Thu','Fri'][day]} {hour:02d}:{qtr*15:02d} = {stats['mean']:6.0f} [{marker}]")

print(f"\nFri 08:00 is peak? {peaks_s1[(4, 8, 0, 'pcb-dev-01-app')]}")
print(f"Fri 08:15 is peak? {peaks_s1[(4, 8, 1, 'pcb-dev-01-app')]}")

print("\n" + "="*60)
print("SCENARIO 2: WITH 2-PASS (proposed fix)")
print("="*60)

# PASS 1: Find peaks
peaks_to_skip = set()
for key, stats in data.items():
    is_peak = detect_peak(*key, stats['mean'], data)
    if is_peak:
        peaks_to_skip.add(key)

print(f"PASS 1: Found {len(peaks_to_skip)} peaks: {peaks_to_skip}")

# PASS 2: Detect again, now ignoring peaks in references
peaks_s2 = {}
for key, stats in sorted(data.items()):
    is_peak = detect_peak(*key, stats['mean'], data, peaks_to_skip)
    peaks_s2[key] = is_peak
    day, hour, qtr, ns = key
    marker = "PEAK" if is_peak else "OK"
    marker_info = " (was reference!)" if key in peaks_to_skip else ""
    print(f"{['Mon','Tue','Wed','Thu','Fri'][day]} {hour:02d}:{qtr*15:02d} = {stats['mean']:6.0f} [{marker}]{marker_info}")

print(f"\nFri 08:00 is peak? {peaks_s2[(4, 8, 0, 'pcb-dev-01-app')]}")
print(f"Fri 08:15 is peak? {peaks_s2[(4, 8, 1, 'pcb-dev-01-app')]}")

print("\n" + "="*60)
print("ANALYSIS")
print("="*60)

if not peaks_s2[(4, 8, 1, 'pcb-dev-01-app')] and peaks_s2[(4, 8, 0, 'pcb-dev-01-app')]:
    print("✅ FIX WORKS! Both peaks are now detected correctly!")
else:
    print("❌ Fix didn't work - still have issues")

