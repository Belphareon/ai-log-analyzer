# Dokumentace AI Log Analyzer v5.3.1

## Obsah

| Dokument | Popis |
|----------|-------|
| [QUICKSTART.md](QUICKSTART.md) | 5 minut k prvnímu reportu |
| [INSTALLATION.md](INSTALLATION.md) | Podrobná instalace |
| [INSTALLATION_CHECKLIST.md](INSTALLATION_CHECKLIST.md) | Checklist pro produkci |
| [PIPELINE_V4_ARCHITECTURE.md](PIPELINE_V4_ARCHITECTURE.md) | Technická architektura |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Řešení problémů |
| [ADD_APPLICATION_VERSION.md](ADD_APPLICATION_VERSION.md) | Přidání version pole do ES |

## Další dokumenty

| Dokument | Popis |
|----------|-------|
| [../README.md](../README.md) | Hlavní README projektu |
| [../INSTALL.md](../INSTALL.md) | Rychlá instalace |

## Změny v5.3.1

### Architektura

```python
# Scope (KDE) a Propagation (JAK) jsou oddělené
class IncidentAnalysis:
    scope: IncidentScope          # apps, root_apps, downstream_apps
    propagation: IncidentPropagation  # propagated, propagation_time_sec
```

### Report generation

- Report se generuje VŽDY (i prázdný)
- Output do `scripts/reports/`

### Registry

- Append-only evidence všech detekovaných problémů
- `registry/known_errors.yaml` + `.md`
- `registry/known_peaks.yaml` + `.md`

## Quick Links

```bash
# Spuštění
python scripts/regular_phase_v5.3.py

# Výstup
cat scripts/reports/incident_analysis_15min_*.txt

# Registry
cat registry/known_errors.yaml
```
