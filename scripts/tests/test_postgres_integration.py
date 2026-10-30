import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip('psycopg2')
from psycopg2.extras import execute_values

from scripts.core import run_db_migrations
from scripts.core.run_data_maintenance import run_maintenance
from scripts.core.run_persistence import persist_analysis_run
from scripts.core.delivery_persistence import persist_notification_decisions, persist_notification_deliveries
from scripts.core.notification_policy import decide_notification_candidates
from scripts.core.peak_decision import materialize_namespace_decisions
from scripts.core.peak_episode import materialize_episode_state
from scripts.pipeline.incident import Incident


TEST_POSTGRES_DSN = os.getenv('TEST_POSTGRES_DSN', '').strip()
pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_DSN,
    reason='TEST_POSTGRES_DSN is required for PostgreSQL integration tests',
)


def _connect():
    return psycopg2.connect(TEST_POSTGRES_DSN)


@pytest.fixture(scope='module', autouse=True)
def migrated_database():
    if not TEST_POSTGRES_DSN:
        yield
        return

    connection = _connect()
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database(), current_user')
        database_name, database_user = cursor.fetchone()
        if not any(marker in database_name.lower() for marker in ('test', 'migration')):
            pytest.fail(
                'TEST_POSTGRES_DSN must target a database containing "test" '
                'or "migration" in its name'
            )
        cursor.execute('DROP SCHEMA IF EXISTS ailog_peak CASCADE')
    connection.close()

    connection = _connect()
    with connection.cursor() as cursor:
        for migration_file in sorted(run_db_migrations.MIGRATIONS_DIR.glob('[0-9]*.sql')):
            statements = run_db_migrations.split_sql_statements(
                migration_file.read_text(encoding='utf-8')
            )
            for statement in statements:
                if not run_db_migrations.is_effectively_empty(statement):
                    cursor.execute(statement)
    connection.commit()
    connection.close()

    original_connect = run_db_migrations.connect
    original_app_role = os.environ.get('DB_APP_ROLE')
    original_ddl_role = os.environ.get('DB_DDL_ROLE')
    run_db_migrations.connect = _connect
    os.environ['DB_APP_ROLE'] = database_user
    os.environ.pop('DB_DDL_ROLE', None)
    try:
        run_db_migrations.run_migrations()
        run_db_migrations.run_migrations()
        yield
    finally:
        run_db_migrations.connect = original_connect
        if original_app_role is None:
            os.environ.pop('DB_APP_ROLE', None)
        else:
            os.environ['DB_APP_ROLE'] = original_app_role
        if original_ddl_role is None:
            os.environ.pop('DB_DDL_ROLE', None)
        else:
            os.environ['DB_DDL_ROLE'] = original_ddl_role

        connection = _connect()
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA IF EXISTS ailog_peak CASCADE')
        connection.close()


