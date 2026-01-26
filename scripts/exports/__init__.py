"""
Exports - Tabulkové exporty pro operátory
=========================================

Export pravidla (V6.1):
- latest/   → VŽDY přepsat (overwrite) - aktuální snapshot
- daily/    → 1× denně, kontrola existence
- weekly/   → 1× týdně, kontrola existence

Struktura:
    exports/
    ├── latest/     ← overwrite (15-min běhy)
    ├── daily/      ← once per day
    └── weekly/     ← once per week

Použití:
    from exports import export_latest, export_daily

    export_latest(registry, './exports')   # overwrite
    export_daily(registry, './exports')    # once per day
"""

from .table_exporter import (
    TableExporter,
    export_latest,
    export_daily,
    export_weekly,
    # Backward compat (deprecated)
    export_errors_table,
    export_peaks_table,
)

__all__ = [
    'TableExporter',
    'export_latest',
    'export_daily',
    'export_weekly',
    # Deprecated
    'export_errors_table',
    'export_peaks_table',
]
