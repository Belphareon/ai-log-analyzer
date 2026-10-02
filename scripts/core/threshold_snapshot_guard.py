#!/usr/bin/env python3
"""Decide whether init must bootstrap a new threshold snapshot."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence, Tuple

import psycopg2

try:
    from .calculate_peak_thresholds import (
        CALCULATION_VERSION,
        DB_CONFIG,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
        load_monitored_namespaces,
    )
except ImportError:  # pragma: no cover - direct script execution
    from calculate_peak_thresholds import (
        CALCULATION_VERSION,
        DB_CONFIG,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
        load_monitored_namespaces,
    )


REFRESH_EXIT_CODE = 10


@dataclass(frozen=True)
class SnapshotMetadata:
    snapshot_id: str
    percentile_level: float
    population_grain: str
    percentile_method: str
    calculation_version: str
    namespaces: Tuple[str, ...]


@dataclass(frozen=True)
class RefreshDecision:
    refresh: bool
    reason: str
    snapshot_id: str = ""


def _normalized_namespaces(values: Iterable[Any]) -> Tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def load_latest_complete_snapshot(conn: Any) -> Optional[SnapshotMetadata]:
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT snapshot.snapshot_id::text,
                   snapshot.percentile_level,
                   snapshot.population_grain,
                   snapshot.percentile_method,
                   snapshot.calculation_version,
                                     snapshot.monitored_namespaces
            FROM ailog_peak.v_latest_threshold_snapshot snapshot
            GROUP BY snapshot.snapshot_id, snapshot.percentile_level,
                     snapshot.population_grain, snapshot.percentile_method,
                                         snapshot.calculation_version, snapshot.monitored_namespaces
        """)
        row = cursor.fetchone()
    finally:
        cursor.close()
    if not row:
        return None
    return SnapshotMetadata(
        snapshot_id=str(row[0]),
        percentile_level=float(row[1]),
        population_grain=str(row[2]),
        percentile_method=str(row[3]),
        calculation_version=str(row[4]),
        namespaces=_normalized_namespaces(row[5] or ()),
    )


def decide_refresh(
    snapshot: Optional[SnapshotMetadata],
    *,
    percentile_level: float,
    monitored_namespaces: Sequence[str],
    force: bool = False,
) -> RefreshDecision:
    if force:
        return RefreshDecision(True, "manual_refresh")
    if snapshot is None:
        return RefreshDecision(True, "bootstrap")

    expected_namespaces = _normalized_namespaces(monitored_namespaces)
    compatibility = {
        "percentile_level": abs(snapshot.percentile_level - percentile_level) < 1e-9,
        "population_grain": snapshot.population_grain == POPULATION_GRAIN,
        "percentile_method": snapshot.percentile_method == PERCENTILE_METHOD,
        "calculation_version": snapshot.calculation_version == CALCULATION_VERSION,
        "namespaces": snapshot.namespaces == expected_namespaces,
    }
    mismatches = [name for name, matches in compatibility.items() if not matches]
    if mismatches:
        return RefreshDecision(
            True,
            "model_change:" + ",".join(mismatches),
            snapshot.snapshot_id,
        )
    return RefreshDecision(False, "compatible_snapshot", snapshot.snapshot_id)


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_only_db_config() -> dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "database": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER") or os.getenv("DB_DDL_USER"),
        "password": os.getenv("DB_PASSWORD") or os.getenv("DB_DDL_PASSWORD"),
        "connect_timeout": 30,
        "options": "-c statement_timeout=60000",
    }


def main() -> int:
    monitored_namespaces = load_monitored_namespaces()
    if not monitored_namespaces:
        print("ERROR: MONITORED_NAMESPACES is required", file=sys.stderr)
        return 2

    percentile_level = float(os.getenv("PERCENTILE_LEVEL", "0.93"))
    force = _is_true(os.getenv("FORCE_THRESHOLD_REFRESH", "false"))
    try:
        conn = psycopg2.connect(**_read_only_db_config())
        conn.set_session(readonly=True, autocommit=True)
        snapshot = load_latest_complete_snapshot(conn)
        conn.close()
    except Exception as error:
        print(
            f"ERROR: threshold snapshot preflight failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 2

    decision = decide_refresh(
        snapshot,
        percentile_level=percentile_level,
        monitored_namespaces=monitored_namespaces,
        force=force,
    )
    print(
        f"threshold_snapshot_decision={'refresh' if decision.refresh else 'reuse'} "
        f"reason={decision.reason} snapshot_id={decision.snapshot_id or 'none'}"
    )
    return REFRESH_EXIT_CODE if decision.refresh else 0


if __name__ == "__main__":
    sys.exit(main())