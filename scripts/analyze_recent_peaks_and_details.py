#!/usr/bin/env python3
"""
Generate review artifacts for:
1) All detected peaks in last N days (BROAD + STRICT definitions)
2) Three high-quality detail examples from recent data

Outputs to ../ai-data by default:
- peaks_last_<N>d_broad_full.csv
- peaks_last_<N>d_broad_summary.json
- peaks_last_<N>d_broad_summary.md
- peaks_last_<N>d_strict_full.csv
- peaks_last_<N>d_strict_summary.json
- peaks_last_<N>d_strict_summary.md
- detail_examples_last_<N>d.md
"""

import os
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from zoneinfo import ZoneInfo
import yaml


FLOW_PATTERNS = {
    "card-servicing": "card_servicing",
    "card-opening": "card_opening",
    "card-validation": "card_validation",
    "click2pay": "click2pay",
    "billing": "billing",
    "document-signing": "document_signing",
    "batch-processor": "batch_processing",
    "event-processor": "event_processing",
    "rainbow-status": "client_status",
    "codelist": "codelist",
    "client-segment": "client_segment",
    "design-lifecycle": "design_lifecycle",
    "georisk": "georisk",
    "pilot-context": "pilot_context",
}

import psycopg2
from dotenv import load_dotenv


def connect_db(project_root: Path):
    load_dotenv(project_root / ".env")
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 5432)),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    cur = conn.cursor()
    cur.execute("SET search_path = ailog_peak;")
    return conn, cur


def safe_ratio(original_value, reference_value):
    try:
        if reference_value is None or reference_value == 0:
            return None
        if original_value is None:
            return None
        return float(original_value) / float(reference_value)
    except Exception:
        return None


def format_ts(dt: datetime | None, tz_name: str = "Europe/Prague"):
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(ZoneInfo(tz_name))
    return f"{dt.isoformat()} (UTC) | {local_dt.isoformat()} ({tz_name})"


