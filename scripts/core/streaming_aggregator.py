#!/usr/bin/env python3
"""
Streaming Aggregator (r87)
==========================

Cíl: zpracovat LIBOVOLNĚ VELKÝ vstup z Elasticsearch bez držení všech recordů
v paměti a bez zkracování (žádný truncating OOM guard). Paměť je omezena počtem
UNIKÁTNÍCH fingerprintů / namespace / trace — ne počtem logů.

Princip:
  ES pages (globálně vzestupně dle @timestamp) → per-record normalizace
  (Phase A logika) → PŘESNÉ agregáty v RAM → bounded samples → detail eventy
  spillnuté do job-scoped SQLite na /data.

Agregáty jsou navrženy tak, aby `pipeline.run_streaming()` vyprodukoval
BIT-IDENTICKÉ výsledky jako `pipeline.run()` nad stejnými logy:
  - per-fp ns_bucket_counts[ns][floor15(ts)]  → Phase B rates i Phase C P93
  - per-fp Counters (app/ns/trace/originator) v pořadí příchodu (== ES pořadí)
  - burst stav inkrementálně (trailing 60s okno) == Phase C _detect_burst
  - první record fp = nejstarší (ES vzestupně) → normalized_message/error_type
  - bounded raw_samples (první 3), versions set

Robustnost vůči pořadí: bucket je ABSOLUTNÍ (floor na WINDOW_MINUTES), takže
window_idx se dopočítá až ve finalize z globálního minima — nezávisí na tom,
v jakém pořadí stránky dorazí.
"""

from __future__ import annotations

import os
import sys
import gc
import sqlite3
import tempfile
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional


def _ensure_pipeline_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    pipeline_dir = os.path.normpath(os.path.join(here, '..', 'pipeline'))
    if pipeline_dir not in sys.path:
        sys.path.insert(0, pipeline_dir)


