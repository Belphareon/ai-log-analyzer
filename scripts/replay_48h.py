#!/usr/bin/env python3
"""Run isolated read-only regular-phase replays and aggregate detector evidence."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_THRESHOLD_WEEKS = 4


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError('timestamp must include a UTC offset or Z suffix')
    return parsed.astimezone(timezone.utc)


def aligned_window_end(now: datetime) -> datetime:
    utc_now = now.astimezone(timezone.utc)
    quarter = (utc_now.minute // 15) * 15
    return utc_now.replace(minute=quarter, second=0, microsecond=0)


def replay_window_ends(period_end: datetime, hours: int) -> List[datetime]:
    if hours <= 0 or hours * 60 % 15:
        raise ValueError('hours must describe a positive whole number of 15-minute windows')
    window_count = hours * 4
    period_start = period_end - timedelta(hours=hours)
    return [
        period_start + timedelta(minutes=15 * (index + 1))
        for index in range(window_count)
    ]


def _serialize_threshold_bundle(
    data: Dict[Any, List[float]],
    date_range: Dict[str, Any],
    training_cutoff: datetime,
    weeks: int,
    percentile_level: float,
) -> Dict[str, Any]:
    from core.calculate_peak_thresholds import (
        CALCULATION_VERSION,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
        calculate_cap_values,
        calculate_p93_thresholds,
    )

    thresholds = calculate_p93_thresholds(data, percentile_level)
    caps = calculate_cap_values(thresholds)
    if not thresholds or not caps:
        raise RuntimeError('no read-only replay thresholds could be calculated')
    bundle_id = (
        f'replay-memory-v{CALCULATION_VERSION}-asof-'
        f'{training_cutoff.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}'
    )
    return {
        'bundle_id': bundle_id,
        'metadata': {
            'percentile_level': percentile_level,
            'population_grain': POPULATION_GRAIN,
            'percentile_method': PERCENTILE_METHOD,
            'calculation_version': CALCULATION_VERSION,
            'training_weeks': weeks,
            'training_cutoff': training_cutoff.astimezone(timezone.utc).isoformat(),
            'training_start': (
                date_range['min'].isoformat() if date_range.get('min') else None
            ),
            'training_last_fact': (
                date_range['max'].isoformat() if date_range.get('max') else None
            ),
            'source': 'ailog_peak.v_complete_namespace_error_counts',
            'persistence': 'none',
        },
        'thresholds': [
            {
                'namespace': namespace,
                'day_of_week': day_of_week,
                'value': stats['p93'],
                'samples': stats['count'],
            }
            for (namespace, day_of_week), stats in sorted(thresholds.items())
        ],
        'caps': {
            namespace: {
                'value': stats['cap'],
                'samples': stats['total_samples'],
            }
            for namespace, stats in sorted(caps.items())
        },
    }


def build_replay_threshold_bundle(
    training_cutoff: datetime,
    weeks: int = DEFAULT_THRESHOLD_WEEKS,
) -> Dict[str, Any]:
    from core.calculate_peak_thresholds import fetch_raw_data
    from regular_phase import get_db_connection

    if weeks <= 0:
        raise ValueError('threshold weeks must be positive')
    percentile_level = float(os.getenv('PERCENTILE_LEVEL', '0.93'))
    connection = get_db_connection(read_only=True)
    try:
        connection.set_session(readonly=True, autocommit=True)
        data, date_range = fetch_raw_data(
            connection,
            weeks=weeks,
            as_of=training_cutoff,
        )
    finally:
        connection.close()
    return _serialize_threshold_bundle(
        data,
        date_range,
        training_cutoff,
        weeks,
        percentile_level,
    )


def compact_peak_example(audit: Dict[str, Any]) -> Dict[str, Any]:
    owner_fingerprint = audit.get('owner_fingerprint')
    decisions = audit.get('family_decisions', [])
    owner = next(
        (
            decision
            for decision in decisions
            if decision.get('fingerprint') == owner_fingerprint
        ),
        None,
    )
    top_families = []
    for decision in decisions[:3]:
        top_families.append({
            'fingerprint': decision.get('fingerprint'),
            'error_type': decision.get('error_type'),
            'normalized_message': decision.get('normalized_message'),
            'apps': decision.get('apps', []),
            'contribution': decision.get('contribution'),
            'threshold': decision.get('threshold'),
            'baseline': decision.get('baseline'),
            'anomaly_score': decision.get('anomaly_score'),
            'method': decision.get('method'),
            'is_anomalous': decision.get('is_anomalous'),
        })
    return {
        'window_start': audit.get('window_start'),
        'namespace': audit.get('namespace'),
        'namespace_total': audit.get('namespace_total'),
        'percentile_level': audit.get('percentile_level'),
        'percentile_threshold': audit.get('percentile_threshold'),
        'cap_threshold': audit.get('cap_threshold'),
        'triggered_by': audit.get('triggered_by'),
        'threshold_snapshot_id': audit.get('threshold_snapshot_id'),
        'owner_fingerprint': owner_fingerprint,
        'owner': owner,
        'suppressed_reason': audit.get('suppressed_reason'),
        'top_families': top_families,
    }


def summarize(window_results: List[Dict[str, Any]], hours: int) -> Dict[str, Any]:
    audits = [
        audit
        for result in window_results
        for audit in result.get('namespace_peak_audit', [])
    ]
    volume_peaks = [audit for audit in audits if audit.get('is_namespace_peak')]
    attributed = [audit for audit in volume_peaks if audit.get('owner_fingerprint')]
    suppressed = [audit for audit in volume_peaks if not audit.get('owner_fingerprint')]
    statuses: Dict[str, int] = {}
    suppression_reasons: Dict[str, int] = {}
    for result in window_results:
        status = str(result.get('status') or 'missing')
        statuses[status] = statuses.get(status, 0) + 1
    for audit in suppressed:
        reason = str(audit.get('suppressed_reason') or 'unknown')
        suppression_reasons[reason] = suppression_reasons.get(reason, 0) + 1

    return {
        'requested_hours': hours,
        'expected_windows': hours * 4,
        'completed_windows': len(window_results),
        'statuses': statuses,
        'complete_fetch_windows': sum(
            1 for result in window_results if result.get('fetch_complete')
        ),
        'expected_errors': sum(
            int(result.get('expected_count') or 0) for result in window_results
        ),
        'fetched_errors': sum(
            int(result.get('fetched_count') or 0) for result in window_results
        ),
        'namespace_window_evaluations': len(audits),
        'namespace_volume_peaks': len(volume_peaks),
        'attributed_peaks': len(attributed),
        'suppressed_volume_peaks': len(suppressed),
        'suppression_reasons': suppression_reasons,
        'threshold_snapshot_ids': sorted({
            str(audit['threshold_snapshot_id'])
            for audit in audits
            if audit.get('threshold_snapshot_id')
        }),
        'family_baseline_unavailable_windows': sum(
            1
            for result in window_results
            if result.get('status') == 'success'
            and not result.get('family_baseline_available', False)
        ),
        'top_attributed_peaks': [
            compact_peak_example(audit)
            for audit in sorted(
                attributed,
                key=lambda item: -int(item.get('namespace_total') or 0),
            )[:10]
        ],
        'top_suppressed_volume_peaks': [
            compact_peak_example(audit)
            for audit in sorted(
                suppressed,
                key=lambda item: -int(item.get('namespace_total') or 0),
            )[:10]
        ],
    }


def run_replay(
    period_end: datetime,
    hours: int,
    threshold_weeks: int = DEFAULT_THRESHOLD_WEEKS,
) -> Dict[str, Any]:
    window_results = []
    failures = []
    ends = replay_window_ends(period_end, hours)
    period_start = period_end - timedelta(hours=hours)
    with tempfile.TemporaryDirectory(prefix='peak-replay-') as temporary_directory:
        temp_dir = Path(temporary_directory)
        threshold_bundle = build_replay_threshold_bundle(
            period_start,
            weeks=threshold_weeks,
        )
        threshold_bundle_path = temp_dir / 'threshold-bundle.json'
        threshold_bundle_path.write_text(
            json.dumps(threshold_bundle, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )
        for index, window_end in enumerate(ends, start=1):
            result_path = temp_dir / f'window-{index:03d}.json'
            command = [
                sys.executable,
                str(SCRIPT_DIR / 'regular_phase.py'),
                '--window',
                '15',
                '--dry-run',
                '--audit-only',
                '--replay-window-end',
                window_end.isoformat(),
                '--result-json',
                str(result_path),
                '--replay-thresholds-json',
                str(threshold_bundle_path),
            ]
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if not result_path.exists():
                failures.append({
                    'window_end': window_end.isoformat(),
                    'returncode': completed.returncode,
                    'output': completed.stdout[-4000:],
                })
                print(f'[{index}/{len(ends)}] ERROR {window_end.isoformat()}', flush=True)
                break
            result = json.loads(result_path.read_text(encoding='utf-8'))
            result['returncode'] = completed.returncode
            window_results.append(result)
            print(
                f"[{index}/{len(ends)}] {result['status']} "
                f"errors={result.get('fetched_count', 0)} "
                f"namespace_peaks={sum(1 for audit in result.get('namespace_peak_audit', []) if audit.get('is_namespace_peak'))}",
                flush=True,
            )
            if completed.returncode != 0 or result.get('status') == 'error':
                failures.append({
                    'window_end': window_end.isoformat(),
                    'returncode': completed.returncode,
                    'output': completed.stdout[-4000:],
                    'result': result,
                })
                break

    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'threshold_bundle': {
            'bundle_id': threshold_bundle['bundle_id'],
            **threshold_bundle['metadata'],
            'threshold_rows': len(threshold_bundle['thresholds']),
            'cap_rows': len(threshold_bundle['caps']),
        },
        'summary': summarize(window_results, hours),
        'failures': failures,
        'windows': window_results,
    }
    if failures or len(window_results) != hours * 4:
        report['status'] = 'incomplete'
    elif any(result.get('status') == 'error' for result in window_results):
        report['status'] = 'failed'
    elif report['summary']['complete_fetch_windows'] != hours * 4:
        report['status'] = 'incomplete'
    else:
        report['status'] = 'complete'
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only DB-backed historical peak replay')
    parser.add_argument('--hours', type=int, default=48)
    parser.add_argument('--end', type=parse_utc)
    parser.add_argument('--threshold-weeks', type=int, default=DEFAULT_THRESHOLD_WEEKS)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    period_end = args.end or aligned_window_end(datetime.now(timezone.utc))
    report = run_replay(period_end, args.hours, args.threshold_weeks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    print(json.dumps({
        'status': report['status'],
        'period_start': report['period_start'],
        'period_end': report['period_end'],
        'summary': report['summary'],
    }, indent=2, ensure_ascii=False))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    sys.exit(main())