# Duplicity - KOMPLETNE VYRESENO

**Datum:** 2026-01-26
**Status:** Hotovo

---

## Smazano / Prejmenovano

| Polozka | Akce |
|---------|------|
| `/fixes/` | Smazano (zkopirovan do scripts/) |
| `/knowledge/` | Smazano (duplicita registry/) |
| `/scripts/incident_analysis/` | Smazano (ponechana root verze s v5.3) |
| `backfill.py`, `backfill_v2.py`, `backfill_v5.3.py` | Smazano |
| `regular_phase.py`, `regular_phase_v5.3.py` | Smazano |
| `/analyze_incidents.py` (root) | Smazano |
| `*:Zone.Identifier` | Smazano |
| `phase_c_detect.py` (puvodni) | Nahrazeno novou verzi |

---

## Aktualni skripty

| Skript | Popis |
|--------|-------|
| `backfill.py` | Backfill s registry integraci |
| `regular_phase.py` | 15-min pipeline s registry |
| `migrate_registry.py` | Migrace 700k -> stovky problem_keys |
| `phase_c_detect.py` | S registry integraci |

---

## Finalni struktura

```
ai-log-analyzer/
├── config/
│   └── known_issues/          # Knowledge base
├── docs/
├── incident_analysis/         # Propagation, version change
├── k8s/
├── registry/                  # Problem registry
├── scripts/
│   ├── core/
│   │   ├── problem_registry.py
│   │   └── ...
│   ├── pipeline/
│   │   ├── phase_c_detect.py     # S registry
│   │   └── ...
│   ├── backfill.py
│   ├── regular_phase.py
│   └── migrate_registry.py
└── README.md
```