def score_for_quality(message: str, error_type: str):
    if not message:
        return 0
    msg = message.lower()
    score = 0

    # Penalize generic phrasing
    generic_markers = [
        "error handled",
        "service exception",
        "an error occurred",
        "unknownerror",
        "handle fault",
    ]
    for marker in generic_markers:
        if marker in msg:
            score -= 3

    # Reward specific hints
    specific_markers = [
        "card with id",
        "constraintviolationexception",
        "jsonparseexception",
        "accessdeniedexception",
        "operation not allowed",
        "scope",
        "status",
        "code=",
        "detail=",
        "#post#",
        "#get#",
    ]
    for marker in specific_markers:
        if marker in msg:
            score += 2

    # reward richer content length (but cap)
    score += min(len(message) // 80, 5)

    if error_type and error_type.lower() not in ("unknownerror", "simpleerror"):
        score += 2

    return score


def fetch_rows(cur, since, strict: bool):
    if strict:
        condition = "(is_spike = TRUE OR is_burst = TRUE)"
    else:
        condition = "(is_spike = TRUE OR is_burst = TRUE OR score >= 30)"

    cur.execute(
        f"""
        SELECT
            timestamp,
            namespace,
            error_type,
            original_value,
            reference_value,
            baseline_mean,
            ratio,
            score,
            severity,
            is_spike,
            is_burst,
            detection_method,
                        error_message,
                        suspected_root_cause,
                        known_peak_id,
                        app_name
        FROM peak_investigation
        WHERE timestamp >= %s
          AND {condition}
        ORDER BY timestamp ASC;
        """,
        (since,)
    )
    return cur.fetchall()


def write_outputs(rows, now, since, days: int, output_dir: Path, mode: str):
    full_csv = output_dir / f"peaks_last_{days}d_{mode}_full.csv"
    with open(full_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "namespace",
            "error_type",
            "app_name",
            "original_value",
            "reference_value",
            "baseline_mean",
            "ratio_db",
            "ratio_derived",
            "score",
            "severity",
            "is_spike",
            "is_burst",
            "detection_method",
            "known_peak_id",
            "suspected_root_cause",
            "error_message",
        ])
        for r in rows:
            ts, ns, et, ov, rv, bm, ratio_db, score, sev, is_spike, is_burst, method, msg, root_cause, known_peak_id, app_name = r
            writer.writerow([
                ts.isoformat() if ts else "",
                ns or "",
                et or "",
                app_name or "",
                ov,
                rv,
                bm,
                ratio_db,
                safe_ratio(ov, rv),
                float(score) if score is not None else None,
                sev,
                bool(is_spike),
                bool(is_burst),
                method or "",
                known_peak_id,
                (root_cause or "").replace("\n", " ")[:350],
                (msg or "").replace("\n", " ")[:1000],
            ])

    grouped = defaultdict(lambda: {
        "count": 0,
        "first_seen": None,
        "last_seen": None,
        "max_score": None,
        "max_ratio": None,
        "spikes": 0,
        "bursts": 0,
        "sample_messages": [],
    })

    for r in rows:
        ts, ns, et, ov, rv, bm, ratio_db, score, sev, is_spike, is_burst, method, msg, root_cause, known_peak_id, app_name = r
        key = (ns or "unknown", et or "unknown", method or "unknown")
        g = grouped[key]
        g["count"] += 1
        if is_spike:
            g["spikes"] += 1
        if is_burst:
            g["bursts"] += 1

        if g["first_seen"] is None or (ts and ts < g["first_seen"]):
            g["first_seen"] = ts
        if g["last_seen"] is None or (ts and ts > g["last_seen"]):
            g["last_seen"] = ts

        score_val = float(score) if score is not None else None
        if score_val is not None and (g["max_score"] is None or score_val > g["max_score"]):
            g["max_score"] = score_val

        ratio_val = ratio_db if ratio_db is not None else safe_ratio(ov, rv)
        if ratio_val is not None:
            ratio_val = float(ratio_val)
            if g["max_ratio"] is None or ratio_val > g["max_ratio"]:
                g["max_ratio"] = ratio_val

        if msg:
            normalized_msg = " ".join(msg.split())
            if normalized_msg not in g["sample_messages"] and len(g["sample_messages"]) < 3:
                g["sample_messages"].append(normalized_msg[:350])

    summary_items = []
    for (ns, et, method), g in grouped.items():
        summary_items.append({
            "namespace": ns,
            "error_type": et,
            "detection_method": method,
            "count": g["count"],
            "spikes": g["spikes"],
            "bursts": g["bursts"],
            "first_seen": g["first_seen"].isoformat() if g["first_seen"] else None,
            "last_seen": g["last_seen"].isoformat() if g["last_seen"] else None,
            "max_score": g["max_score"],
            "max_ratio": g["max_ratio"],
            "sample_messages": g["sample_messages"],
        })

    summary_items.sort(key=lambda x: x["count"], reverse=True)

    summary_json = output_dir / f"peaks_last_{days}d_{mode}_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now.isoformat(),
            "mode": mode,
            "window_since": since.isoformat(),
            "window_until": now.isoformat(),
            "total_detected_peaks": len(rows),
            "unique_peak_groups": len(summary_items),
            "groups": summary_items,
        }, f, ensure_ascii=False, indent=2)

    summary_md = output_dir / f"peaks_last_{days}d_{mode}_summary.md"
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write(f"# Peaks last {days} days ({mode})\n\n")
        f.write(f"- Generated at: {now.isoformat()}\n")
        f.write(f"- Window: {since.isoformat()} → {now.isoformat()}\n")
        if mode == "strict":
            f.write(f"- Total detected peaks (is_spike OR is_burst): {len(rows)}\n")
        else:
            f.write(f"- Total detected peaks (is_spike OR is_burst OR score>=30): {len(rows)}\n")
        f.write(f"- Unique grouped signatures: {len(summary_items)}\n\n")

        f.write("## Top grouped peaks\n\n")
        f.write("| Namespace | Error Type | Method | Count | Spikes | Bursts | First Seen | Last Seen | Max Score | Max Ratio |\n")
        f.write("|---|---|---|---:|---:|---:|---|---|---:|---:|\n")
        for item in summary_items[:100]:
            f.write(
                f"| {item['namespace']} | {item['error_type']} | {item['detection_method']} | "
                f"{item['count']} | {item['spikes']} | {item['bursts']} | "
                f"{item['first_seen'] or ''} | {item['last_seen'] or ''} | "
                f"{item['max_score'] if item['max_score'] is not None else ''} | "
                f"{item['max_ratio'] if item['max_ratio'] is not None else ''} |\n"
            )

    return full_csv, summary_json, summary_md