@pytest.mark.parametrize('stale', [False, True])
def test_runtime_bootstrap_preserves_knowledge_and_delivered_cooldowns(stale, tmp_path):
    import json
    from core.problem_registry import ProblemEntry, PeakEntry, ProblemRegistry
    from core.regular_schedule import sync_report_knowledge
    from core.runtime_state import RuntimeStateStore, bootstrap_runtime_state
    from scripts.core.run_persistence import build_query_hash

    window = datetime(2026, 10, 30, 8, 15, tzinfo=timezone.utc)
    source = f'runtime-bootstrap-{stale}-*'
    query_hash = build_query_hash(source, ['ns-a'])
    run_id = f'runtime-bootstrap-{stale}'
    persist_analysis_run(
        connection_factory=_connect, collection=_collection(run_id, window, [('known-fp', 'cards', 10)]),
        run_type='regular', window_start=window, window_end=window + timedelta(minutes=15),
        monitored_namespaces=['ns-a'], expected_count=10, fetched_count=10, source_index=source,
    )
    problem = ProblemEntry(id='KP-000042', problem_key='db:cards:timeout', category='db', flow='cards', error_class='timeout')
    problem.fingerprints = ['known-fp']
    problem.occurrences = 123
    peak = PeakEntry(id='PK-000007', problem_key='db:cards:SPIKE', peak_type='SPIKE')
    registry = SimpleNamespace(problems={problem.problem_key: problem}, peaks={peak.problem_key: peak})
    connection = _connect()
    sync_report_knowledge(connection, source, ['ns-a'], registry)
    if stale:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE ailog_peak.report_knowledge SET updated_at = NOW() - INTERVAL '1 day' WHERE query_hash = %s", (query_hash,))
        connection.commit()
    connection.close()
    sent_at = datetime.now(timezone.utc)
    persist_notification_deliveries(_connect, [{
        'dedup_key': 'already-delivered', 'destination': 'email', 'status': 'delivered',
        'attempted_at': sent_at, 'metadata': {
            'alert_identity': 'CAUSE:known', 'window_key': '2026-10-30T08:15:00Z',
            'peak_key': peak.problem_key, 'error_count': 123, 'cause_signatures': ['known'],
        },
    }], notification_type='regular_peak', run_id=run_id, window_start=window)
    if stale:
        with pytest.raises(RuntimeError, match='older than completed collection'):
            bootstrap_runtime_state(_connect, query_hash)
        with RuntimeStateStore(_connect, query_hash).writer() as store:
            with pytest.raises(RuntimeError, match='not seeded'):
                store.restore(tmp_path)
        return
    assert bootstrap_runtime_state(_connect, query_hash)
    assert not bootstrap_runtime_state(_connect, query_hash)
    with RuntimeStateStore(_connect, query_hash).writer() as store:
        store.restore(tmp_path)
    restored = ProblemRegistry(str(tmp_path))
    assert restored.load()
    assert restored._problem_counter == 42
    assert restored._peak_counter == 7
    assert restored.is_fingerprint_known('known-fp')
    assert restored.problems[problem.problem_key].occurrences == 123
    cooldown = json.loads((tmp_path / 'alert_state_regular_phase.json').read_text())['peaks']['CAUSE:known']
    assert cooldown['last_sent_at'] == sent_at.isoformat()
    assert cooldown['cooldown_until'] == (sent_at + timedelta(minutes=45)).isoformat()
    assert cooldown['last_error_count'] == 123


def _fact(window_start, fingerprint, application, count):
    return {
        'window_start': window_start,
        'namespace': 'ns-a',
        'application': application,
        'fingerprint': fingerprint,
        'error_type': 'RuntimeError',
        'category': 'unknown',
        'subcategory': 'unclassified',
        'error_count': count,
        'first_event_at': window_start,
        'last_event_at': window_start,
        'sample_message': f'{fingerprint} failure',
        'metadata_quality': 'structured',
    }


def _collection(run_id, window_start, counts):
    incidents = []
    facts = []
    for fingerprint, application, count in counts:
        incident = Incident(id=f'inc-{fingerprint}', fingerprint=fingerprint)
        incident.error_type = 'RuntimeError'
        incident.normalized_message = f'{fingerprint} failure'
        incident.stats.current_count = count
        incident.apps = [application]
        incident.namespaces = ['ns-a']
        incidents.append(incident)
        facts.append(_fact(window_start, fingerprint, application, count))

    return SimpleNamespace(
        run_id=run_id,
        pipeline_version='integration-test',
        input_records=sum(count for _, _, count in counts),
        error_kind_facts=facts,
        incidents=incidents,
    )


