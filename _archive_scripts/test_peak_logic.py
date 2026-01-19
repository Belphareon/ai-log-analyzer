#!/usr/bin/env python3
"""Test peak detection logic OFFLINE"""

data = {
    (0, 5, 0, 'app-sit'): {'mean': 5.0, 'stddev': 0.5, 'samples': 10},
    (0, 5, 1, 'app-sit'): {'mean': 6.0, 'stddev': 0.5, 'samples': 10},
    (0, 5, 2, 'app-sit'): {'mean': 5.5, 'stddev': 0.5, 'samples': 10},
    (0, 5, 3, 'app-sit'): {'mean': 6.5, 'stddev': 0.5, 'samples': 10},
    (0, 6, 0, 'app-sit'): {'mean': 8217.0, 'stddev': 0.5, 'samples': 10},
    (0, 6, 1, 'app-sit'): {'mean': 5.0, 'stddev': 0.5, 'samples': 10},
    (0, 6, 2, 'app-sit'): {'mean': 5.5, 'stddev': 0.5, 'samples': 10},
}

PEAK_RATIO_THRESHOLD = 15.0

def detect_peak(day, hour, quarter, ns, value, all_data):
    refs = []
    for i in range(1, 4):
        total_min = hour * 60 + quarter * 15 - i * 15
        if total_min >= 0:
            prev_hour = total_min // 60
            prev_quarter = (total_min % 60) // 15
            key = (day, prev_hour, prev_quarter, ns)
            if key in all_data:
                refs.append(all_data[key]['mean'])
    
    if not refs:
        return (False, None, None)
    
    reference = sum(refs) / len(refs)
    if reference <= 0:
        reference = 1
    
    ratio = value / reference
    is_peak = ratio >= PEAK_RATIO_THRESHOLD
    
    return (is_peak, ratio, reference)

print("\n" + "=" * 120)
print("🧪 TEST: Peak Detection Logic")
print("=" * 120)

db_insert = {}
peaks_log = {}

for key in sorted(data.keys()):
    day, hour, quarter, ns = key
    original_value = data[key]['mean']
    is_peak, ratio, reference = detect_peak(day, hour, quarter, ns, original_value, data)
    
    day_names = ['Mon']
    time_str = f"{day_names[day]} {hour:02d}:{quarter*15:02d}"
    
    print(f"\n  ⏱️  {time_str} {ns:15s}")
    print(f"      Original value: {original_value:.1f}")
    
    if reference is None:
        print(f"      Reference: NO REFERENCE (first windows)")
        db_insert[key] = original_value
        print(f"      ✅ INSERT to DB (no reference to compare)")
    elif is_peak:
        print(f"      Reference: {reference:.1f}")
        print(f"      Ratio: {ratio:.1f}× → ⚠️  PEAK DETECTED!")
        print(f"      ✅ LOG to peak_investigation")
        print(f"      ✅ DO NOT insert to DB")
        print(f"      ✅ Update memory: {original_value:.1f} → {reference:.1f}")
        peaks_log[key] = {'original': original_value, 'reference': reference, 'ratio': ratio}
        data[key]['mean'] = reference
    else:
        print(f"      Reference: {reference:.1f}")
        print(f"      Ratio: {ratio:.1f}× → ✅ Normal value")
        print(f"      ✅ INSERT to DB")
        db_insert[key] = original_value

print("\n" + "=" * 120)
print("📋 RESULTS")
print("=" * 120)

print(f"\n✅ Inserted to peak_statistics: {len(db_insert)} rows")
for key, val in sorted(db_insert.items()):
    day, hour, quarter, ns = key
    day_names = ['Mon']
    print(f"    {day_names[day]} {hour:02d}:{quarter*15:02d} | {val:10.1f}")

print(f"\n🔴 Logged to peak_investigation: {len(peaks_log)} peaks")
for key, peak in sorted(peaks_log.items()):
    day, hour, quarter, ns = key
    day_names = ['Mon']
    print(f"    {day_names[day]} {hour:02d}:{quarter*15:02d} | orig={peak['original']:10.1f} → ref={peak['reference']:8.1f} ({peak['ratio']:6.1f}×)")

print("\n⚠️  VALIDATION:")
print("─" * 120)
if (0, 6, 0, 'app-sit') not in db_insert:
    print("✅ Peak value (8217.0) NOT in DB_INSERT")
else:
    print("❌ ERROR: Peak value SHOULD NOT be in DB!")

if (0, 6, 0, 'app-sit') in peaks_log:
    print("✅ Peak value IS logged in peak_investigation")
else:
    print("❌ ERROR: Peak value SHOULD be logged!")

if (0, 6, 1, 'app-sit') in db_insert and db_insert[(0, 6, 1, 'app-sit')] != 5.0:
    print(f"❌ Next window (06:15) value not updated! Still 5.0")
elif (0, 6, 1, 'app-sit') in db_insert:
    print(f"✅ Next window (06:15) kept original value (reference not auto-updated in next iteration)")

print("\n" + "=" * 120)
