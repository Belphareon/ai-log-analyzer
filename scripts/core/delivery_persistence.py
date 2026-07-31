#!/usr/bin/env python3
"""Persist immutable per-destination publication and notification outcomes."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import psycopg2
from psycopg2.extras import Json, execute_values


VALID_STATUSES = {"delivered", "failed", "suppressed", "skipped"}


def summarize_delivery_outcomes(
    deliveries: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize outcomes without hiding payloads that never reached a destination."""
    outcomes = list(deliveries)
    statuses_by_key: dict[str, set[str]] = {}
    for outcome in outcomes:
        dedup_key = str(outcome.get("dedup_key", "")).strip()
        status = str(outcome.get("status", "")).strip().lower()
        if dedup_key and status in VALID_STATUSES:
            statuses_by_key.setdefault(dedup_key, set()).add(status)

    failed_keys = sorted(
        dedup_key
        for dedup_key, statuses in statuses_by_key.items()
        if "failed" in statuses and "delivered" not in statuses
    )
    delivered_keys = sorted(
        dedup_key
        for dedup_key, statuses in statuses_by_key.items()
        if "delivered" in statuses
    )
    has_failed_attempt = any("failed" in statuses for statuses in statuses_by_key.values())

    if failed_keys:
        status = "failed"
    elif has_failed_attempt and delivered_keys:
        status = "partial"
    elif delivered_keys:
        status = "complete"
    elif any("suppressed" in statuses for statuses in statuses_by_key.values()):
        status = "suppressed"
    else:
        status = "skipped"

    return {
        "status": status,
        "failed_dedup_keys": failed_keys,
        "delivered_dedup_keys": delivered_keys,
        "outcome_count": len(outcomes),
    }


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect_from_env():
    return psycopg2.connect(
        host=_require_env("DB_HOST"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=_require_env("DB_NAME"),
        user=_require_env("DB_USER"),
        password=_require_env("DB_PASSWORD"),
        connect_timeout=30,
        options="-c statement_timeout=60000",
    )


def persist_notification_deliveries(
    connection_factory: Callable[[], Any],
    deliveries: Iterable[dict[str, Any]],
    *,
    notification_type: str,
    run_id: str | None = None,
    window_start: datetime | None = None,
) -> int:
    """Insert one immutable row per destination attempt or policy outcome."""
    notification_type = str(notification_type or "").strip()
    if not notification_type:
        raise ValueError("notification_type is required")
    if window_start is not None and window_start.tzinfo is None:
        raise ValueError("window_start must be timezone-aware")

    attempted_at = datetime.now(timezone.utc)
    rows = []
    for delivery in deliveries:
        status = str(delivery.get("status", "")).strip().lower()
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid delivery status: {status!r}")
        dedup_key = str(delivery.get("dedup_key", "")).strip()
        destination = str(delivery.get("destination", "")).strip()
        if not dedup_key or not destination:
            raise ValueError("Every delivery requires dedup_key and destination")
        metadata = delivery.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Delivery metadata must be a dictionary")
        rows.append(
            (
                str(uuid.uuid4()),
                run_id,
                window_start,
                notification_type,
                dedup_key,
                destination,
                status,
                str(delivery.get("provider_message", "") or "")[:4000],
                Json(metadata),
                delivery.get("attempted_at") or attempted_at,
            )
        )

    if not rows:
        return 0

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            execute_values(
                cursor,
                """
                INSERT INTO ailog_peak.notification_deliveries (
                    delivery_id, run_id, window_start, notification_type,
                    dedup_key, destination, status, provider_message,
                    metadata, attempted_at
                ) VALUES %s
                """,
                rows,
                page_size=500,
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    summary: dict[str, int] = {}
    for row in rows:
        summary[row[6]] = summary.get(row[6], 0) + 1
    print(
        json.dumps(
            {
                "event": "delivery_outcomes_persisted",
                "notification_type": notification_type,
                "run_id": run_id,
                "window_start": window_start.isoformat() if window_start else None,
                "outcome_count": len(rows),
                "status_counts": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return len(rows)