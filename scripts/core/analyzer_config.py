#!/usr/bin/env python3
"""
Analyzer Config - načítání config/analyzer.yaml (BEZ tajemství)
==============================================================

Jeden přehledný konfigurák rozdělený do sekcí. Účty/hesla sem NEPATŘÍ
(zůstávají v .env / CyberArk). Cíl: analyzátor použitelný i jinými týmy.

Priorita: ENV proměnná > analyzer.yaml > vestavěný default.

Použití:
    from core.analyzer_config import get_config
    cfg = get_config()
    cfg.generic_error_classes        # set[str]
    cfg.generic_error_class_min_flows  # int
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / 'config' / 'analyzer.yaml'

# Vestavěné defaulty (fallback, když analyzer.yaml chybí). Empirické z ES/registry.
_DEFAULT_GENERIC_CLASSES = {
    'servicebusinessexception', 'constraintviolationexception', 'unknownerror',
    'notfounderror', 'not_found', 'forbiddenerror', 'servererror',
    'unauthorizederror', 'accessdeniedexception', 'mismatchedinputexception',
    'illegalargumentexception', 'internal_error',
}
_DEFAULT_MIN_FLOWS = 8
_DEFAULT_MAX_TRACES = 20000
_DEFAULT_MAX_EVENTS_PER_TRACE = 500


def _split_env_list(value: str) -> List[str]:
    return [x.strip() for x in value.split(',') if x.strip()]


class AnalyzerConfig:
    """Načtená konfigurace (immutable po vytvoření)."""

    def __init__(self, raw: Optional[Dict[str, Any]] = None):
        raw = raw or {}
        classification = raw.get('classification', {}) or {}
        trace = raw.get('trace', {}) or {}

        # generic_error_classes: ENV (csv) > yaml > default. Normalizováno na lowercase.
        env_generic = os.getenv('GENERIC_ERROR_CLASSES', '').strip()
        if env_generic:
            classes = _split_env_list(env_generic)
        else:
            classes = classification.get('generic_error_classes') or list(_DEFAULT_GENERIC_CLASSES)
        self.generic_error_classes: Set[str] = {str(c).strip().lower() for c in classes if str(c).strip()}

        self.generic_error_class_min_flows: int = int(
            os.getenv('GENERIC_ERROR_CLASS_MIN_FLOWS')
            or classification.get('generic_error_class_min_flows')
            or _DEFAULT_MIN_FLOWS
        )

        self.trace_ownership_enabled: bool = _as_bool(
            os.getenv('TRACE_OWNERSHIP_ENABLED'),
            trace.get('ownership_enabled', True),
        )
        self.max_traces: int = int(
            os.getenv('TRACE_TIMELINE_MAX_TRACES')
            or trace.get('max_traces')
            or _DEFAULT_MAX_TRACES
        )
        self.max_events_per_trace: int = int(
            os.getenv('TRACE_TIMELINE_MAX_EVENTS_PER_TRACE')
            or trace.get('max_events_per_trace')
            or _DEFAULT_MAX_EVENTS_PER_TRACE
        )

    def is_generic_error_class(self, error_class: str) -> bool:
        """True, pokud je error_class generický (sub-klíčovat zprávou)."""
        if not error_class:
            return False
        return error_class.strip().lower() in self.generic_error_classes


def _as_bool(env_value: Optional[str], default: bool) -> bool:
    if env_value is None or env_value == '':
        return bool(default)
    return env_value.strip().lower() in {'1', 'true', 'yes', 'on'}


_cached: Optional[AnalyzerConfig] = None


def get_config(reload: bool = False) -> AnalyzerConfig:
    """Vrátí (cachovanou) konfiguraci. reload=True vynutí znovunačtení."""
    global _cached
    if _cached is not None and not reload:
        return _cached

    raw: Dict[str, Any] = {}
    if HAS_YAML and _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            raw = {}
    _cached = AnalyzerConfig(raw)
    return _cached
