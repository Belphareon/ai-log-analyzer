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
from zoneinfo import ZoneInfo


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
    namespaces: Any = None,
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
    resolved_namespaces = tuple(sorted({
        str(namespace).strip()
        for namespace in (
            namespaces
            if namespaces is not None
            else (key[0] for key in data)
        )
        if str(namespace).strip()
    }))
    from core.namespace_contract import namespace_contract_hash

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
            'monitored_namespaces': list(resolved_namespaces),
            'namespace_contract_hash': namespace_contract_hash(resolved_namespaces),
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
    from core.calculate_peak_thresholds import fetch_raw_data, load_monitored_namespaces
    from regular_phase import get_db_connection

    if weeks <= 0:
        raise ValueError('threshold weeks must be positive')
    percentile_level = float(os.getenv('PERCENTILE_LEVEL', '0.93'))
    monitored_namespaces = load_monitored_namespaces()
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
        monitored_namespaces,
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
    episode_ids = set()
    episode_states: Dict[str, int] = {}
    policy_outcomes: Dict[str, int] = {}
    delivery_outcomes: Dict[str, int] = {}
    for result in window_results:
        status = str(result.get('status') or 'missing')
        statuses[status] = statuses.get(status, 0) + 1
        episode_ids.update(
            str(episode.get('episode_id'))
            for episode in (result.get('peak_episodes') or ())
            if episode.get('episode_id')
        )
        for transition in result.get('peak_episode_transitions') or ():
            state = str(transition.get('state') or 'unknown')
            episode_states[state] = episode_states.get(state, 0) + 1
        for decision in result.get('notification_decisions') or ():
            outcome = str(decision.get('policy_outcome') or 'unknown')
            policy_outcomes[outcome] = policy_outcomes.get(outcome, 0) + 1
        for delivery in result.get('delivery_outcomes') or ():
            outcome = str(delivery.get('status') or 'unknown')
            delivery_outcomes[outcome] = delivery_outcomes.get(outcome, 0) + 1
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
        'episode_count': len(episode_ids),
        'episode_states': episode_states,
        'policy_outcomes': policy_outcomes,
        'delivery_outcomes': delivery_outcomes,
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


def _fixture_window_decisions(
    window: Dict[str, Any],
    namespaces: List[str],
    *,
    stream_key: str,
    contract_hash: str,
) -> List[Dict[str, Any]]:
    """Materialize one dense 12-namespace window from sanitized fixture rows."""
    from core.peak_decision import materialize_namespace_decisions

    window_start = parse_utc(str(window['window_start_utc']))
    audits = []
    for source in window.get('decisions') or ():
        audit = dict(source)
        audit['window_start'] = window_start.isoformat()
        audit['namespace'] = str(audit.get('namespace') or '').strip()
        audit['namespace_total'] = int(audit.get('namespace_total') or 0)
        audit['is_namespace_peak'] = bool(audit.get('is_peak', audit.get('is_namespace_peak', False)))
        audit['family_decisions'] = list(audit.get('family_decisions') or ())
        audits.append(audit)

    decisions = materialize_namespace_decisions(
        audits,
        namespaces,
        window_start=window_start,
        stream_key=stream_key,
        contract_hash=contract_hash,
        run_id='fixture-replay',
    )
    metadata_by_namespace = {
        str(source.get('namespace') or ''): source
        for source in window.get('decisions') or ()
    }
    rows = []
    for decision in decisions:
        row = decision.to_dict()
        source = metadata_by_namespace.get(decision.signal_namespace, {})
        row['candidate_id'] = str(source.get('candidate_id') or window.get('candidate_id') or '')
        row['cause_families'] = list(source.get('cause_families') or ())
        row['test_origin_label'] = str(
            source.get('test_origin_label')
            or window.get('test_origin_label')
            or ''
        )
        rows.append(row)
    return rows


