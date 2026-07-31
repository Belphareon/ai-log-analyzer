import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

psycopg2 = pytest.importorskip('psycopg2')
from psycopg2.extras import execute_values

from scripts.core import run_db_migrations
from scripts.core.run_data_maintenance import run_maintenance
from scripts.core.run_persistence import persist_analysis_run
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
            "to_regclass('ailog_peak.v_pipeline_health'), "
            "to_regclass('ailog_peak.v_notification_delivery_health'), "
            "to_regclass('ailog_peak.v_metadata_quality_health')"
        )
        schema_objects = cursor.fetchone()
    connection.close()

    assert [row[0] for row in ledger_rows] == [
        migration.name
        for migration in sorted(run_db_migrations.MIGRATIONS_DIR.glob('[0-9]*.sql'))
    ]
    assert all(checksum_length == 64 and execution_ms >= 0 for _, checksum_length, execution_ms in ledger_rows)
    assert all(schema_objects)


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