def _format_duration(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return "N/A"
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    sec = int((end - start).total_seconds())
    if sec < 0:
        return "N/A"
    if sec < 60:
        return f"{sec}s"
    minutes, seconds = divmod(sec, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def load_known_peaks_registry(project_root: Path):
    peaks_yaml = project_root / "registry" / "known_peaks.yaml"
    if not peaks_yaml.exists():
        return []
    try:
        data = yaml.safe_load(peaks_yaml.read_text(encoding="utf-8")) or []
    except Exception:
        return []

    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        peak_type = str(item.get("peak_type") or "").upper()
        namespaces = set(item.get("affected_namespaces") or [])
        entries.append({
            "id": item.get("id"),
            "problem_key": item.get("problem_key") or "",
            "peak_type": peak_type,
            "affected_namespaces": namespaces,
            "flow": ((item.get("problem_key") or "").split(":")[2] if len((item.get("problem_key") or "").split(":")) >= 4 else "unknown"),
            "first_seen": item.get("first_seen"),
            "last_seen": item.get("last_seen"),
        })
    return entries


def _normalize_token(s: str | None) -> str:
    if not s:
        return ""
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")


def derive_flow_from_app_name(app_name: str | None) -> str:
    if not app_name:
        return "unknown"
    name = app_name.lower()
    for pattern, flow in FLOW_PATTERNS.items():
        if pattern in name:
            return flow

    parts = name.replace("_", "-").split("-")
    skip_prefixes = {"bff", "bl", "feapi", "pcb", "pca", "ch", "v1", "v2", "v3"}
    meaningful = [p for p in parts if p and p not in skip_prefixes and not p.isdigit()]
    if meaningful:
        return "_".join(meaningful[:2])
    return "unknown"


def match_known_peak_registry(namespace: str, peak_type: str, error_type: str, app_name: str, known_entries):
    ns = namespace or ""
    pt = (peak_type or "").upper()
    et = _normalize_token(error_type)
    flow = derive_flow_from_app_name(app_name)
    if not ns or not pt or not known_entries:
        return None

    candidates = []
    for entry in known_entries:
        if entry.get("peak_type") != pt:
            continue
        if ns not in entry.get("affected_namespaces", set()):
            continue

        score = 1
        pk = _normalize_token(entry.get("problem_key", ""))
        if flow != "unknown" and flow == entry.get("flow"):
            score += 3
        if et and et in pk:
            score += 2
        candidates.append((score, entry))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    top_score, top_entry = candidates[0]

    # Strong match when error_type token is aligned with problem_key.
    if top_score >= 2:
        return top_entry

    # Weak fallback only when there is exactly one namespace+peak_type candidate.
    if len(candidates) == 1:
        return top_entry

    # Ambiguous namespace+peak_type without error_type alignment.
    return None


def write_detected_24h_report(strict_rows, now: datetime, output_dir: Path, known_registry_entries, known_peaks_db_rows: int):
    since_24h = now - timedelta(hours=24)
    def _to_aware(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    rows_24h = [r for r in strict_rows if _to_aware(r[0]) and _to_aware(r[0]) >= since_24h]

    full_csv = output_dir / "peaks_detected_last_24h_strict_full.csv"
    with open(full_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "namespace",
            "error_type",
            "app_name",
            "detection_method",
            "known_status",
            "known_peak_id_db",
            "known_peak_id_registry",
            "is_spike",
            "is_burst",
            "score",
            "original_value",
            "reference_value",
            "baseline_mean",
            "ratio_db",
            "ratio_derived",
            "severity",
            "suspected_root_cause",
            "error_message",
        ])
        for ts, ns, et, ov, rv, bm, ratio_db, score, sev, is_spike, is_burst, method, msg, root_cause, known_peak_id_db, app_name in rows_24h:
            peak_type = "SPIKE" if is_spike else "BURST" if is_burst else "UNKNOWN"
            registry_match = match_known_peak_registry(ns or "", peak_type, et or "", app_name or "", known_registry_entries)
            known_peak_id_registry = registry_match.get("id") if registry_match else None
            known_status = "KNOWN" if (known_peak_id_db is not None or known_peak_id_registry is not None) else "NEW"
            writer.writerow([
                ts.isoformat() if ts else "",
                ns or "",
                et or "",
                app_name or "",
                method or "",
                known_status,
                known_peak_id_db,
                known_peak_id_registry,
                bool(is_spike),
                bool(is_burst),
                float(score) if score is not None else None,
                ov,
                rv,
                bm,
                ratio_db,
                safe_ratio(ov, rv),
                sev,
                (root_cause or "").replace("\n", " ")[:350],
                (msg or "").replace("\n", " "),
            ])

    grouped = defaultdict(lambda: {
        "count": 0,
        "spikes": 0,
        "bursts": 0,
        "first_seen": None,
        "last_seen": None,
        "max_score": None,
        "max_ratio": None,
        "nonzero_original": 0,
        "nonzero_reference": 0,
        "known_count": 0,
        "known_peak_ids_db": set(),
        "known_peak_ids_registry": set(),
        "root_causes": [],
        "messages": [],
    })

    for ts, ns, et, ov, rv, bm, ratio_db, score, sev, is_spike, is_burst, method, msg, root_cause, known_peak_id_db, app_name in rows_24h:
        key = (ns or "unknown", et or "unknown", method or "unknown")
        g = grouped[key]
        g["count"] += 1
        if is_spike:
            g["spikes"] += 1
        if is_burst:
            g["bursts"] += 1
        if g["first_seen"] is None or (ts and ts < g["first_seen"]):
            g["first_seen"] = ts
        if g["last_seen"] is None or (ts and ts > g["last_seen"]):
            g["last_seen"] = ts
        score_val = float(score) if score is not None else None
        if score_val is not None and (g["max_score"] is None or score_val > g["max_score"]):
            g["max_score"] = score_val
        ratio_val = ratio_db if ratio_db is not None else safe_ratio(ov, rv)
        if ratio_val is not None:
            ratio_val = float(ratio_val)
            if g["max_ratio"] is None or ratio_val > g["max_ratio"]:
                g["max_ratio"] = ratio_val
        if ov is not None and float(ov) > 0:
            g["nonzero_original"] += 1
        if rv is not None and float(rv) > 0:
            g["nonzero_reference"] += 1
        peak_type = "SPIKE" if is_spike else "BURST" if is_burst else "UNKNOWN"
        registry_match = match_known_peak_registry(ns or "", peak_type, et or "", app_name or "", known_registry_entries)
        known_peak_id_registry = registry_match.get("id") if registry_match else None
        if known_peak_id_db is not None or known_peak_id_registry is not None:
            g["known_count"] += 1
        if known_peak_id_db is not None:
            g["known_peak_ids_db"].add(str(known_peak_id_db))
        if known_peak_id_registry:
            g["known_peak_ids_registry"].add(str(known_peak_id_registry))
        if root_cause:
            normalized_root = " ".join(str(root_cause).split())
            if normalized_root not in g["root_causes"] and len(g["root_causes"]) < 3:
                g["root_causes"].append(normalized_root)
        if msg:
            normalized = " ".join(msg.split())
            if normalized not in g["messages"] and len(g["messages"]) < 5:
                g["messages"].append(normalized)

    groups = []
    for (ns, et, method), g in grouped.items():
        groups.append({
            "namespace": ns,
            "error_type": et,
            "detection_method": method,
            "count": g["count"],
            "known_status": "KNOWN" if g["known_count"] > 0 else "NEW",
            "known_count": g["known_count"],
            "new_count": g["count"] - g["known_count"],
            "known_peak_ids_db": sorted(g["known_peak_ids_db"]),
            "known_peak_ids_registry": sorted(g["known_peak_ids_registry"]),
            "spikes": g["spikes"],
            "bursts": g["bursts"],
            "first_seen": g["first_seen"].isoformat() if g["first_seen"] else None,
            "last_seen": g["last_seen"].isoformat() if g["last_seen"] else None,
            "duration": _format_duration(g["first_seen"], g["last_seen"]),
            "max_score": g["max_score"],
            "max_ratio": g["max_ratio"],
            "nonzero_original": g["nonzero_original"],
            "nonzero_reference": g["nonzero_reference"],
            "root_causes": g["root_causes"],
            "sample_messages": g["messages"],
        })

    groups.sort(key=lambda x: (x["count"], x["max_score"] or 0), reverse=True)

    summary_json = output_dir / "peaks_detected_last_24h_strict_summary.json"
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now.isoformat(),
            "window_since": since_24h.isoformat(),
            "window_until": now.isoformat(),
            "definition": "strict = is_spike OR is_burst",
            "known_check": "automatic: peak_investigation.known_peak_id + registry/known_peaks.yaml fallback",
            "known_source_stats": {
                "known_peaks_table_rows": known_peaks_db_rows,
                "registry_known_peaks_entries": len(known_registry_entries),
            },
            "total_events": len(rows_24h),
            "total_groups": len(groups),
            "known_groups": sum(1 for g in groups if g["known_status"] == "KNOWN"),
            "new_groups": sum(1 for g in groups if g["known_status"] == "NEW"),
            "groups": groups,
        }, f, ensure_ascii=False, indent=2)

    summary_md = output_dir / "peaks_detected_last_24h_strict_summary.md"
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write("# Detected Peaks - Last 24h (strict)\n\n")
        f.write(f"- Generated at: {format_ts(now)}\n")
        f.write(f"- Window: {format_ts(since_24h)} → {format_ts(now)}\n")
        f.write("- Definition: strict = is_spike OR is_burst\n")
        f.write("- Known-check: automatic (`known_peak_id` from DB + `registry/known_peaks.yaml` fallback)\n")
        f.write(f"- Known source rows: DB known_peaks={known_peaks_db_rows}, registry known_peaks={len(known_registry_entries)}\n")
        f.write(f"- Total detected events: {len(rows_24h)}\n")
        f.write(f"- Total grouped peaks: {len(groups)}\n\n")

        f.write("## Grouped overview\n\n")
        f.write("| Namespace | Error Type | Method | Known? | Events | New | Spikes | Bursts | From | To | Duration | Max score | Max ratio |\n")
        f.write("|---|---|---|---|---:|---:|---:|---:|---|---|---|---:|---:|\n")
        for g in groups:
            f.write(
                f"| {g['namespace']} | {g['error_type']} | {g['detection_method']} | {g['known_status']} | {g['count']} | {g['new_count']} | "
                f"{g['spikes']} | {g['bursts']} | {g['first_seen'] or ''} | {g['last_seen'] or ''} | {g['duration']} | "
                f"{g['max_score'] if g['max_score'] is not None else ''} | {g['max_ratio'] if g['max_ratio'] is not None else ''} |\n"
            )

        f.write("\n## Detail samples by group\n\n")
        for idx, g in enumerate(groups, start=1):
            f.write(f"### {idx}. {g['namespace']} / {g['error_type']} / {g['detection_method']}\n\n")
            f.write(f"- Event window: {g['first_seen']} → {g['last_seen']} ({g['duration']})\n")
            f.write(f"- Totals: events={g['count']}, new={g['new_count']}, spikes={g['spikes']}, bursts={g['bursts']}\n")
            f.write(f"- Known status: {g['known_status']}\n")
            f.write(f"- Known IDs (DB): {', '.join(g['known_peak_ids_db']) if g['known_peak_ids_db'] else '(none)'}\n")
            f.write(f"- Known IDs (registry): {', '.join(g['known_peak_ids_registry']) if g['known_peak_ids_registry'] else '(none)'}\n")
            f.write(f"- Metric profile: nonzero_original={g['nonzero_original']}, nonzero_reference={g['nonzero_reference']}, max_score={g['max_score']}, max_ratio={g['max_ratio']}\n")
            f.write(f"- Root cause candidates: {' | '.join(g['root_causes']) if g['root_causes'] else '(none)'}\n")
            f.write("- Sample messages:\n")
            if g["sample_messages"]:
                for i, m in enumerate(g["sample_messages"], start=1):
                    f.write(f"  {i}) {m}\n")
            else:
                f.write("  (none)\n")
            f.write("\n")

    return full_csv, summary_json, summary_md