def _floor_bucket(ts: datetime, window_minutes: int) -> datetime:
    minute = (ts.minute // window_minutes) * window_minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


class _FingerprintAcc:
    """Bounded per-fingerprint akumulátor. Roste s počtem NS/trace, ne s počtem logů."""

    __slots__ = (
        'fingerprint', 'error_type', 'normalized_message',
        'window_counts', 'ns_bucket_counts', 'ns_meas', 'apps_meas',
        'first_seen', 'last_seen',
        'raw_samples',
        'app_counts', 'ns_counts', 'trace_counts', 'originator_counts',
        'versions',
        'burst_window', 'burst_max', 'burst_sum', 'burst_n', 'burst_ts_events',
    )

    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.error_type = ''
        self.normalized_message = ''
        # Phase B: per-bucket count přes VŠECHNY timestamped recordy (nezávislé na ns)
        self.window_counts: Dict[datetime, int] = {}
        # Phase C P93: ns -> {bucket_datetime -> count}, jen truthy namespace
        self.ns_bucket_counts: Dict[str, Dict[datetime, int]] = {}
        # Phase B measurement sety (timestamped recordy, raw hodnota vč. None)
        self.ns_meas: set = set()
        self.apps_meas: set = set()
        self.first_seen: Optional[datetime] = None
        self.last_seen: Optional[datetime] = None
        self.raw_samples: List[str] = []
        # Incident Countery (VŠECHNY recordy, jen truthy hodnoty)
        self.app_counts: Counter = Counter()
        self.ns_counts: Counter = Counter()
        self.trace_counts: Counter = Counter()
        self.originator_counts: Counter = Counter()
        self.versions: set = set()
        # Burst stav (trailing okno) — identické s Phase C _detect_burst
        self.burst_window: deque = deque()
        self.burst_max: int = 0
        self.burst_sum: int = 0
        self.burst_n: int = 0
        self.burst_ts_events: int = 0  # počet eventů s timestampem (guard < 2)


class StreamingAggregator:
    """
    Konzumuje ES stránky, staví PŘESNÉ agregáty a spilluje detail eventy do SQLite.

    Použití:
        agg = StreamingAggregator(window_minutes=15, burst_window_sec=60)
        agg.ingest_page(list_of_error_dicts)   # opakovaně
        agg.finalize()
        # -> předej do pipeline.run_streaming(agg, run_id)
        agg.close()
    """

    def __init__(
        self,
        window_minutes: int = 15,
        burst_window_sec: int = 60,
        parser: Any = None,
        sqlite_path: Optional[str] = None,
        spill_details: bool = True,
    ):
        self.window_minutes = int(window_minutes)
        self.burst_window = timedelta(seconds=int(burst_window_sec))
        self.spill_details = spill_details

        if parser is None:
            _ensure_pipeline_on_path()
            from phase_a_parse import PhaseA_Parser  # type: ignore
            parser = PhaseA_Parser()
        self.parser = parser

        # Per-fingerprint akumulátory + pořadí prvního výskytu (== groups pořadí)
        self.acc: Dict[str, _FingerprintAcc] = {}
        self.fp_order: List[str] = []

        # Globální stav
        self.min_ts: Optional[datetime] = None
        self.max_ts: Optional[datetime] = None
        self.total_records: int = 0
        # (15m bucket, namespace, application, fingerprint) -> [count, first, last]
        self.error_kind_facts: Dict[tuple, List[Any]] = {}

        # Finalizované hodnoty
        self.current_window_start: Optional[datetime] = None
        self.global_last_bucket: Optional[datetime] = None
        self.global_max_window_idx: int = 0
        self._finalized = False

        # SQLite spill (detail eventy pro rekonstrukci trace timelines)
        self._sqlite_path: Optional[str] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._pending: List[tuple] = []
        if self.spill_details:
            self._open_sqlite(sqlite_path)

    # ------------------------------------------------------------------ SQLite
    def _open_sqlite(self, sqlite_path: Optional[str]) -> None:
        if sqlite_path is None:
            registry_dir = os.getenv('REGISTRY_DIR', '')
            base_dir = registry_dir if registry_dir and os.path.isdir(registry_dir) else tempfile.gettempdir()
            self._remove_stale_sqlite_files(base_dir)
            fd, sqlite_path = tempfile.mkstemp(prefix='streaming_events_', suffix='.sqlite', dir=base_dir)
            os.close(fd)
        self._sqlite_path = sqlite_path
        # fresh file
        try:
            if os.path.exists(sqlite_path) and os.path.getsize(sqlite_path) > 0:
                os.remove(sqlite_path)
        except OSError:
            pass
        self._conn = sqlite3.connect(sqlite_path)
        self._conn.execute('PRAGMA journal_mode=OFF')
        self._conn.execute('PRAGMA synchronous=OFF')
        self._conn.execute(
            'CREATE TABLE ev ('
            'fp TEXT, trace_id TEXT, ts TEXT, ns TEXT, app TEXT, '
            'span TEXT, parent TEXT, msg TEXT, etype TEXT, norm TEXT)'
        )
        self._conn.commit()

    @staticmethod
    def _remove_stale_sqlite_files(base_dir: str) -> None:
        max_age_seconds = int(os.getenv('STREAMING_SQLITE_MAX_AGE_SEC', '86400'))
        if max_age_seconds <= 0:
            return
        cutoff = time.time() - max_age_seconds
        try:
            entries = os.scandir(base_dir)
        except OSError:
            return
        with entries:
            for entry in entries:
                if not entry.name.startswith('streaming_events_') or not entry.name.endswith('.sqlite'):
                    continue
                try:
                    if entry.is_file() and entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                except OSError:
                    continue

    def _flush_sqlite(self) -> None:
        if self._conn is None or not self._pending:
            return
        self._conn.executemany(
            'INSERT INTO ev VALUES (?,?,?,?,?,?,?,?,?,?)', self._pending
        )
        self._conn.commit()
        self._pending.clear()

    # ------------------------------------------------------------------ ingest
    def ingest_page(self, errors: List[dict]) -> None:
        """Zpracuj jednu ES stránku (list raw error dictů). Recordy se NEDRŽÍ."""
        if self._finalized:
            raise RuntimeError('ingest_page() after finalize()')
        for err in errors:
            rec = self.parser.parse(err)
            self._ingest_record(rec)
        # detail eventy zapiš po každé stránce (drž paměť nízko)
        self._flush_sqlite()

    def _ingest_record(self, rec: Any) -> None:
        fp = rec.fingerprint
        acc = self.acc.get(fp)
        if acc is None:
            acc = _FingerprintAcc(fp)
            acc.error_type = getattr(rec, 'error_type', '') or ''
            acc.normalized_message = getattr(rec, 'normalized_message', '') or ''
            self.acc[fp] = acc
            self.fp_order.append(fp)

        self.total_records += 1

        # Incident Countery přes VŠECHNY recordy (i bez timestampu) — jako pipeline.run
        app_name = getattr(rec, 'app_name', None)
        if app_name:
            acc.app_counts[app_name] += 1
        ns = getattr(rec, 'namespace', None)
        if ns:
            acc.ns_counts[ns] += 1
        trace_id = getattr(rec, 'trace_id', None)
        if trace_id:
            acc.trace_counts[trace_id] += 1
        originator = getattr(rec, 'originator_application', None)
        if originator:
            acc.originator_counts[originator] += 1
        version = getattr(rec, 'app_version', None)
        if version and version != 'unknown':
            acc.versions.add(version)

        # Bounded raw samples (první 3)
        if len(acc.raw_samples) < 3:
            raw_msg = getattr(rec, 'raw_message', '') or ''
            acc.raw_samples.append(raw_msg[:500])

        ts = getattr(rec, 'timestamp', None)
        if not ts:
            return  # bez timestampu se do window/burst/bucket nepočítá (== Phase B)

        # Globální min/max
        if self.min_ts is None or ts < self.min_ts:
            self.min_ts = ts
        if self.max_ts is None or ts > self.max_ts:
            self.max_ts = ts

        # first/last seen fp
        if acc.first_seen is None or ts < acc.first_seen:
            acc.first_seen = ts
        if acc.last_seen is None or ts > acc.last_seen:
            acc.last_seen = ts

        # Phase B measurement sety (timestamped, raw hodnota vč. None) + window count
        acc.apps_meas.add(app_name)         # match Phase B fp_apps.add(r.app_name)
        acc.ns_meas.add(ns)                 # match Phase B fp_namespaces.add(r.namespace)
        bucket = _floor_bucket(ts, self.window_minutes)
        acc.window_counts[bucket] = acc.window_counts.get(bucket, 0) + 1

        fact_key = (bucket, ns or 'unknown', app_name or 'unknown', fp)
        fact = self.error_kind_facts.get(fact_key)
        if fact is None:
            self.error_kind_facts[fact_key] = [1, ts, ts]
        else:
            fact[0] += 1
            if ts < fact[1]:
                fact[1] = ts
            if ts > fact[2]:
                fact[2] = ts

        # Phase C P93: per-ns per-bucket count — jen truthy namespace (== Phase C)
        if ns:
            ns_buckets = acc.ns_bucket_counts.get(ns)
            if ns_buckets is None:
                ns_buckets = {}
                acc.ns_bucket_counts[ns] = ns_buckets
            ns_buckets[bucket] = ns_buckets.get(bucket, 0) + 1

        # Burst inkrementálně (trailing okno, identické s Phase C)
        acc.burst_ts_events += 1
        win = acc.burst_window
        win.append(ts)
        while win and win[0] < ts - self.burst_window:
            win.popleft()
        cnt = len(win)
        if cnt > acc.burst_max:
            acc.burst_max = cnt
        acc.burst_sum += cnt
        acc.burst_n += 1

        # Detail event → SQLite spill
        if self._conn is not None:
            self._pending.append((
                fp,
                trace_id or '',
                ts.isoformat(),
                getattr(rec, 'namespace', '') or '',
                app_name or '',
                getattr(rec, 'span_id', '') or '',
                getattr(rec, 'parent_span_id', '') or '',
                (getattr(rec, 'raw_message', '') or '')[:500],
                acc.error_type,
                getattr(rec, 'normalized_message', '') or '',
            ))
            if len(self._pending) >= 5000:
                self._flush_sqlite()

    # ---------------------------------------------------------------- finalize
    def finalize(self) -> None:
        if self._finalized:
            return
        self._flush_sqlite()
        if self.min_ts is not None:
            wm = self.window_minutes
            minute = self.min_ts.minute
            aligned = (minute // wm) * wm
            self.current_window_start = self.min_ts.replace(
                minute=aligned, second=0, microsecond=0
            )
            self.global_last_bucket = _floor_bucket(self.max_ts, wm)
            delta_min = int((self.global_last_bucket - self.current_window_start).total_seconds() / 60)
            self.global_max_window_idx = delta_min // wm
        self._finalized = True

    # --------------------------------------------------------------- accessors
    @property
    def fingerprint_count(self) -> int:
        return len(self.acc)

    def day_of_week(self) -> int:
        return self.min_ts.weekday() if self.min_ts else 0

    def iter_top_trace_records(
        self,
        max_traces: int = 20000,
        max_events_per_trace: Optional[int] = None,
        max_total_events: Optional[int] = None,
    ) -> Iterator[Any]:
        """
        Rekonstruuj duck-typed recordy pro TOP trace (dle počtu eventů) ze SQLite.

        build_trace_timelines() si stejně bere jen _MAX_TRACES nejaktivnějších,
        takže limit aplikujeme už na úrovni SQL a nedržíme všechno v RAM.
        """
        if self._conn is None:
            return
        if max_events_per_trace is None:
            max_events_per_trace = int(os.getenv('TRACE_TIMELINE_MAX_EVENTS_PER_TRACE', '5000'))
        if max_total_events is None:
            max_total_events = int(os.getenv('TRACE_TIMELINE_MAX_TOTAL_EVENTS', '200000'))

        cur = self._conn.execute(
            'SELECT trace_id FROM ev WHERE trace_id != "" '
            'GROUP BY trace_id ORDER BY COUNT(*) DESC LIMIT ?',
            (max_traces,),
        )
        top = [row[0] for row in cur.fetchall()]
        if not top:
            return
        from types import SimpleNamespace
        CHUNK = 500
        yielded_events = 0
        for i in range(0, len(top), CHUNK):
            chunk = top[i:i + CHUNK]
            placeholders = ','.join('?' * len(chunk))
            if max_events_per_trace > 0:
                rows = self._conn.execute(
                    'SELECT trace_id, ts, ns, app, msg, etype, norm FROM ('
                    'SELECT trace_id, ts, ns, app, msg, etype, norm, '
                    'ROW_NUMBER() OVER (PARTITION BY trace_id ORDER BY ts) AS event_rank '
                    f'FROM ev WHERE trace_id IN ({placeholders})'
                    ') WHERE event_rank <= ?',
                    [*chunk, max_events_per_trace],
                )
            else:
                rows = self._conn.execute(
                    f'SELECT trace_id, ts, ns, app, msg, etype, norm '
                    f'FROM ev WHERE trace_id IN ({placeholders})',
                    chunk,
                )
            for tid, ts, ns, app, msg, etype, norm in rows:
                if max_total_events > 0 and yielded_events >= max_total_events:
                    return
                try:
                    dt = datetime.fromisoformat(ts) if ts else None
                except ValueError:
                    dt = None
                yield SimpleNamespace(
                    trace_id=tid,
                    timestamp=dt,
                    app_name=app or '?',
                    namespace=ns or '',
                    normalized_message=norm or '',
                    error_type=etype or '',
                    raw_message=msg or '',
                )
                yielded_events += 1

    # ------------------------------------------------------------------ close
    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None
        if self._sqlite_path and os.path.exists(self._sqlite_path):
            try:
                os.remove(self._sqlite_path)
            except OSError:
                pass
        self._sqlite_path = None
        gc.collect()

    def __enter__(self) -> 'StreamingAggregator':
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
