"""Durable registry and notification state for PVC-free scheduled collectors."""

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
from pathlib import Path

from psycopg2.extras import Json
import yaml


STATE_FILES = (
    'known_problems.yaml',
    'known_peaks.yaml',
    'alert_state_regular_phase.json',
)


class RuntimeStateStore:
    def __init__(self, connection_factory, query_hash):
        self.connection_factory = connection_factory
        self.query_hash = query_hash
        self.connection = None
        self.lock_key = int.from_bytes(
            hashlib.sha256(('runtime-state:' + query_hash).encode()).digest()[:8],
            byteorder='big', signed=True,
        )

    @contextmanager
    def writer(self):
        if self.connection is not None:
            raise RuntimeError('runtime state writer is already active')
        connection = self.connection_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_lock(%s)', (self.lock_key,))
                if not cursor.fetchone()[0]:
                    raise RuntimeError('another runtime state writer is active')
            connection.commit()
            self.connection = connection
            yield self
        finally:
            self.connection = None
            connection.close()

    def _require_writer(self):
        if self.connection is None:
            raise RuntimeError('runtime state requires an active writer lease')
        return self.connection

    @staticmethod
    def validate_files(files):
        if not isinstance(files, dict) or set(files) != set(STATE_FILES):
            raise ValueError('runtime state must include both registries and alert cooldowns')
        if not all(isinstance(value, str) for value in files.values()):
            raise ValueError('runtime state files must be text')
        for filename in STATE_FILES[:2]:
            entries = yaml.safe_load(files[filename])
            if not isinstance(entries, list):
                raise ValueError(f'{filename} must contain a registry list')
            if any(not isinstance(entry, dict) or not entry.get('id') or not entry.get('problem_key')
                   for entry in entries):
                raise ValueError(f'{filename} contains an invalid entry')
        alerts = json.loads(files[STATE_FILES[2]])
        if not isinstance(alerts, dict) or not isinstance(alerts.get('peaks'), dict):
            raise ValueError('runtime state has invalid alert cooldowns')

    def seed(self, files):
        self.validate_files(files)
        connection = self._require_writer()
        with connection.cursor() as cursor:
            cursor.execute('''
                INSERT INTO ailog_peak.runtime_state (query_hash, files)
                VALUES (%s, %s) ON CONFLICT (query_hash) DO NOTHING
            ''', (self.query_hash, Json(files)))
            inserted = cursor.rowcount == 1
        connection.commit()
        return inserted

    def restore(self, registry_dir):
        connection = self._require_writer()
        with connection.cursor() as cursor:
            cursor.execute('SELECT files FROM ailog_peak.runtime_state WHERE query_hash = %s',
                           (self.query_hash,))
            row = cursor.fetchone()
        connection.commit()
        if row is None:
            raise RuntimeError('runtime state is not seeded; refusing an empty registry')
        files = row[0]
        self.validate_files(files)
        directory = Path(registry_dir)
        directory.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            temporary = directory / (filename + '.restore.tmp')
            temporary.write_text(content, encoding='utf-8')
            temporary.replace(directory / filename)

    def checkpoint(self, registry_dir):
        connection = self._require_writer()
        directory = Path(registry_dir)
        files = {filename: (directory / filename).read_text(encoding='utf-8')
                 for filename in STATE_FILES}
        self.validate_files(files)
        with connection.cursor() as cursor:
            cursor.execute('''
                UPDATE ailog_peak.runtime_state SET files = %s, updated_at = NOW()
                WHERE query_hash = %s
            ''', (Json(files), self.query_hash))
            if cursor.rowcount != 1:
                raise RuntimeError('runtime state disappeared; refusing a new empty registry')
        connection.commit()


def bootstrap_runtime_state(connection_factory, query_hash, cooldown_minutes=45):
    store = RuntimeStateStore(connection_factory, query_hash)
    with store.writer():
        connection = store._require_writer()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM ailog_peak.runtime_state WHERE query_hash = %s', (query_hash,))
            if cursor.fetchone():
                connection.commit()
                return False
            cursor.execute('''
                SELECT payload, updated_at FROM ailog_peak.report_knowledge
                WHERE query_hash = %s
            ''', (query_hash,))
            knowledge = cursor.fetchall()
            if not knowledge:
                raise RuntimeError('No mirrored registry exists; explicit state import is required')
            cursor.execute('''
                SELECT MAX(completed_at) FROM ailog_peak.analysis_runs
                WHERE query_hash = %s AND status = 'complete'
                  AND superseded_by_run_id IS NULL
            ''', (query_hash,))
            last_collection = cursor.fetchone()[0]
            if last_collection and max(updated_at for _, updated_at in knowledge) < last_collection:
                raise RuntimeError('Mirrored registry is older than completed collection; refusing stale bootstrap')
            cursor.execute('''
                SELECT DISTINCT ON (delivery.metadata->>'alert_identity')
                    delivery.metadata, delivery.attempted_at
                FROM ailog_peak.notification_deliveries delivery
                JOIN ailog_peak.analysis_runs run_row ON run_row.run_id = delivery.run_id
                WHERE run_row.query_hash = %s AND delivery.status = 'delivered'
                  AND delivery.notification_type = 'regular_peak'
                  AND NULLIF(delivery.metadata->>'alert_identity', '') IS NOT NULL
                ORDER BY delivery.metadata->>'alert_identity', delivery.attempted_at DESC
            ''', (query_hash,))
            deliveries = cursor.fetchall()
        connection.commit()
        problems, peaks = [], []
        for payload, _updated_at in knowledge:
            entry = dict(payload)
            (peaks if entry.pop('_report_kind', None) == 'peak' else problems).append(entry)
        alerts = {}
        for metadata, attempted_at in deliveries:
            alerts[metadata['alert_identity']] = {
                'last_sent_at': attempted_at.isoformat(),
                'last_sent_window': metadata.get('window_key', ''),
                'last_trend': metadata.get('trend', ''),
                'last_error_count': int(metadata.get('error_count', 0) or 0),
                'cooldown_until': (attempted_at + timedelta(minutes=max(cooldown_minutes, 0))).isoformat(),
                'last_reason': metadata.get('send_reason', ''),
                'peak_key': metadata.get('peak_key', ''),
                'cause_signatures': metadata.get('cause_signatures', []),
            }
        return store.seed({
            'known_problems.yaml': yaml.safe_dump(problems, allow_unicode=True, sort_keys=False),
            'known_peaks.yaml': yaml.safe_dump(peaks, allow_unicode=True, sort_keys=False),
            'alert_state_regular_phase.json': json.dumps({'peaks': alerts}),
        })