def test_collection_checkpoint_and_report_snapshot_are_scoped_and_replay_safe(monkeypatch, tmp_path):
    import report_from_facts as report
    import confluence_csv_uploader as uploader
    from core.regular_schedule import load_collection_state
    from scripts.core.run_persistence import build_query_hash

    window = datetime(2026, 10, 29, 6, 45, tzinfo=timezone.utc)
    end = window + timedelta(minutes=15)
    source_index = 'report-integration-*'
    connection = _connect()
    coverage_start, counts = load_collection_state(connection, source_index, ['ns-a'], window)
    assert coverage_start == window
    assert counts == {}
    coverage_start, _counts = load_collection_state(connection, source_index, ['ns-a'], end)
    assert coverage_start == window
    connection.close()

    for run_id, count, source in [
        ('report-first', 10, source_index), ('report-correction', 20, source_index),
        ('report-other-scope', 900, 'other-report-integration-*'),
    ]:
        persist_analysis_run(
            connection_factory=_connect, collection=_collection(run_id, window, [('report-fp', 'cards', count)]),
            run_type='regular', window_start=window, window_end=end, monitored_namespaces=['ns-a'],
            expected_count=count, fetched_count=count, source_index=source,
        )
    connection = _connect()
    snapshot = report.load_snapshot(connection, build_query_hash(source_index, ['ns-a']), ['ns-a'], end)
    assert snapshot['namespace_counts'] == {window: 20}
    assert report.error_rows(snapshot)[0]['error_lines_2h'] == 20
    connection.close()

    monkeypatch.setenv('ES_INDEX', source_index)
    monkeypatch.setenv('TEAMS_ENABLED', 'false')
    monkeypatch.setattr(report, 'load_monitored_namespaces', lambda **_kwargs: ['ns-a'])
    for name in ('KNOWN_ERRORS', 'KNOWN_PEAKS', 'RECENT_INCIDENTS'):
        monkeypatch.setenv(f'CONFLUENCE_{name}_PAGE_ID', name)
    sent = []
    monkeypatch.setattr(uploader, 'upload_to_confluence', lambda page, body: sent.append((page, body)) or True)
    now = end.replace(hour=8, minute=10)
    assert report.run_reports(connection_factory=_connect, now=now, output_dir=tmp_path)['status'] == 'success'
    assert len(sent) == 3
    report.run_reports(connection_factory=_connect, now=now + timedelta(minutes=5), output_dir=tmp_path)
    assert len(sent) == 3
    assert 'INCOMPLETE DATA' in sent[0][1]


def test_publication_retry_is_per_destination_and_records_only_success():
    import report_from_facts as report
    from scripts.core.run_persistence import build_query_hash

    connection = _connect()
    query_hash = build_query_hash('delivery-test-*', ['ns-a'])
    end = datetime(2026, 10, 29, 7, tzinfo=timezone.utc)
    sends = []
    assert report.publish_once(connection, query_hash, 'daily', end, 'smtp:test', lambda: sends.append('smtp') or True)
    assert not report.publish_once(connection, query_hash, 'daily', end, 'wiki:test', lambda: sends.append('wiki-failed') or False)
    assert report.publish_once(connection, query_hash, 'daily', end, 'smtp:test', lambda: sends.append('smtp-duplicate') or True)
    assert report.publish_once(connection, query_hash, 'daily', end, 'wiki:test', lambda: sends.append('wiki-retry') or True)
    assert sends == ['smtp', 'wiki-failed', 'wiki-retry']
    connection.close()


