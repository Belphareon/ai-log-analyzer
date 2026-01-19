#!/usr/bin/env python3
"""Test REPLACEMENT peak detection logic OFFLINE"""

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
print("TEST: REPLACEMENT Peak Detection Logic")
print("=" * 120)

db_insert = {}
peaks_log = {}

for key in sorted(data.keys()):
    day, hour, quarter, ns = key
    original_value = data[key]['mean']
    is_peak, ratio, reference = detect_peak(day, hour, quarter, ns, original_value, data)
    
    day_names = ['Mon']
    time_str = f"{day_names[day]} {hour:02d}:{quarter*15:02d}"
    
    print(f"\n  Time: {time_str} {ns:15s}")
    print(f"      Original: {original_value:.1f}")
    
    if reference is None:
        print(f"      Ref: NO REFERENCE (first windows)")
        db_insert[key] = original_value
        print(f"      INSERT to DB (no ref to compare)")
    elif is_peak:
        replacement_value = reference
        print(f"      Ref: {reference:.1f}")
        print(f"      Ratio: {ratio:.1f}x => PEAK!")
        print(f"      REPL: {original_value:.1f} => {replacement_value:.1f}")
        print(f"      LOG peak_investigation + INSERT replacement to DB")
        peaks_log[key] = {'original': original_value, 'reference': reference, 'replacement': replacement_value, 'ratio': ratio}
        db_insert[key] = replacement_value
        data[key]['mean'] = replacement_value
    else:
        print(f"      Ref: {reference:.1f}")
        print(f"      Ratio: {ratio:.1f}x => Normal")
        print(f"      INSERT to DB")
        db_insert[key] = original_value

print("\n" + "=" * 120)
print("RESULTS")
print("=" * 120)

print(f"\nInserted to peak_statistics: {len(db_insert)} rows")
for key, val in sorted(db_insert.items()):
    day, hour, quarter, ns = key
    day_names = ['Mon']
    is_replacement = key in peaks_log
    marker = "REPL" if is_replacement else "REG"
    print(f"  {marker} {day_names[day]} {hour:02d}:{quarter*15:02d} {val:10.1f}")

print(f"\nLogged to peak_investigation: {len(peaks_log)} peaks")
for key, peak in sorted(peaks_log.items()):
    day, hour, quarter, ns = key
    day_names = ['Mon']
    print(f"  {day_names[day]} {hour:02d}:{quarter*15:02d} orig={peak['original']:.1f} ref={peak['reference']:.1f} repl={peak['replacement']:.1f} ({peak['ratio']:.1f}x)")

print("\nVALIDATION:")
if (0, 6, 0, 'app-sit') in db_insert and db_insert[(0, 6, 0, 'app-sit')] == 6.0:
    print("OK: Peak slot in DB with replacement (6.0 not 8217.0)")
else:
    print("ERROR: Peak should be in DB with replacement!")

if (0, 6, 0, 'app-sit') in peaks_log:
    print("OK: Peak logged in peak_investigation")
else:
    print("ERROR: Peak should be logged!")

if len(db_insert) == 7:
    print("OK: All 7 windows in DB (no gaps)")
else:
    print(f"ERROR: Expected 7, got {len(db_insert)}")

print("=" * 120 + "\n")
