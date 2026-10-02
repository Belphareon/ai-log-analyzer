"""Shared classification helpers for peak notification and export paths."""

import os
from typing import Any, Dict, Optional, Tuple


TEST_PEAK_ORIGINATORS = tuple(
    item.strip().lower()
    for item in os.getenv('TEST_PEAK_ORIGINATORS', 'MochaXTestApp').split(',')
    if item.strip()
)
TEST_PEAK_MIN_SHARE = float(os.getenv('TEST_PEAK_MIN_SHARE', '0.5'))


def _normalize_count_dict(counts: Optional[Dict[str, Any]]) -> Dict[str, int]:
    normalized: Dict[str, int] = {}
    for key, value in (counts or {}).items():
        if not key:
            continue
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            normalized[str(key)] = count
    return normalized


def dominant_count_entry(counts: Optional[Dict[str, Any]]) -> Tuple[str, int]:
    normalized = _normalize_count_dict(counts)
    if not normalized:
        return '', 0
    return max(normalized.items(), key=lambda item: (item[1], item[0]))


def is_test_peak_counts(
    originator_counts: Optional[Dict[str, Any]], total_count: int
) -> bool:
    top_originator, top_count = dominant_count_entry(originator_counts)
    if top_originator.strip().lower() not in TEST_PEAK_ORIGINATORS:
        return False
    denominator = max(
        int(total_count or 0),
        sum(_normalize_count_dict(originator_counts).values()),
        1,
    )
    return (top_count / denominator) >= TEST_PEAK_MIN_SHARE