def evaluate_peak_candidate_fixture(fixture: Dict[str, Any]) -> Dict[str, Any]:
    """Replay sanitized candidate windows through decisions, episodes, and policy."""
    from core.namespace_contract import namespace_contract_hash
    from core.notification_policy import decide_notification_candidates, decision_summary
    from core.peak_episode import PeakEpisodeCorrelator, observations_from_decisions

    namespaces = [str(value) for value in fixture.get('namespaces') or ()]
    if not namespaces:
        raise ValueError('fixture must define monitored namespaces')
    stream_key = str(fixture.get('stream_key') or 'fixture-replay')
    contract_hash = namespace_contract_hash(namespaces)
    decision_rows = [
        row
        for window in fixture.get('windows') or ()
        for row in _fixture_window_decisions(
            window,
            namespaces,
            stream_key=stream_key,
            contract_hash=contract_hash,
        )
    ]
    observations = observations_from_decisions(decision_rows)
    correlator = PeakEpisodeCorrelator(
        resolve_non_peak_windows=int(fixture.get('resolve_non_peak_windows', 2)),
    )
    episodes = correlator.correlate(observations)
    transitions = tuple(correlator.last_transitions)
    transitions_by_decision: Dict[str, List[Dict[str, Any]]] = {}
    for transition in transitions:
        transitions_by_decision.setdefault(
            transition.window_decision_id, []
        ).append(transition.to_dict())

    observations_by_decision: Dict[str, List[Any]] = {}
    for observation in observations:
        observations_by_decision.setdefault(
            observation.window_decision_id, []
        ).append(observation)

    policy_candidates = []
    decision_reports = []
    for row in decision_rows:
        row_transitions = transitions_by_decision.get(row['window_decision_id'], [])
        transition_by_state = [
            transition
            for transition in row_transitions
            if transition.get('state') in {
                'START', 'RECURRENCE', 'CONTINUATION', 'EXPANSION', 'ESCALATION',
            }
        ]
        decision_report = {
            'candidate_id': row.get('candidate_id') or None,
            'window_decision_id': row['window_decision_id'],
            'signal_namespace': row['signal_namespace'],
            'window_start_utc': row['window_start_utc'],
            'window_display_prague': (
                parse_utc(row['window_start_utc']).astimezone(
                    ZoneInfo('Europe/Prague')
                ).isoformat()
            ),
            'namespace_raw_lines': row['namespace_raw_lines'],
            'is_peak': row['is_peak'],
            'verdict_reason': row['verdict_reason'],
            'diagnosis_status': row['diagnosis_status'],
            'episode_transitions': row_transitions,
            'episode_ids': sorted({
                str(transition.get('episode_id'))
                for transition in row_transitions
                if transition.get('episode_id')
            }),
            'policy_outcomes': [],
        }
        for transition in transition_by_state:
            observation = next(
                (
                    candidate
                    for candidate in observations_by_decision.get(
                        row['window_decision_id'], []
                    )
                    if candidate.normalized_cause_signature() == transition['cause_signature']
                ),
                None,
            )
            cause_family = next(
                (
                    family
                    for family in (row.get('cause_families') or ())
                    if family.get('signature') == transition['cause_signature']
                ),
                {},
            )
            policy_candidates.append({
                'episode_id': transition['episode_id'],
                'window_decision_id': row['window_decision_id'],
                'stream_key': stream_key,
                'episode_state': transition['state'],
                'assessment': (observation.assessment if observation else 'unknown'),
                'confidence': (observation.confidence if observation else 'low'),
                'namespace_ratio': (
                    row['namespace_raw_lines'] / float(row['effective_threshold'])
                    if row.get('effective_threshold')
                    else 0
                ),
                'unique_operation_occurrences': (
                    observation.unique_operation_occurrences if observation else
                    cause_family.get('unique_operations')
                ),
                'material_change_reasons': transition.get('material_change_reasons') or [],
                'test_originator_application': row.get('test_origin_label') or '',
            })
        decision_reports.append(decision_report)

    policy_decisions = decide_notification_candidates(
        policy_candidates,
        detail_limit=int(fixture.get('detail_limit', 3)),
    )
    policies_by_window = {}
    deliveries_by_window = {}
    fixture_delivery_outcomes = []
    for decision in policy_decisions:
        policy_report = decision.to_dict()
        policies_by_window.setdefault(decision.window_decision_id, []).append(policy_report)
        delivery_report = {
            'notification_decision_id': decision.notification_decision_id,
            'destination': decision.destination,
            'status': 'not_attempted',
            'provider_message': 'fixture_replay',
            'policy_outcome': decision.policy_outcome,
            'test_origin_label': decision.test_origin_label,
        }
        deliveries_by_window.setdefault(decision.window_decision_id, []).append(
            delivery_report
        )
        fixture_delivery_outcomes.append(delivery_report)
    for decision_report in decision_reports:
        decision_report['policy_outcomes'] = policies_by_window.get(
            decision_report['window_decision_id'], []
        )
        decision_report['delivery_outcomes'] = deliveries_by_window.get(
            decision_report['window_decision_id'], []
        )

    candidate_reports: Dict[str, Dict[str, Any]] = {}
    for decision_report in decision_reports:
        candidate_id = decision_report.get('candidate_id')
        if not candidate_id:
            continue
        report = candidate_reports.setdefault(candidate_id, {
            'candidate_id': candidate_id,
            'window_starts_utc': [],
            'namespace_timelines': {},
            'decisions': [],
            'episode_states': [],
            'policy_outcomes': [],
            'delivery_outcomes': [],
        })
        window_start = decision_report['window_start_utc']
        if window_start not in report['window_starts_utc']:
            report['window_starts_utc'].append(window_start)
        namespace = decision_report['signal_namespace']
        report['namespace_timelines'].setdefault(namespace, []).append({
            'window_start_utc': window_start,
            'namespace_raw_lines': decision_report['namespace_raw_lines'],
            'is_peak': decision_report['is_peak'],
            'verdict_reason': decision_report['verdict_reason'],
        })
        report['decisions'].append(decision_report)
        report['episode_states'].extend(
            transition.get('state')
            for transition in decision_report['episode_transitions']
            if transition.get('state')
        )
        report['policy_outcomes'].extend(decision_report['policy_outcomes'])
        report['delivery_outcomes'].extend(decision_report['delivery_outcomes'])

    for report in candidate_reports.values():
        report['window_starts_utc'].sort()
        report['episode_states'].sort()
        report['policy_outcome_counts'] = decision_summary(
            type('DecisionView', (), {'policy_outcome': outcome['policy_outcome']})()
            for outcome in report['policy_outcomes']
        )
        report['delivery_outcome_counts'] = {
            status: sum(
                1 for outcome in report['delivery_outcomes']
                if outcome.get('status') == status
            )
            for status in ('not_attempted', 'delivered', 'failed')
        }

    return {
        'status': 'complete',
        'fixture_id': fixture.get('fixture_id', 'peak-candidate-fixture'),
        'stream_key': stream_key,
        'contract_hash': contract_hash,
        'namespaces': namespaces,
        'summary': {
            'evaluated_namespaces': len(namespaces),
            'decision_rows': len(decision_rows),
            'peak_decisions': sum(1 for row in decision_rows if row['is_peak']),
            'non_peak_decisions': sum(1 for row in decision_rows if not row['is_peak']),
            'episodes': len(episodes),
            'transitions': len(transitions),
            'policy': decision_summary(policy_decisions),
        },
        'candidates': candidate_reports,
        'decisions': decision_reports,
        'episodes': [episode.to_dict() for episode in episodes],
        'transitions': [transition.to_dict() for transition in transitions],
        'delivery_outcomes': fixture_delivery_outcomes,
    }


