from datetime import datetime
from types import SimpleNamespace

from pipeline.phase_c_detect import PhaseC_Detect
from pipeline.phase_b_measure import MeasurementResult

class FakeDetector:
    def __init__(self, thresholds):
        self.thresholds = thresholds

    def is_peak(self, value, namespace, day_of_week):
        p, c = self.thresholds.get(namespace, (9999, 9999))
        return {
            'is_peak': value > p or value > c,
            'value': value,
            'p93_threshold': float(p),
            'cap_threshold': float(c),
            'triggered_by': 'p93' if value > p else ('cap' if value > c else None),
            'namespace': namespace,
            'day_of_week': day_of_week,
        }

# Same namespace, two fingerprints
# fp-A has 600 events in ns -> should spike
# fp-B has 17 events in same ns -> should NOT spike
records = []
base = datetime(2026, 3, 3, 10, 0, 0)
for i in range(600):
    records.append(SimpleNamespace(fingerprint='fp-A', timestamp=base, namespace='pcb-dev-01-app', app_name='app-a', error_type='E1', normalized_message='m1'))
for i in range(17):
    records.append(SimpleNamespace(fingerprint='fp-B', timestamp=base, namespace='pcb-dev-01-app', app_name='app-b', error_type='E2', normalized_message='m2'))

measurements = {
    'fp-A': MeasurementResult(fingerprint='fp-A', current_count=600, namespaces=['pcb-dev-01-app'], active_windows=1, total_count=600),
    'fp-B': MeasurementResult(fingerprint='fp-B', current_count=17, namespaces=['pcb-dev-01-app'], active_windows=1, total_count=17),
}

phase = PhaseC_Detect(peak_detector=FakeDetector({'pcb-dev-01-app': (579, 852)}), min_namespace_peak_value=1)
results = phase.detect_batch(measurements, records)

print('fp-A spike=', results['fp-A'].flags.is_spike)
print('fp-B spike=', results['fp-B'].flags.is_spike)
for fp in ['fp-A', 'fp-B']:
    for ev in results[fp].evidence:
        if ev.rule == 'spike_p93_cap':
            print(fp, ev.message)