def test_daily_report_publishes_final_after_gap_closes_and_sends_only_once(monkeypatch, tmp_path):
    import report_from_facts as report
    import confluence_csv_uploader as uploader
    from core.email_notifier import EmailNotifier

    end = datetime(2026, 10, 30, 7, tzinfo=timezone.utc)
    start = end - timedelta(hours=24)
    source_index = 'complete-daily-integration-*'
    connection = _connect()
    for quarter in range(95):
        window = start + timedelta(minutes=quarter * 15)
        count = 12 if quarter == 0 else 0
        persist_analysis_run(
            connection_factory=_connect, connection=connection,
            collection=_collection(f'daily-complete-{quarter}', window, [('daily-fp', 'cards', count)] if count else []),
            run_type='regular', window_start=window, window_end=window + timedelta(minutes=15),
            monitored_namespaces=['ns-a'], expected_count=count, fetched_count=count, source_index=source_index,
        )
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO ailog_peak.cause_family_facts
                (run_id, window_start, cause_signature, signature_version, canonical_cause,
                 root_application, operation, outward_status, assessment, confidence,
                 raw_error_lines, traced_error_lines, unsegmented_error_lines, unique_operations,
                 operation_count_method, operation_count_confidence, next_action, representative_trace_id)
            VALUES (%s, %s, 'daily-family', 'test', 'Database unavailable', 'cards', 'lookup', 503,
                    'technical_failure', 'high', 12, 12, 0, 1, 'trace_id', 'high', 'Repair backend', 'trace-test')
        """, ('daily-complete-0', start))
    connection.commit()
    connection.close()
    monkeypatch.setenv('ES_INDEX', source_index)
    monkeypatch.setenv('DAILY_REPORT_HOUR_UTC', '7')
    monkeypatch.setenv('TEAMS_ENABLED', 'true')
    monkeypatch.setenv('TEAMS_EMAIL', 'daily-test@example.invalid')
    monkeypatch.setenv('TEAMS_WEBHOOK_URL', '')
    monkeypatch.setattr(report, 'load_monitored_namespaces', lambda **_kwargs: ['ns-a'])
    for name in ('KNOWN_ERRORS', 'KNOWN_PEAKS', 'RECENT_INCIDENTS'):
        monkeypatch.setenv(f'CONFLUENCE_{name}_PAGE_ID', name)
    pages, emails = [], []
    monkeypatch.setattr(uploader, 'upload_to_confluence', lambda page, body: pages.append((page, body)) or True)
    monkeypatch.setattr(EmailNotifier, '_send_email_smtp', lambda _self, subject, body: emails.append((subject, body)) or True)
    now = end.replace(hour=8, minute=10)
    partial = report.run_reports(connection_factory=_connect, now=now, output_dir=tmp_path)
    assert partial['daily_complete'] is False
    assert emails == []
    assert len(pages) == 3
    assert '95/96 complete' in pages[-1][1]

    window = end - timedelta(minutes=15)
    persist_analysis_run(
        connection_factory=_connect, collection=_collection('daily-complete-95', window, []),
        run_type='regular', window_start=window, window_end=end, monitored_namespaces=['ns-a'],
        expected_count=0, fetched_count=0, source_index=source_index,
    )
    final = report.run_reports(connection_factory=_connect, now=now, output_dir=tmp_path)
    assert final['status'] == 'success'
    assert final['daily_complete'] is True
    assert len(pages) == 6
    assert len(emails) == 1
    assert 'Diagnostic coverage: 12/12 ERROR lines' in emails[0][1]
    assert 'Database unavailable [technical_failure; confidence=high]' in emails[0][1]
    assert 'operation occurrences: 1' in emails[0][1]
    report.run_reports(connection_factory=_connect, now=now + timedelta(minutes=5), output_dir=tmp_path)
    assert len(pages) == 6
    assert len(emails) == 1


def test_migration_ledger_and_schema_postconditions():
    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT migration_name, LENGTH(TRIM(checksum)), execution_ms '
            'FROM ailog_peak.schema_migrations ORDER BY migration_name'
        )
        ledger_rows = cursor.fetchall()
        cursor.execute(
            "SELECT to_regclass('ailog_peak.analysis_runs'), "
            "to_regclass('ailog_peak.error_kind_counts'), "
            "to_regclass('ailog_peak.namespace_error_counts'), "
            "to_regclass('ailog_peak.detection_events'), "
            "to_regclass('ailog_peak.daily_error_kind_rollups'), "
            "to_regclass('ailog_peak.daily_namespace_rollups'), "
            "to_regclass('ailog_peak.notification_deliveries'), "
            "to_regclass('ailog_peak.cause_family_facts'), "
            "to_regclass('ailog_peak.v_complete_cause_family_facts'), "
            "to_regclass('ailog_peak.v_pipeline_health'), "
            "to_regclass('ailog_peak.v_notification_delivery_health'), "
            "to_regclass('ailog_peak.v_metadata_quality_health'), "
            "to_regclass('ailog_peak.workflow_lifecycle_runs'), "
            "to_regclass('ailog_peak.workflow_lifecycle_incidents'), "
            "to_regclass('ailog_peak.workflow_lifecycle_evidence')"
        )
        schema_objects = cursor.fetchone()
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'ailog_peak' "
            "AND table_name = 'cause_family_facts' "
            "AND column_name IN ("
            "'operation_count_method', "
            "'operation_count_confidence', "
            "'operation_count_reason'"
            ") ORDER BY column_name"
        )
        operation_count_columns = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'ailog_peak' "
            "AND table_name = 'v_latest_threshold_snapshot' "
            "AND column_name = 'monitored_namespaces'"
        )
        snapshot_view_columns = [row[0] for row in cursor.fetchall()]
    connection.close()

    assert [row[0] for row in ledger_rows] == [
        migration.name
        for migration in sorted(run_db_migrations.MIGRATIONS_DIR.glob('[0-9]*.sql'))
    ]
    assert all(checksum_length == 64 and execution_ms >= 0 for _, checksum_length, execution_ms in ledger_rows)
    assert all(schema_objects)
    assert operation_count_columns == [
        'operation_count_confidence',
        'operation_count_method',
        'operation_count_reason',
    ]
    assert snapshot_view_columns == ['monitored_namespaces']


def test_utc_slot_snapshot_roundtrip_retains_ten_weeks_zeros_and_init_audit(monkeypatch):
    from scripts.core import calculate_peak_thresholds as training
    from scripts.core.peak_detection import PeakDetector
    from scripts.core.threshold_snapshot_guard import decide_refresh, load_latest_complete_snapshot

    monkeypatch.setenv('MONITORED_NAMESPACES', 'ns-a')
    monkeypatch.setenv('PERCENTILE_LEVEL', '0.95')
    monkeypatch.setenv('MIN_SAMPLES_FOR_THRESHOLD', '10')
    cutoff = datetime(2026, 10, 26, 7, tzinfo=timezone.utc)
    latest_monday = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)
    for week in range(10):
        monday = latest_monday - timedelta(weeks=week)
        slots = [(monday, 0), (monday + timedelta(hours=2), 13000)]
        if week < 2:
            slots.append((monday + timedelta(hours=2, minutes=15), 1000))
        for timestamp, count in slots:
            collection = _collection(
                f'integration-slot-{timestamp:%Y%m%dT%H%M}', timestamp,
                [('fp-slot', 'app-a', count)] if count else [],
            )
            persist_analysis_run(
                connection_factory=_connect, collection=collection, run_type='regular',
                window_start=timestamp, window_end=timestamp + timedelta(minutes=15),
                monitored_namespaces=['ns-a'], expected_count=count, fetched_count=count,
                source_index='slot-logs-*',
            )

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'Europe/Prague'")
        cursor.execute("""
            INSERT INTO ailog_peak.threshold_snapshot_runs
                (snapshot_id, percentile_level, population_grain, training_start,
                 training_end, sample_count, percentile_method, calculation_version,
                 status, completed_at, monitored_namespaces)
            VALUES ('00000000-0000-0000-0000-000000000041', .95,
                    'namespace/15m/day_of_week/active_windows', %s, %s, 100,
                    %s, '4.1', 'complete', NOW(), ARRAY['ns-a'])
        """, (latest_monday - timedelta(weeks=10), cutoff, training.PERCENTILE_METHOD))
        cursor.execute("""
            INSERT INTO ailog_peak.threshold_snapshot_values
                (snapshot_id, namespace, day_of_week, percentile_value, cap_value, sample_count)
            VALUES ('00000000-0000-0000-0000-000000000041', 'ns-a', 0, 10, 1, 100)
        """)
    connection.commit()
    old = load_latest_complete_snapshot(connection)
    assert decide_refresh(old, percentile_level=.95, monitored_namespaces=['ns-a']).refresh
    with pytest.raises(RuntimeError, match='threshold snapshot'):
        PeakDetector(conn=connection).is_peak(12000, 'ns-a', 0, 12, 0)

    data, date_range = training.fetch_raw_data(connection, as_of=cutoff)
    assert data[('ns-a', 0, 10, 0)] == [0] * 10
    assert data[('ns-a', 0, 12, 0)] == [13000] * 10
    assert data[('ns-a', 0, 12, 1)] == [1000] * 2
    assert ('ns-a', 0, 11, 0) not in data
    profiles = training.calculate_p93_thresholds(data)
    snapshot_id = training.save_thresholds_to_db(connection, profiles, date_range, as_of=cutoff)
    detector = PeakDetector(conn=connection)
    assert detector.is_peak(1, 'ns-a', 0, 10, 0)['profile_status'] == 'mature'
    assert not detector.is_peak(12000, 'ns-a', 0, 12, 0)['is_peak']
    assert not decide_refresh(
        load_latest_complete_snapshot(connection), percentile_level=.95, monitored_namespaces=['ns-a'],
    ).refresh

    for quarter, status in [(1, 'init'), (2, 'missing')]:
        window_start = cutoff.replace(hour=12, minute=quarter * 15)
        verdict = detector.is_peak(1200, 'ns-a', 0, 12, quarter)
        assert verdict['threshold_snapshot_id'] == snapshot_id
        assert verdict['profile_status'] == status
        assert verdict['cap_threshold'] is None
        collection = _collection(f'integration-slot-verdict-{quarter}', window_start, [('fp-slot-verdict', 'app-a', 1200)])
        collection.namespace_peak_decisions = [item.to_dict() for item in materialize_namespace_decisions([{
            **verdict, 'window_start': window_start.isoformat(), 'namespace_total': 1200,
            'peak_identifier': 'slot-peak' if verdict['is_peak'] else None,
            'verdict_reason': 'peak_undiagnosed' if verdict['is_peak'] else 'threshold_profile_missing',
        }], ['ns-a'], window_start=window_start)]
        persist_analysis_run(
            connection_factory=_connect, collection=collection, run_type='regular',
            window_start=window_start, window_end=window_start + timedelta(minutes=15),
            monitored_namespaces=['ns-a'], expected_count=1200, fetched_count=1200,
            source_index='slot-logs-*',
        )
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT profile_status, threshold_samples, is_evaluated, cap_threshold
            FROM ailog_peak.namespace_peak_decisions
            WHERE run_id LIKE 'integration-slot-verdict-%%' ORDER BY window_start_utc
        """)
        assert cursor.fetchall() == [('init', 2, True, None), ('missing', 0, False, None)]
    connection.close()