def validate_peak_candidate_oracle(
    report: Dict[str, Any],
    fixture: Dict[str, Any],
) -> List[str]:
    """Return release-blocking oracle violations for candidate fixture output."""
    errors = []
    candidates = report.get('candidates') or {}
    for expected in fixture.get('candidate_oracle') or ():
        candidate_id = str(expected.get('candidate_id') or '')
        candidate = candidates.get(candidate_id)
        if candidate is None:
            errors.append(f'candidate {candidate_id} has no replay report')
            continue
        decisions = candidate.get('decisions') or []
        if expected.get('requires_peak') and not any(
            decision.get('is_peak') for decision in decisions
        ):
            errors.append(f'candidate {candidate_id} has no peak decision')
        if expected.get('requires_audit') and not decisions:
            errors.append(f'candidate {candidate_id} has no audit decision')
        for namespace, expected_values in (expected.get('namespace_timelines') or {}).items():
            actual_values = [
                int(item.get('namespace_raw_lines') or 0)
                for item in (candidate.get('namespace_timelines') or {}).get(namespace, [])
            ]
            for value in expected_values:
                if int(value) not in actual_values:
                    errors.append(
                        f'candidate {candidate_id} missing {namespace} value {value}'
                    )
        required_states = set(expected.get('required_states') or ())
        if not required_states.issubset(set(candidate.get('episode_states') or ())):
            errors.append(
                f'candidate {candidate_id} missing states '
                f'{sorted(required_states - set(candidate.get("episode_states") or ()))}'
            )
        if expected.get('requires_test_origin_label'):
            labels = {
                str(outcome.get('test_origin_label') or '')
                for outcome in candidate.get('policy_outcomes') or ()
            }
            if expected['requires_test_origin_label'] not in labels:
                errors.append(
                    f'candidate {candidate_id} missing test-origin label '
                    f'{expected["requires_test_origin_label"]}'
                )
    return errors


