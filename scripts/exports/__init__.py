"""
Exports - Tabulkové exporty pro operátory
=========================================

Generuje filtrovatelné tabulky z Problem Registry:
- CSV (Excel, filtry, Jira import)
- Markdown (human-readable)
- JSON (API, další zpracování)
"""

from .table_exporter import (
    TableExporter,
    export_errors_table,
    export_peaks_table,
)

__all__ = [
    'TableExporter',
    'export_errors_table',
    'export_peaks_table',
]