def test_two_fingerprints_and_replay_have_one_authoritative_run():
    window_start = datetime(2026, 7, 31, 8, 0, tzinfo=timezone.utc)
    window_end = window_start + timedelta(minutes=15)
    counts = [('fp-a', 'app-a', 3), ('fp-b', 'app-b', 2)]

    first = persist_analysis_run(
        connection_factory=_connect,
        collection=_collection('integration-run-1', window_start, counts),
        run_type='regular',
        window_start=window_start,
        window_end=window_end,
        monitored_namespaces=['ns-a'],
        expected_count=5,
        fetched_count=5,
        source_index='logs-*',
    )
    replay = persist_analysis_run(
        connection_factory=_connect,
        collection=_collection('integration-run-2', window_start, counts),
        run_type='regular',
        window_start=window_start,
        window_end=window_end,
        monitored_namespaces=['ns-a'],
        expected_count=5,
        fetched_count=5,
        source_index='logs-*',
    )

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT run_id, status, replay_of_run_id, superseded_by_run_id '
            'FROM ailog_peak.analysis_runs '
            "WHERE run_id IN ('integration-run-1', 'integration-run-2') "
            'ORDER BY run_id'
        )
        runs = cursor.fetchall()
        cursor.execute(
            'SELECT run_id, fingerprint, error_count '
            'FROM ailog_peak.v_complete_error_kind_counts '
            'WHERE window_start = %s ORDER BY fingerprint',
            (window_start,),
        )
        authoritative_facts = cursor.fetchall()
    connection.close()

    assert first['fact_rows'] == replay['fact_rows'] == 2
    assert first['incident_rows'] == replay['incident_rows'] == 2
    assert runs == [
        ('integration-run-1', 'superseded', None, 'integration-run-2'),
        ('integration-run-2', 'complete', 'integration-run-1', None),
    ]
    assert authoritative_facts == [
        ('integration-run-2', 'fp-a', 3),
        ('integration-run-2', 'fp-b', 2),
    ]