def load_and_validate_peak_candidate_fixture(path: Path) -> Dict[str, Any]:
    fixture = json.loads(path.read_text(encoding='utf-8'))
    report = evaluate_peak_candidate_fixture(fixture)
    errors = validate_peak_candidate_oracle(report, fixture)
    if errors:
        raise ValueError('peak candidate oracle failed: ' + '; '.join(errors))
    report['oracle'] = {'status': 'passed', 'errors': []}
    return report


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
        prior_episodes_path = temp_dir / 'prior-episodes.json'
        prior_episodes_path.write_text('[]', encoding='utf-8')
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
                '--replay-evaluate-policy',
                '--replay-window-end',
                window_end.isoformat(),
                '--result-json',
                str(result_path),
                '--replay-thresholds-json',
                str(threshold_bundle_path),
                '--replay-prior-episodes-json',
                str(prior_episodes_path),
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
            prior_episodes_path.write_text(
                json.dumps(result.get('peak_episodes') or [], ensure_ascii=False),
                encoding='utf-8',
            )
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


def run_threshold_sensitivity(
    period_end: datetime,
    replay_days: tuple[int, ...] = (7, 14, 28),
) -> Dict[str, Any]:
    """Run complete-fact replays at the required threshold training horizons."""
    if not replay_days or any(days <= 0 or days % 7 for days in replay_days):
        raise ValueError('replay_days must contain positive whole weeks')
    runs = []
    for days in replay_days:
        replay_report = run_replay(
            period_end,
            hours=days * 24,
            threshold_weeks=days // 7,
        )
        runs.append({
            'days': days,
            'status': replay_report['status'],
            'period_start': replay_report['period_start'],
            'period_end': replay_report['period_end'],
            'threshold_bundle': replay_report['threshold_bundle'],
            'summary': replay_report['summary'],
            'failures': replay_report['failures'],
        })
    status = 'complete' if all(run['status'] == 'complete' for run in runs) else 'incomplete'
    return {
        'status': status,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'period_end': period_end.astimezone(timezone.utc).isoformat(),
        'replays': runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Read-only DB-backed historical peak replay')
    parser.add_argument('--hours', type=int, default=48)
    parser.add_argument('--end', type=parse_utc)
    parser.add_argument('--threshold-weeks', type=int, default=DEFAULT_THRESHOLD_WEEKS)
    parser.add_argument(
        '--threshold-sensitivity',
        action='store_true',
        help='run complete-fact 7, 14, and 28 day threshold sensitivity replays',
    )
    parser.add_argument(
        '--candidate-fixture',
        type=Path,
        help='evaluate a sanitized candidate fixture without connecting to PostgreSQL',
    )
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    if args.candidate_fixture and args.threshold_sensitivity:
        parser.error('--candidate-fixture and --threshold-sensitivity are mutually exclusive')
    if args.candidate_fixture:
        report = load_and_validate_peak_candidate_fixture(args.candidate_fixture)
    elif args.threshold_sensitivity:
        period_end = args.end or aligned_window_end(datetime.now(timezone.utc))
        report = run_threshold_sensitivity(period_end)
    else:
        period_end = args.end or aligned_window_end(datetime.now(timezone.utc))
        report = run_replay(period_end, args.hours, args.threshold_weeks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding='utf-8',
    )
    console_summary = report.get('summary')
    if console_summary is None:
        console_summary = {
            'replays': report.get('replays') or [],
        }
    print(json.dumps({
        'status': report['status'],
        'summary': console_summary,
        **({
            'period_start': report['period_start'],
            'period_end': report['period_end'],
        } if 'period_start' in report else {}),
    }, indent=2, ensure_ascii=False))
    return 0 if report['status'] == 'complete' else 1


if __name__ == '__main__':
    sys.exit(main())