def build_group_stats(rows):
    stats = defaultdict(lambda: {
        "count": 0,
        "first_seen": None,
        "last_seen": None,
        "spikes": 0,
        "bursts": 0,
        "nonzero_original": 0,
        "nonzero_reference": 0,
        "max_score": None,
    })

    for r in rows:
        ts, ns, et, ov, rv, bm, ratio_db, score, sev, is_spike, is_burst, method, msg, root_cause, known_peak_id, app_name = r
        key = (ns or "unknown", et or "unknown", method or "unknown")
        g = stats[key]
        g["count"] += 1
        if is_spike:
            g["spikes"] += 1
        if is_burst:
            g["bursts"] += 1
        if ov is not None and float(ov) > 0:
            g["nonzero_original"] += 1
        if rv is not None and float(rv) > 0:
            g["nonzero_reference"] += 1
        if g["first_seen"] is None or (ts and ts < g["first_seen"]):
            g["first_seen"] = ts
        if g["last_seen"] is None or (ts and ts > g["last_seen"]):
            g["last_seen"] = ts
        score_val = float(score) if score is not None else None
        if score_val is not None and (g["max_score"] is None or score_val > g["max_score"]):
            g["max_score"] = score_val

    return stats


def main(days: int = 2):
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    workspace_root = project_root.parent
    output_dir = workspace_root / "ai-data"
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    conn, cur = connect_db(project_root)

    broad_rows = fetch_rows(cur, since, strict=False)
    strict_rows = fetch_rows(cur, since, strict=True)
    group_stats = build_group_stats(broad_rows)
    known_registry_entries = load_known_peaks_registry(project_root)
    cur.execute("SELECT COUNT(*) FROM known_peaks;")
    known_peaks_db_rows = int(cur.fetchone()[0])

    broad_full_csv, broad_summary_json, broad_summary_md = write_outputs(
        broad_rows, now, since, days, output_dir, mode="broad"
    )
    strict_full_csv, strict_summary_json, strict_summary_md = write_outputs(
        strict_rows, now, since, days, output_dir, mode="strict"
    )
    peaks24_full_csv, peaks24_summary_json, peaks24_summary_md = write_detected_24h_report(
        strict_rows, now, output_dir, known_registry_entries, known_peaks_db_rows
    )

    # Pick three high-quality detail examples from peaks window
    cur.execute(
        """
        SELECT
            timestamp,
            namespace,
            error_type,
            original_value,
            reference_value,
            score,
            is_spike,
            is_burst,
            detection_method,
            error_message
        FROM peak_investigation
        WHERE timestamp >= %s
                    AND (
                                is_spike = TRUE
                         OR is_burst = TRUE
                         OR score >= 30
                    )
          AND error_message IS NOT NULL
          AND length(trim(error_message)) > 30
        ORDER BY score DESC NULLS LAST, timestamp DESC
        LIMIT 5000;
        """,
        (since,)
    )
    candidates = cur.fetchall()

    scored = []
    for row in candidates:
        ts, ns, et, ov, rv, score, is_spike, is_burst, method, msg = row
        quality = score_for_quality(msg, et)
        if msg:
            lowered = msg.lower()
            if "error handled" in lowered:
                quality -= 4
            if "handle fault" in lowered:
                quality -= 2
        scored.append((quality, row))

    scored.sort(key=lambda x: (x[0], float(x[1][5]) if x[1][5] is not None else 0), reverse=True)

    selected = []
    seen_families = set()
    for quality, row in scored:
        ts, ns, et, ov, rv, score, is_spike, is_burst, method, msg = row
        family = (et or "unknown", ns or "unknown", method or "unknown", "spike" if is_spike else "burst")
        if family in seen_families:
            continue
        if msg and len(msg) > 80 and "error handled" not in msg.lower():
            selected.append((quality, row))
            seen_families.add(family)
        if len(selected) == 3:
            break

    # fallback if too strict
    if len(selected) < 3:
        for quality, row in scored:
            if (quality, row) not in selected:
                selected.append((quality, row))
            if len(selected) == 3:
                break

    detail_md = output_dir / f"detail_examples_last_{days}d.md"
    with open(detail_md, "w", encoding="utf-8") as f:
        f.write(f"# Detail quality examples (last {days} days)\n\n")
        f.write(f"- Generated at: {format_ts(now)}\n")
        f.write(f"- Window: {format_ts(since)} → {format_ts(now)}\n")
        f.write("- Note: `original_value` and `reference_value` can be 0.0 in some BURST/backfill records; the important context is group window + counts below.\n\n")
        for idx, (quality, row) in enumerate(selected, start=1):
            ts, ns, et, ov, rv, score, is_spike, is_burst, method, msg = row
            derived_ratio = safe_ratio(ov, rv)
            key = (ns or "unknown", et or "unknown", method or "unknown")
            group = group_stats.get(key, {})
            f.write(f"## Example {idx}\n\n")
            f.write(f"- Timestamp: {format_ts(ts)}\n")
            f.write(f"- Namespace: {ns}\n")
            f.write(f"- Error type: {et}\n")
            f.write(f"- Detection method: {method}\n")
            f.write(f"- Peak type: {'SPIKE' if is_spike else 'BURST'}\n")
            f.write(f"- Score: {float(score) if score is not None else 'N/A'}\n")
            f.write(f"- Original value: {ov}\n")
            f.write(f"- Reference value: {rv}\n")
            f.write(f"- Derived ratio: {derived_ratio if derived_ratio is not None else 'N/A'}\n")
            f.write(f"- Quality score: {quality}\n")
            f.write(f"- Group window (same namespace+error_type+method): {format_ts(group.get('first_seen'))} → {format_ts(group.get('last_seen'))}\n")
            f.write(f"- Group totals: events={group.get('count', 0)}, spikes={group.get('spikes', 0)}, bursts={group.get('bursts', 0)}\n")
            f.write(f"- Group metric quality: nonzero_original={group.get('nonzero_original', 0)}, nonzero_reference={group.get('nonzero_reference', 0)}, max_score={group.get('max_score', 'N/A')}\n")
            f.write(f"- Detail candidate:\n\n")
            f.write(f"```\n{(msg or '').strip()}\n```\n\n")

    cur.close()
    conn.close()

    print("DONE")
    print(f"BROAD_FULL_CSV={broad_full_csv}")
    print(f"BROAD_SUMMARY_JSON={broad_summary_json}")
    print(f"BROAD_SUMMARY_MD={broad_summary_md}")
    print(f"STRICT_FULL_CSV={strict_full_csv}")
    print(f"STRICT_SUMMARY_JSON={strict_summary_json}")
    print(f"STRICT_SUMMARY_MD={strict_summary_md}")
    print(f"PEAKS24_FULL_CSV={peaks24_full_csv}")
    print(f"PEAKS24_SUMMARY_JSON={peaks24_summary_json}")
    print(f"PEAKS24_SUMMARY_MD={peaks24_summary_md}")
    print(f"DETAIL_MD={detail_md}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze recent peaks and detail quality")
    parser.add_argument("--days", type=int, default=2, help="Lookback days (default: 2)")
    args = parser.parse_args()
    main(days=args.days)