def test_injected_bulk_failure_leaves_failed_run_without_facts():
    window_start = datetime(2026, 7, 31, 8, 15, tzinfo=timezone.utc)
    window_end = window_start + timedelta(minutes=15)
    bulk_calls = 0

    def fail_after_fact_insert(cursor, statement, rows, page_size):
        nonlocal bulk_calls
        bulk_calls += 1
        if bulk_calls == 2:
            raise RuntimeError('injected namespace insert failure')
        execute_values(cursor, statement, rows, page_size=page_size)

    with pytest.raises(RuntimeError, match='injected namespace insert failure'):
        persist_analysis_run(
            connection_factory=_connect,
            collection=_collection(
                'integration-run-failure',
                window_start,
                [('fp-failure', 'app-a', 1)],
            ),
            run_type='regular',
            window_start=window_start,
            window_end=window_end,
            monitored_namespaces=['ns-a'],
            expected_count=1,
            fetched_count=1,
            source_index='logs-*',
            execute_values_fn=fail_after_fact_insert,
        )

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT status FROM ailog_peak.analysis_runs WHERE run_id = %s',
            ('integration-run-failure',),
        )
        status = cursor.fetchone()[0]
        cursor.execute(
            'SELECT COUNT(*) FROM ailog_peak.error_kind_counts WHERE run_id = %s',
            ('integration-run-failure',),
        )
        fact_count = cursor.fetchone()[0]
        cursor.execute(
            'SELECT COUNT(*) FROM ailog_peak.namespace_error_counts WHERE run_id = %s',
            ('integration-run-failure',),
        )
        namespace_count = cursor.fetchone()[0]
    connection.close()

    assert status == 'failed'
    assert fact_count == 0
    assert namespace_count == 0


def test_retention_rolls_up_authoritative_facts_before_delete():
    window_start = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    window_end = window_start + timedelta(minutes=15)
    first = persist_analysis_run(
        connection_factory=_connect,
        collection=_collection(
            'integration-retention-1',
            window_start,
            [('fp-retained', 'app-a', 3)],
        ),
        run_type='regular',
        window_start=window_start,
        window_end=window_end,
        monitored_namespaces=['ns-a'],
        expected_count=3,
        fetched_count=3,
        source_index='logs-*',
    )
    replay = persist_analysis_run(
        connection_factory=_connect,
        collection=_collection(
            'integration-retention-2',
            window_start,
            [('fp-retained', 'app-a', 5)],
        ),
        run_type='regular',
        window_start=window_start,
        window_end=window_end,
        monitored_namespaces=['ns-a'],
        expected_count=5,
        fetched_count=5,
        source_index='logs-*',
    )
    assert first['fact_rows'] == replay['fact_rows'] == 1

    legacy_timestamp = datetime(2026, 1, 14, 8, 0, tzinfo=timezone.utc)
    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ailog_peak.peak_raw_data (
                timestamp, day_of_week, hour_of_day, quarter_hour,
                namespace, error_count, original_value
            ) VALUES (%s, 2, 8, 0, 'legacy-only-ns', 7, 7)
            """,
            (legacy_timestamp,),
        )
    connection.commit()
    connection.close()

    dry_run = run_maintenance(
        connection_factory=_connect,
        retention_days=90,
        dry_run=True,
        now=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    assert dry_run['source_events'] == 5
    assert dry_run['deleted_fact_rows'] == 2

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.error_kind_counts "
            "WHERE run_id LIKE 'integration-retention-%'"
        )
        assert cursor.fetchone()[0] == 2
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.daily_error_kind_rollups "
            "WHERE fingerprint = 'fp-retained'"
        )
        assert cursor.fetchone()[0] == 0
    connection.close()

    committed = run_maintenance(
        connection_factory=_connect,
        retention_days=90,
        now=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )
    assert committed['source_fact_rows'] == 1
    assert committed['source_events'] == 5
    assert committed['legacy_raw_rows'] == 1
    assert committed['legacy_raw_events'] == 7
    assert committed['deleted_fact_rows'] == 2
    assert committed['deleted_namespace_rows'] == 2
    assert committed['deleted_peak_raw_rows'] == 2

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT error_count, complete_window_count
            FROM ailog_peak.daily_error_kind_rollups
            WHERE rollup_date = DATE '2026-01-15'
              AND fingerprint = 'fp-retained'
            """
        )
        assert cursor.fetchone() == (5, 1)
        cursor.execute(
            """
            SELECT error_count, complete_window_count
            FROM ailog_peak.daily_namespace_rollups
            WHERE rollup_date = DATE '2026-01-15'
              AND namespace = 'ns-a'
            """
        )
        assert cursor.fetchone() == (5, 1)
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.error_kind_counts "
            "WHERE run_id LIKE 'integration-retention-%'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            "SELECT COUNT(*) FROM ailog_peak.peak_raw_data "
            "WHERE namespace = 'legacy-only-ns'"
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT error_count, complete_window_count, source_kind
            FROM ailog_peak.daily_namespace_rollups
            WHERE rollup_date = DATE '2026-01-14'
              AND namespace = 'legacy-only-ns'
            """
        )
        assert cursor.fetchone() == (7, 1, 'legacy_peak_raw_data')
        cursor.execute(
            "SELECT status, source_events, deleted_fact_rows "
            "FROM ailog_peak.maintenance_runs ORDER BY started_at DESC LIMIT 1"
        )
        assert cursor.fetchone() == ('complete', 5, 2)
    connection.close()


def test_episode_policy_delivery_fk_chain_survives_authoritative_replay():
    window_start = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
    decisions = [item.to_dict() for item in materialize_namespace_decisions([{
        'window_start': window_start.isoformat(), 'namespace': 'ns-a',
        'namespace_total': 5, 'is_namespace_peak': True,
        'p93_threshold': 2, 'cap_threshold': 3, 'triggered_by': 'both',
        'peak_identifier': 'integration-peak', 'family_decisions': [],
    }], ['ns-a'], window_start=window_start, stream_key='integration-r109')]
    episodes, transitions = materialize_episode_state(decisions, [])
    collection = _collection('integration-episode-1', window_start, [('fp-episode', 'app-a', 5)])
    collection.namespace_peak_decisions = decisions
    collection.peak_episodes = episodes
    collection.peak_episode_transitions = transitions
    arguments = dict(
        connection_factory=_connect, collection=collection, run_type='regular',
        window_start=window_start, window_end=window_start + timedelta(minutes=15),
        monitored_namespaces=['ns-a'], expected_count=5, fetched_count=5,
        source_index='logs-*',
    )
    persist_analysis_run(**arguments)
    policy = decide_notification_candidates([{
        **transitions[0], 'episode_state': transitions[0]['state'],
    }])[0].to_dict()
    assert persist_notification_decisions(_connect, [policy]) == 1
    assert persist_notification_deliveries(_connect, [{
        'notification_decision_id': policy['notification_decision_id'],
        'dedup_key': 'integration-episode-delivery', 'destination': 'test-smtp',
        'status': 'delivered',
    }], notification_type='regular_peak', run_id=collection.run_id, window_start=window_start) == 1

    collection.run_id = 'integration-episode-2'
    persist_analysis_run(**arguments)
    assert persist_notification_decisions(_connect, [policy]) == 1
    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM ailog_peak.notification_decisions WHERE notification_decision_id = %s", (policy['notification_decision_id'],))
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM ailog_peak.notification_deliveries WHERE dedup_key = 'integration-episode-delivery'")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_episode_windows WHERE episode_id = %s", (episodes[0]['episode_id'],))
        assert cursor.fetchone()[0] == 1
    connection.close()


def test_incomplete_late_replay_cannot_replace_existing_daily_rollup():
    window_start = datetime(2026, 1, 16, 8, 0, tzinfo=timezone.utc)
    window_end = window_start + timedelta(minutes=15)
    persist_analysis_run(
        connection_factory=_connect,
        collection=_collection(
            'integration-late-original',
            window_start,
            [('fp-late', 'app-a', 4)],
        ),
        run_type='regular',
        window_start=window_start,
        window_end=window_end,
        monitored_namespaces=['ns-a'],
        expected_count=4,
        fetched_count=4,
        source_index='logs-*',
    )
    maintenance_now = datetime(2026, 7, 31, tzinfo=timezone.utc)
    run_maintenance(
        connection_factory=_connect,
        retention_days=90,
        now=maintenance_now,
    )

    replay_start = window_start + timedelta(minutes=15)
    persist_analysis_run(
        connection_factory=_connect,
        collection=_collection(
            'integration-late-fragment',
            replay_start,
            [('fp-late-new', 'app-a', 2)],
        ),
        run_type='regular',
        window_start=replay_start,
        window_end=replay_start + timedelta(minutes=15),
        monitored_namespaces=['ns-a'],
        expected_count=2,
        fetched_count=2,
        source_index='logs-*',
    )

    with pytest.raises(RuntimeError, match='complete 96-window authoritative replay'):
        run_maintenance(
            connection_factory=_connect,
            retention_days=90,
            now=maintenance_now,
        )

    connection = _connect()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT error_count, complete_window_count
            FROM ailog_peak.daily_namespace_rollups
            WHERE rollup_date = DATE '2026-01-16'
              AND namespace = 'ns-a'
            """
        )
        assert cursor.fetchone() == (4, 1)
        cursor.execute(
            "SELECT COUNT(*), SUM(error_count) "
            "FROM ailog_peak.namespace_error_counts "
            "WHERE run_id = 'integration-late-fragment'"
        )
        assert cursor.fetchone() == (1, 2)
        cursor.execute(
            """
            SELECT status, error_message
            FROM ailog_peak.maintenance_runs
            WHERE status = 'failed'
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
        failed_status, error_message = cursor.fetchone()
    connection.close()

    assert failed_status == 'failed'
    assert 'complete 96-window authoritative replay' in error_message